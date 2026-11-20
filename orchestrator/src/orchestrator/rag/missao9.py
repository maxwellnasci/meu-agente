"""Missao 9: formato do Max nas respostas (REGRAS_DO_MANUAL v2 x v1).

UMA variavel: o texto das regras do manual no synthesize_final. Busca, top_k,
indice, juiz (v1), roteamento e criterio de formato (formato_v1.yaml) ficam
iguais. Criterios pre-registrados em docs/RAG.md (secao Missao 9), ANTES de
rodar; nenhum outro criterio entra depois.

    cd orchestrator
    .venv/bin/python -m orchestrator.rag.missao9              # plano + custo + comandos (gratis)
    #   ... os 8 comandos pagos impressos pelo plano, NA ORDEM (intercalada) ...
    .venv/bin/python -m orchestrator.rag.missao9 --comparar   # gratis: aplica a regra de decisao

As respostas variam a cada execucao (o synth nao fixa temperatura), por isso
N=2 por versao, intercalado: v1-r1, v2-r1, v1-r2, v2-r2.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from orchestrator.rag import avaliar_respostas as av
from orchestrator.rag import juiz

DIR_M9 = av.DIR_SAIDA.parent / "m9"
RESPOSTAS_M8 = av.DIR_SAIDA / "respostas-2026-11-19.json"
VERSOES = ("v1", "v2")
RODADAS = ("r1", "r2")
ORDEM = (("v1", "r1"), ("v2", "r1"), ("v1", "r2"), ("v2", "r2"))

# Hash do texto das regras PRE-REGISTRADO (docs/RAG.md, Missao 9). Mudar o
# texto depois disso invalida a comparacao (vira v3 com novo pre-registro).
HASH_REGRAS_PRE_REGISTRO = {
    "v1": "3f4ca553845cc40ed10451f70df9357f2afad2ac2f76d265198be0e6be498240",  # = Missao 8
    "v2": "f8cdc6c099ba109c080a8640b55c9d9001a9de439997f6cb035696fbff69f448",
}

# Teto TOTAL da missao: US$ 1,00. Orcamento por invocacao (o script corta
# depois da pergunta que estourar): 4 x 0,08 + 4 x 0,15 = 0,92.
TETO_TOTAL_USD = 1.00
ORCAMENTO_RESPOSTAS_USD = 0.08
ORCAMENTO_JUIZ_USD = 0.15
# Custo REAL medido na Missao 8 (respostas-2026-11-19 / julgamento-2026-11-20).
CUSTO_M8_USD = {"respostas": 0.0329, "juiz": 0.0708}

# Regra de decisao (pre-registro): metricas e tolerancia.
METRICA_FORMATO = "g_total"                               # a) v2 > v1 (estrito), media das 2 rodadas
METRICAS_SEM_QUEDA = ("b_fatos", "f_correcao", "d_sem_grave")  # b) media_v1 - media_v2 <= 1,0
QUEDA_MAXIMA = 1.0

_SIM_NAO = re.compile(r"^(sim|nao)\b")


def caminhos(versao: str, rodada: str) -> tuple[Path, Path]:
    return DIR_M9 / f"respostas-{versao}-{rodada}.json", DIR_M9 / f"julgamento-{versao}-{rodada}.json"


def comandos() -> list[str]:
    base = ".venv/bin/python -m orchestrator.rag.avaliar_respostas --executar"
    saida = []
    for v, r in ORDEM:
        resp, julg = (p.relative_to(av.ORCHESTRATOR_DIR) for p in caminhos(v, r))
        saida.append(f"{base} --etapa respostas --regras {v} --orcamento {ORCAMENTO_RESPOSTAS_USD} --saida {resp}")
        saida.append(f"{base} --etapa julgar --sem-calibracao --orcamento {ORCAMENTO_JUIZ_USD} "
                     f"--respostas {resp} --saida {julg}")
    return saida


def primeira_palavra(resposta: str | None) -> str | None:
    """"sim"/"nao" se a 1a linha nao vazia (limpa de markdown, normalizada)
    comeca pela palavra inteira; senao None. Mesmo preparo da (g-a)."""
    for linha in (resposta or "").split("\n"):
        limpa = av.limpar_linha(linha)
        if limpa:
            m = _SIM_NAO.search(av.normalizar(limpa))
            return m.group(1) if m else None
    return None


def esperado_sim_nao(gabarito: list[dict], ids) -> dict[str, str]:
    """1a palavra da resposta_esperada do gabarito (q05 -> sim; q01/q02/q04/q10 -> nao)."""
    saida = {}
    for g in gabarito:
        if g["id"] in ids:
            p = primeira_palavra(g["resposta_esperada"])
            if p is None:
                raise ValueError(f"{g['id']}: resposta_esperada nao comeca por Sim/Nao")
            saida[g["id"]] = p
    return saida


def violacoes_sim_nao(respostas: dict, esperado: dict[str, str]) -> tuple[list[dict], list[str]]:
    """c) Sim/Nao que CONTRADIZ o gabarito. Resposta que nao comeca por
    Sim/Nao nao viola (so falha a g-a). Resposta fixa sem LLM (indisponivel /
    nao cobre) fica fora e e listada."""
    violacoes, fixas = [], []
    por_id = {r["id"]: r for r in respostas["perguntas"]}
    for qid, quer in esperado.items():
        r = por_id.get(qid)
        if not r:
            continue
        if r.get("resposta_fixa_sem_llm"):
            fixas.append(qid)
            continue
        veio = primeira_palavra(r.get("resposta_crua"))
        if veio is not None and veio != quer:
            violacoes.append({"id": qid, "esperado": quer, "veio": veio})
    return violacoes, fixas


def _checar_integridade(v: str, r: str, respostas: dict, julgamento: dict, regras_hash: dict[str, str]) -> list[str]:
    problemas = []
    gravada = (respostas.get("config") or {}).get("rag_regras_versao")
    if gravada != v:
        problemas.append(f"{v}-{r}: respostas gravadas com regras {gravada!r}")
    if (respostas.get("hashes") or {}).get("regras_do_manual") != regras_hash[v]:
        problemas.append(f"{v}-{r}: hash das regras difere do texto {v} atual")
    hash_resp = av.sha256_texto(json.dumps(respostas, sort_keys=True, ensure_ascii=False))
    if (julgamento.get("hashes") or {}).get("respostas") != hash_resp:
        problemas.append(f"{v}-{r}: o julgamento nao e destas respostas")
    juiz_hashes = julgamento.get("hashes") or {}
    if (juiz_hashes.get("prompt_fidelidade"), juiz_hashes.get("prompt_correcao")) != (
            juiz.HASH_PROMPT_FIDELIDADE, juiz.HASH_PROMPT_CORRECAO):
        problemas.append(f"{v}-{r}: juiz diferente do v1")
    return problemas


def comparar(rodadas: dict[tuple[str, str], tuple[dict, dict]], gabarito: list[dict], fatos: dict,
             fmt: dict, indice_meta_m8: dict | None = None) -> dict:
    """Aplica a regra pre-registrada. `rodadas[(versao, rodada)] = (respostas, julgamento)`."""
    from orchestrator.graph import rag_specialist

    faltando = [f"{v}-{r}" for v, r in ORDEM if (v, r) not in rodadas]
    if faltando:
        raise ValueError(f"rodadas faltando: {', '.join(faltando)}")
    regras_hash = {v: av.sha256_texto(rag_specialist.regras_do_manual(v)) for v in VERSOES}
    problemas = [f"regras {v} mudaram depois do pre-registro" for v in VERSOES
                 if regras_hash[v] != HASH_REGRAS_PRE_REGISTRO[v]]
    indices = set()
    for (v, r), (resp, julg) in rodadas.items():
        problemas += _checar_integridade(v, r, resp, julg, regras_hash)
        # indice_meta INTEIRO (modelo, n_chunks, stemming, contextos...), nao so o hash dos contextos.
        indices.add(json.dumps((resp.get("config") or {}).get("indice_meta"), sort_keys=True))
    if len(indices) != 1 or (indice_meta_m8 is not None and indices != {json.dumps(indice_meta_m8, sort_keys=True)}):
        problemas.append("indice diferente entre as rodadas ou em relacao a Missao 8 (indice_meta)")

    esperado = esperado_sim_nao(gabarito, fmt["sim_nao"])
    por_rodada = {}
    for (v, r), (resp, julg) in rodadas.items():
        m = av.calcular_metricas(resp, gabarito, fatos, julg, fmt)
        viol, fixas = violacoes_sim_nao(resp, esperado)
        por_rodada[f"{v}-{r}"] = {
            **{k: m[k]["acertos"] for k in (METRICA_FORMATO, *METRICAS_SEM_QUEDA)},
            "n": {k: m[k]["n"] for k in (METRICA_FORMATO, *METRICAS_SEM_QUEDA)},
            "pendentes": {k: m[k].get("pendentes", 0) for k in (METRICA_FORMATO, *METRICAS_SEM_QUEDA)},
            "completo": m["completo"],
            "falhas_de_infra": m["falhas_de_infra"],
            "violacoes_sim_nao": viol,
            "fixas_fora_do_c": fixas,
            "custo_usd": resp.get("custo_usd", 0.0) + julg.get("custo_usd", 0.0),
        }

    def media(v, k):
        return sum(por_rodada[f"{v}-{r}"][k] for r in RODADAS) / len(RODADAS)

    medias = {v: {k: media(v, k) for k in (METRICA_FORMATO, *METRICAS_SEM_QUEDA)} for v in VERSOES}
    a = medias["v2"][METRICA_FORMATO] > medias["v1"][METRICA_FORMATO]
    b = {k: medias["v1"][k] - medias["v2"][k] <= QUEDA_MAXIMA for k in METRICAS_SEM_QUEDA}
    viol_v2 = [{**x, "rodada": r} for r in RODADAS for x in por_rodada[f"v2-{r}"]["violacoes_sim_nao"]]
    c = not viol_v2
    return {
        "valido": not problemas,
        "problemas": problemas,
        "por_rodada": por_rodada,
        "medias": medias,
        "criterios": {"a_formato_v2_maior": a, "b_sem_queda": b, "c_sem_sim_nao_errado": c},
        "violacoes_v2": viol_v2,
        "v2_vira_padrao": (not problemas) and a and all(b.values()) and c,
        "custo_total_usd": sum(x["custo_usd"] for x in por_rodada.values()),
    }


def relatorio(c: dict) -> str:
    k = (METRICA_FORMATO, *METRICAS_SEM_QUEDA)
    nomes = {"g_total": "(g) formato total", "b_fatos": "(b) fatos-chave", "f_correcao": "(f) correção",
             "d_sem_grave": "(d) sem grave"}
    linhas = ["| Métrica | " + " | ".join(f"{v}-{r}" for v, r in ORDEM) + " | média v1 | média v2 |",
              "|---" * (len(ORDEM) + 3) + "|"]
    for m in k:
        n = c["por_rodada"]["v1-r1"]["n"][m]
        linhas.append(f"| {nomes[m]} (n={n}) | "
                      + " | ".join(str(c["por_rodada"][f"{v}-{r}"][m]) for v, r in ORDEM)
                      + f" | {c['medias']['v1'][m]:.1f} | {c['medias']['v2'][m]:.1f} |")
    cr = c["criterios"]
    linhas += [
        "",
        f"- a) formato v2 > v1: {'sim' if cr['a_formato_v2_maior'] else 'NÃO'}",
        "- b) sem queda > 1: " + ", ".join(f"{nomes[m]} {'ok' if ok else 'CAIU'}" for m, ok in cr["b_sem_queda"].items()),
        f"- c) nenhum Sim/Não errado na v2: {'sim' if cr['c_sem_sim_nao_errado'] else 'NÃO'}"
        + (" (" + ", ".join("{id} {rodada}: veio {veio}, esperado {esperado}".format(**x) for x in c["violacoes_v2"])
           + ")" if c["violacoes_v2"] else ""),
    ]
    for nome, x in c["por_rodada"].items():
        notas = []
        if not x["completo"]:
            notas.append("INCOMPLETA")
        if x["falhas_de_infra"]:
            notas.append(f"infra: {', '.join(x['falhas_de_infra'])}")
        if any(x["pendentes"].values()):
            notas.append(f"juiz pendente: {x['pendentes']}")
        if x["fixas_fora_do_c"]:
            notas.append(f"resposta fixa fora do c): {', '.join(x['fixas_fora_do_c'])}")
        if notas:
            linhas.append(f"- {nome}: " + "; ".join(notas))
    if c["problemas"]:
        linhas.append("\n**Comparação INVÁLIDA** (integridade): " + "; ".join(c["problemas"]))
    linhas.append(f"\n**Decisão pela regra pré-registrada: v2 {'VIRA' if c['v2_vira_padrao'] else 'NÃO vira'} "
                  f"padrão.** Custo total medido: US$ {c['custo_total_usd']:.4f}.")
    return "\n".join(linhas)


def mostrar_plano(settings, gabarito: list[dict]) -> int:
    from orchestrator.graph import rag_specialist

    meta_m8 = indice_meta_m8()
    meta = av._meta_do_indice(settings) or {}
    print("Missao 9 - formato do Max: REGRAS_DO_MANUAL v2 x v1 (NADA executado)")
    print(f"indice   : {settings.rag_index_path}; contextos_sha256 {meta.get('contextos_sha256')}; indice_meta "
          f"{'IGUAL' if meta and meta == meta_m8 else 'DIFERENTE'} ao da Missao 8")
    print(f"busca    : modo {settings.rag_search_mode}, top_k {settings.rag_top_k}, rerank "
          f"{settings.rag_rerank_model or 'nao'}; synth {settings.general_model} (sem temperatura fixa)")
    for v in VERSOES:
        h = av.sha256_texto(rag_specialist.regras_do_manual(v))
        print(f"regras {v}: sha256 {h} ({'= pre-registro' if h == HASH_REGRAS_PRE_REGISTRO[v] else 'DIFERENTE do pre-registro'})")
    print(f"juiz     : v1 ({juiz.JUIZ_MODELO}), --sem-calibracao; formato_v1 sha256 {av.HASH_FORMATO}")
    teto = 0.0
    for v in VERSOES:
        est = av.estimar_custo(gabarito, settings.rag_top_k, settings.router_model, settings.general_model, regras=v)
        t = est["teto_usd"]
        print(f"teto {v}  : respostas US$ {t['respostas']:.3f} + juiz US$ {t['juiz_fidelidade'] + t['juiz_correcao']:.3f} "
              f"por rodada; x{len(RODADAS)} = US$ {len(RODADAS) * t['total']:.3f}")
        teto += len(RODADAS) * t["total"]
    proj = len(ORDEM) * (CUSTO_M8_USD["respostas"] + CUSTO_M8_USD["juiz"])
    print(f"custo    : TETO estimado US$ {teto:.3f}; projecao pelo custo real da Missao 8 US$ {proj:.3f} "
          f"(4 x ({CUSTO_M8_USD['respostas']} + {CUSTO_M8_USD['juiz']}))")
    orc = len(ORDEM) * (ORCAMENTO_RESPOSTAS_USD + ORCAMENTO_JUIZ_USD)
    print(f"orcamento: por invocacao US$ {ORCAMENTO_RESPOSTAS_USD} (respostas) / US$ {ORCAMENTO_JUIZ_USD} (juiz); "
          f"soma US$ {orc:.2f} <= teto total US$ {TETO_TOTAL_USD:.2f}")
    print("comandos (de dentro de orchestrator/, NESTA ordem):")
    for i, cmd in enumerate(comandos(), 1):
        print(f"  {i}. {cmd}")
    print("depois    : .venv/bin/python -m orchestrator.rag.missao9 --comparar")
    return 0


def indice_meta_m8() -> dict | None:
    m8 = json.loads(RESPOSTAS_M8.read_text(encoding="utf-8")) if RESPOSTAS_M8.is_file() else {}
    return (m8.get("config") or {}).get("indice_meta")


def carregar_rodadas() -> dict[tuple[str, str], tuple[dict, dict]]:
    rodadas = {}
    for v, r in ORDEM:
        resp, julg = caminhos(v, r)
        if resp.is_file() and julg.is_file():
            rodadas[(v, r)] = (json.loads(resp.read_text(encoding="utf-8")), json.loads(julg.read_text(encoding="utf-8")))
    return rodadas


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--comparar", action="store_true", help="aplica a regra pre-registrada aos JSONs de m9/ (gratis)")
    args = p.parse_args(argv)
    from orchestrator.config import settings

    gabarito = av.carregar_gabarito()
    if not args.comparar:
        return mostrar_plano(settings, gabarito)
    try:
        c = comparar(carregar_rodadas(), gabarito, av.carregar_fatos(), av.carregar_formato(), indice_meta_m8())
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    print(relatorio(c))
    return 0 if c["valido"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
