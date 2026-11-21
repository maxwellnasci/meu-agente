"""Missao 10: v3 "pensa primeiro, formata depois" x v1.

UMA variavel: a etapa 2 do synthesize_final. A etapa 1 e a chamada de hoje com
as REGRAS_DO_MANUAL v1 (mesmo hash); na v3 a saida dela e INTERNA e uma 2a
chamada (PROMPT_FORMATADOR_V3, mesmo modelo e mesma configuracao do synth) a
reescreve no formato do Max vendo SO a pergunta e essa resposta, nunca os
trechos. Busca, top_k, indice, juiz (v1, --sem-calibracao), fatos-chave e
formato_v1.yaml ficam iguais aos da Missao 9. Criterios pre-registrados em
docs/RAG.md (secao Missao 10), ANTES de rodar; nenhum outro entra depois.

    cd orchestrator
    .venv/bin/python -m orchestrator.rag.missao10              # plano + custo + comandos (gratis)
    #   ... os 8 comandos pagos impressos pelo plano, NA ORDEM (intercalada) ...
    .venv/bin/python -m orchestrator.rag.missao10 --comparar   # gratis: aplica a regra de decisao

Diferencas de execucao em relacao a Missao 9 (pre-registradas):
- a versao vem SO de --regras (v1 | v3); o avaliar_respostas da Missao 9
  continua aceitando so v1/v2;
- o juiz julga a resposta FINAL (o que o usuario recebe; na v3, etapa 2 +
  garantir_citacao) nas DUAS versoes, contra os mesmos trechos da etapa 1;
  (b), (c) e (g) continuam na resposta crua (na v3, a crua da etapa 2).
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from orchestrator.rag import avaliar_respostas as av
from orchestrator.rag import juiz
from orchestrator.rag import missao9 as m9

DIR_M10 = av.DIR_SAIDA.parent / "m10"
VERSOES = ("v1", "v3")
RODADAS = ("r1", "r2")
ORDEM = (("v1", "r1"), ("v3", "r1"), ("v1", "r2"), ("v3", "r2"))
ALVO_DO_JUIZ = "resposta_final"

# Hashes PRE-REGISTRADOS (docs/RAG.md, Missao 10). A v3 injeta as regras v1 na
# etapa 1, entao o hash das regras e o mesmo nas duas versoes (= Missao 8).
HASH_REGRAS_V1 = "3f4ca553845cc40ed10451f70df9357f2afad2ac2f76d265198be0e6be498240"
HASH_REGRAS_PRE_REGISTRO = {"v1": HASH_REGRAS_V1, "v3": HASH_REGRAS_V1}
HASH_FORMATADOR_PRE_REGISTRO = "490fe4ea022237017d080648e10e39ad7c341ade52afa8bc0c3c22e6cb9dbad8"
HASH_MENSAGEM_FORMATADOR_PRE_REGISTRO = "55b927d3b682ca9f39eb15c08aa4d2dcb2cbec1294f6c109b9dac18ea0184534"

# Teto TOTAL da missao: US$ 1,00 = 2 x 0,08 (v1) + 2 x 0,12 (v3) + 4 x 0,15 (juiz).
TETO_TOTAL_USD = 1.00
ORCAMENTO_RESPOSTAS_USD = {"v1": 0.08, "v3": 0.12}
ORCAMENTO_JUIZ_USD = 0.15

# Regra de decisao (pre-registro).
METRICA_FORMATO = "g_total"                                       # a) v3 > v1 (estrito)
METRICAS_SEM_QUEDA = ("b_fatos", "f_correcao", "d_sem_grave", "d_fiel_estrito", "c_citacao_espontanea")  # b)
QUEDA_MAXIMA = 1.0
FATOR_CUSTO_MAXIMO = 2.0   # d) custo medio por rodada das respostas v3 <= 2,0 x o da v1
LIMITE_P95_ETAPA2_S = 4.0  # e) p95 (nearest-rank) de tempo_etapa2_s <= 4,0 s
_EPS_CUSTO = 1e-12         # so ruido de ponto flutuante (0,1 x 2 != 0,2 em binario)

NOMES = {"g_total": "(g) formato total", "b_fatos": "(b) fatos-chave", "f_correcao": "(f) correção",
         "d_sem_grave": "(d) sem grave", "d_fiel_estrito": "(d) fiel estrito",
         "c_citacao_espontanea": "(c) citação espontânea"}


def caminhos(versao: str, rodada: str) -> tuple[Path, Path]:
    return DIR_M10 / f"respostas-{versao}-{rodada}.json", DIR_M10 / f"julgamento-{versao}-{rodada}.json"


def comandos() -> list[str]:
    base = ".venv/bin/python -m orchestrator.rag.missao10 --executar"
    saida = []
    for v, r in ORDEM:
        resp, julg = (p.relative_to(av.ORCHESTRATOR_DIR) for p in caminhos(v, r))
        saida.append(f"{base} --etapa respostas --regras {v} --orcamento {ORCAMENTO_RESPOSTAS_USD[v]} --saida {resp}")
        saida.append(f"{base} --etapa julgar --orcamento {ORCAMENTO_JUIZ_USD} --respostas {resp} --saida {julg}")
    return saida


def diff_formato_v2_v3() -> list[dict]:
    """Comparacao POR CODIGO (difflib, palavra a palavra) entre a regra 6 da v2 e
    o FORMATO da v3, item a item (cabecalho, a, b, c, d). So o que difere."""
    import difflib

    from orchestrator.graph import rag_specialist

    v2 = rag_specialist._REGRA_FORMATO_V2.strip("\n").split("\n")
    v3 = rag_specialist.PROMPT_FORMATADOR_V3.split("\nFORMATO da resposta", 1)[1]
    v3 = ("FORMATO da resposta" + v3).split("\n")
    if len(v2) != len(v3):
        raise ValueError(f"numero de itens difere: v2 {len(v2)}, v3 {len(v3)}")
    saida = []
    for nome, l2, l3 in zip(("cabecalho", "a", "b", "c", "d"), v2, v3):
        w2, w3 = l2.split(), l3.split()
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, w2, w3, autojunk=False).get_opcodes():
            if op != "equal":
                saida.append({"item": nome, "op": op, "v2": " ".join(w2[i1:i2]), "v3": " ".join(w3[j1:j2])})
    return saida


def percentil(valores, q: float) -> float:
    """Nearest-rank, sem interpolacao (o mesmo da Missao 7, evaluate.percentil)."""
    from orchestrator.rag.evaluate import percentil as p

    return p(valores, q)


def diagnostico_sim_nao(respostas: dict) -> list[dict]:
    """So diagnostico (nao decide): resposta cuja etapa 1 comeca por Sim/Nao ->
    a etapa 2 manteve, inverteu ou tirou a conclusao da 1a palavra?"""
    saida = []
    for r in respostas.get("perguntas", []):
        e1 = m9.primeira_palavra(r.get("resposta_etapa1"))
        if not r.get("etapa2_aplicada") or e1 is None:
            continue
        e2 = m9.primeira_palavra(r.get("resposta_crua"))
        status = "etapa 2 falhou" if r.get("etapa2_falhou") else (
            "manteve" if e2 == e1 else ("inverteu" if e2 is not None else "sem Sim/Não"))
        saida.append({"id": r["id"], "etapa1": e1, "etapa2": e2, "status": status})
    return saida


def _checar_integridade_m10(v: str, r: str, resp: dict, julg: dict, regras_hash: dict[str, str]) -> list[str]:
    problemas = m9._checar_integridade(v, r, resp, julg, regras_hash)
    h = resp.get("hashes") or {}
    if v == "v3" and (h.get("prompt_formatador_v3"), h.get("mensagem_formatador_v3")) != (
            HASH_FORMATADOR_PRE_REGISTRO, HASH_MENSAGEM_FORMATADOR_PRE_REGISTRO):
        problemas.append(f"{v}-{r}: hash do formatador difere do pre-registro")
    aplicada = [x["id"] for x in resp.get("perguntas", []) if x.get("etapa2_aplicada")]
    if v == "v1" and aplicada:
        problemas.append(f"{v}-{r}: etapa 2 aplicada na v1 ({', '.join(aplicada)})")
    if julg.get("alvo") != ALVO_DO_JUIZ:
        problemas.append(f"{v}-{r}: juiz julgou {julg.get('alvo') or 'resposta_crua'!r}, nao {ALVO_DO_JUIZ!r}")
    return problemas


def comparar(rodadas: dict[tuple[str, str], tuple[dict, dict]], gabarito: list[dict], fatos: dict,
             fmt: dict, indice_meta_m8: dict | None = None) -> dict:
    """Aplica a regra pre-registrada. `rodadas[(versao, rodada)] = (respostas, julgamento)`."""
    from orchestrator.graph import rag_specialist

    faltando = [f"{v}-{r}" for v, r in ORDEM if (v, r) not in rodadas]
    if faltando:
        raise ValueError(f"rodadas faltando: {', '.join(faltando)}")
    regras_hash = {v: av.sha256_texto(rag_specialist.regras_da_etapa1(v)) for v in VERSOES}
    problemas = [f"regras da etapa 1 da {v} mudaram depois do pre-registro" for v in VERSOES
                 if regras_hash[v] != HASH_REGRAS_PRE_REGISTRO[v]]
    if (av.sha256_texto(rag_specialist.PROMPT_FORMATADOR_V3), av.sha256_texto(rag_specialist.MENSAGEM_FORMATADOR_V3)) != (
            HASH_FORMATADOR_PRE_REGISTRO, HASH_MENSAGEM_FORMATADOR_PRE_REGISTRO):
        problemas.append("texto do formatador v3 mudou depois do pre-registro")
    indices = set()
    for (v, r), (resp, julg) in rodadas.items():
        problemas += _checar_integridade_m10(v, r, resp, julg, regras_hash)
        indices.add(json.dumps((resp.get("config") or {}).get("indice_meta"), sort_keys=True))
    if len(indices) != 1 or (indice_meta_m8 is not None and indices != {json.dumps(indice_meta_m8, sort_keys=True)}):
        problemas.append("indice diferente entre as rodadas ou em relacao a Missao 8 (indice_meta)")

    chaves = (METRICA_FORMATO, *METRICAS_SEM_QUEDA)
    esperado = m9.esperado_sim_nao(gabarito, fmt["sim_nao"])
    por_rodada = {}
    for (v, r), (resp, julg) in rodadas.items():
        m = av.calcular_metricas(resp, gabarito, fatos, julg, fmt)
        viol, fixas = m9.violacoes_sim_nao(resp, esperado)
        perguntas = resp.get("perguntas", [])
        por_rodada[f"{v}-{r}"] = {
            **{k: m[k]["acertos"] for k in chaves},
            "n": {k: m[k]["n"] for k in chaves},
            "pendentes": {k: m[k].get("pendentes", 0) for k in chaves},
            "completo": m["completo"],
            "falhas_de_infra": m["falhas_de_infra"],
            "violacoes_sim_nao": viol,
            "fixas_fora_do_c": fixas,
            "custo_respostas_usd": resp.get("custo_usd", 0.0),
            "custo_etapa2_usd": resp.get("custo_etapa2_usd", 0.0),
            "custo_juiz_usd": julg.get("custo_usd", 0.0),
            "tempos_etapa2_s": [x["tempo_etapa2_s"] for x in perguntas
                                if x.get("etapa2_aplicada") and x.get("tempo_etapa2_s") is not None],
            "tempos_synth_s": [x["tempo_synth_s"] for x in perguntas if x.get("tempo_synth_s") is not None],
            "tempos_etapa1_s": [x["tempo_etapa1_s"] for x in perguntas if x.get("tempo_etapa1_s") is not None],
            "etapa2_falhou": [x["id"] for x in perguntas if x.get("etapa2_falhou")],
            "diagnostico_sim_nao": diagnostico_sim_nao(resp) if v == "v3" else [],
        }

    def media(v, k):
        return sum(por_rodada[f"{v}-{r}"][k] for r in RODADAS) / len(RODADAS)

    medias = {v: {k: media(v, k) for k in (*chaves, "custo_respostas_usd", "custo_etapa2_usd")} for v in VERSOES}
    a = medias["v3"][METRICA_FORMATO] > medias["v1"][METRICA_FORMATO]
    b = {k: medias["v1"][k] - medias["v3"][k] <= QUEDA_MAXIMA for k in METRICAS_SEM_QUEDA}
    viol_v3 = [{**x, "rodada": r} for r in RODADAS for x in por_rodada[f"v3-{r}"]["violacoes_sim_nao"]]
    c = not viol_v3
    razao_custo = (medias["v3"]["custo_respostas_usd"] / medias["v1"]["custo_respostas_usd"]
                   if medias["v1"]["custo_respostas_usd"] else None)
    d = medias["v3"]["custo_respostas_usd"] <= FATOR_CUSTO_MAXIMO * medias["v1"]["custo_respostas_usd"] + _EPS_CUSTO
    tempos = [t for r in RODADAS for t in por_rodada[f"v3-{r}"]["tempos_etapa2_s"]]
    p95 = percentil(tempos, 0.95) if tempos else None

    def p50_p95(v, chave):  # so informativo (nao decide): 2 rodadas juntas, nearest-rank
        ts = [t for r in RODADAS for t in por_rodada[f"{v}-{r}"][chave]]
        return {"n": len(ts), "p50": percentil(ts, 0.50), "p95": percentil(ts, 0.95)} if ts else None

    latencia = {"v1_synth": p50_p95("v1", "tempos_synth_s"), "v3_etapa1": p50_p95("v3", "tempos_etapa1_s"),
                "v3_etapa2": p50_p95("v3", "tempos_etapa2_s"), "v3_synth": p50_p95("v3", "tempos_synth_s")}
    e = p95 is not None and p95 <= LIMITE_P95_ETAPA2_S
    return {
        "valido": not problemas,
        "problemas": problemas,
        "por_rodada": por_rodada,
        "medias": medias,
        "razao_custo_v3_v1": razao_custo,
        "p95_etapa2_s": p95,
        "n_etapa2": len(tempos),
        "latencia_informativa": latencia,
        "criterios": {"a_formato_v3_maior": a, "b_sem_queda": b, "c_sem_sim_nao_errado": c,
                      "d_custo_ate_2x": d, "e_p95_etapa2_ate_4s": e},
        "violacoes_v3": viol_v3,
        "v3_vira_padrao": (not problemas) and a and all(b.values()) and c and d and e,
        "custo_total_usd": sum(x["custo_respostas_usd"] + x["custo_juiz_usd"] for x in por_rodada.values()),
    }


def relatorio(c: dict) -> str:
    chaves = (METRICA_FORMATO, *METRICAS_SEM_QUEDA)
    pr = c["por_rodada"]
    linhas = ["| Métrica | " + " | ".join(f"{v}-{r}" for v, r in ORDEM) + " | média v1 | média v3 |",
              "|---" * (len(ORDEM) + 3) + "|"]
    for m in chaves:
        linhas.append(f"| {NOMES[m]} (n={pr['v1-r1']['n'][m]}) | "
                      + " | ".join(str(pr[f"{v}-{r}"][m]) for v, r in ORDEM)
                      + f" | {c['medias']['v1'][m]:.1f} | {c['medias']['v3'][m]:.1f} |")
    linhas.append("| custo das respostas (US$) | "
                  + " | ".join(f"{pr[f'{v}-{r}']['custo_respostas_usd']:.4f}" for v, r in ORDEM)
                  + f" | {c['medias']['v1']['custo_respostas_usd']:.4f} | {c['medias']['v3']['custo_respostas_usd']:.4f} |")
    linhas.append("| … só a etapa 2 (US$) | "
                  + " | ".join(f"{pr[f'{v}-{r}']['custo_etapa2_usd']:.4f}" for v, r in ORDEM)
                  + f" | — | {c['medias']['v3']['custo_etapa2_usd']:.4f} |")
    cr = c["criterios"]
    razao = "n/d" if c["razao_custo_v3_v1"] is None else f"{c['razao_custo_v3_v1']:.2f}x"
    p95 = "n/d (nenhuma etapa 2 medida)" if c["p95_etapa2_s"] is None else f"{c['p95_etapa2_s']:.2f} s"
    linhas += [
        "",
        f"- a) formato v3 > v1: {'sim' if cr['a_formato_v3_maior'] else 'NÃO'}",
        "- b) sem queda > 1: " + ", ".join(f"{NOMES[m]} {'ok' if ok else 'CAIU'}" for m, ok in cr["b_sem_queda"].items()),
        f"- c) nenhum Sim/Não errado na v3: {'sim' if cr['c_sem_sim_nao_errado'] else 'NÃO'}"
        + (" (" + ", ".join("{id} {rodada}: veio {veio}, esperado {esperado}".format(**x) for x in c["violacoes_v3"])
           + ")" if c["violacoes_v3"] else ""),
        f"- d) custo v3 ≤ {FATOR_CUSTO_MAXIMO:.1f}x v1: {'sim' if cr['d_custo_ate_2x'] else 'NÃO'} ({razao})",
        (f"- e) p95 da etapa 2 ≤ {LIMITE_P95_ETAPA2_S:.1f} s: {'sim' if cr['e_p95_etapa2_ate_4s'] else 'NÃO'} "
         f"({p95}; n={c['n_etapa2']})"),
    ]
    for nome, x in pr.items():
        notas = []
        if not x["completo"]:
            notas.append("INCOMPLETA")
        if x["falhas_de_infra"]:
            notas.append(f"infra: {', '.join(x['falhas_de_infra'])}")
        if any(x["pendentes"].values()):
            notas.append(f"juiz pendente: {x['pendentes']}")
        if x["fixas_fora_do_c"]:
            notas.append(f"resposta fixa fora do c): {', '.join(x['fixas_fora_do_c'])}")
        if x["etapa2_falhou"]:
            notas.append(f"etapa 2 falhou (usuário recebeu a etapa 1; conta normalmente): {', '.join(x['etapa2_falhou'])}")
        if notas:
            linhas.append(f"- {nome}: " + "; ".join(notas))
    lat = c.get("latencia_informativa") or {}
    rot = {"v1_synth": "v1 synth", "v3_etapa1": "v3 etapa 1", "v3_etapa2": "v3 etapa 2", "v3_synth": "v3 synth (1+2)"}
    partes = [f"{rot[k]} p50 {x['p50']:.2f} s / p95 {x['p95']:.2f} s (n={x['n']})" for k, x in lat.items() if x]
    if partes:
        linhas.append("- latência do synth (informativo, não decide): " + "; ".join(partes))
    diag = [(nome, d) for nome, x in pr.items() for d in x["diagnostico_sim_nao"]]
    if diag:
        linhas.append("\nDiagnóstico (não decide): etapa 1 começou por Sim/Não →")
        linhas += [f"- {nome} {d['id']}: etapa 1 {d['etapa1']}, etapa 2 {d['etapa2'] or '—'}: {d['status']}"
                   for nome, d in diag]
    if c["problemas"]:
        linhas.append("\n**Comparação INVÁLIDA** (integridade): " + "; ".join(c["problemas"]))
    linhas.append(f"\n**Decisão pela regra pré-registrada: v3 {'VIRA' if c['v3_vira_padrao'] else 'NÃO vira'} "
                  f"padrão.** Custo total medido: US$ {c['custo_total_usd']:.4f}.")
    return "\n".join(linhas)


def _custo_real_m9() -> dict:
    """Custo REAL medido na Missao 9 (v1): media das 2 rodadas, respostas e juiz,
    e os tokens de saida do synth por pergunta (base da projecao da etapa 2)."""
    resp, julg, saida_synth = [], [], []
    for r in m9.RODADAS:
        pr, pj = m9.caminhos("v1", r)
        if not (pr.is_file() and pj.is_file()):
            return {}
        dr, dj = json.loads(pr.read_text(encoding="utf-8")), json.loads(pj.read_text(encoding="utf-8"))
        resp.append(dr["custo_usd"])
        julg.append(dj["custo_usd"])
        for p in dr["perguntas"]:
            for ch in p.get("chamadas_llm", []):
                if ch.get("no") == "synthesize_final":
                    uso, meta = ch.get("token_usage") or {}, ch.get("usage_metadata") or {}
                    saida_synth.append(uso.get("completion_tokens") or meta.get("output_tokens") or 0)
    return {"respostas": sum(resp) / len(resp), "juiz": sum(julg) / len(julg),
            "n_synth": len(saida_synth) / len(resp), "saida_synth_media": sum(saida_synth) / max(1, len(saida_synth))}


def projecao(settings, gabarito: list[dict]) -> dict:
    """Projecao pelo custo real da Missao 9 (v1). Etapa 2 por pergunta com rag:
    entrada = prompt + mensagem + pergunta + a saida media do synth; saida =
    a mesma saida media (conservador: o formato pede MENOS texto)."""
    from orchestrator.graph import rag_specialist

    real = _custo_real_m9()
    if not real:
        return {}
    maior = max(len(p["pergunta"]) for p in gabarito)
    ent = (len(rag_specialist.PROMPT_FORMATADOR_V3) + len(rag_specialist.MENSAGEM_FORMATADOR_V3) + maior) \
        / av.CHARS_POR_TOKEN + real["saida_synth_media"]
    pe, ps = av.PRECOS.get(settings.general_model, av.PRECO_DESCONHECIDO)
    etapa2 = real["n_synth"] * (ent * pe + real["saida_synth_media"] * ps) / 1_000_000
    return {"v1": {"respostas": real["respostas"], "juiz": real["juiz"]},
            "v3": {"respostas": real["respostas"] + etapa2, "juiz": real["juiz"], "etapa2": etapa2}}


def mostrar_plano(settings, gabarito: list[dict]) -> int:
    from orchestrator.graph import rag_specialist

    meta_m8 = m9.indice_meta_m8()
    meta = av._meta_do_indice(settings) or {}
    print("Missao 10 - v3 'pensa primeiro, formata depois' x v1 (NADA executado)")
    print(f"indice   : {settings.rag_index_path}; contextos_sha256 {meta.get('contextos_sha256')}; indice_meta "
          f"{'IGUAL' if meta and meta == meta_m8 else 'DIFERENTE'} ao da Missao 8")
    print(f"busca    : modo {settings.rag_search_mode}, top_k {settings.rag_top_k}, rerank "
          f"{settings.rag_rerank_model or 'nao'}; synth e etapa 2: {settings.general_model} (sem temperatura fixa)")
    for v in VERSOES:
        h = av.sha256_texto(rag_specialist.regras_da_etapa1(v))
        print(f"regras {v}: etapa 1 sha256 {h} ({'= pre-registro' if h == HASH_REGRAS_PRE_REGISTRO[v] else 'DIFERENTE do pre-registro'})")
    for nome, texto, pre in (("formatador", rag_specialist.PROMPT_FORMATADOR_V3, HASH_FORMATADOR_PRE_REGISTRO),
                             ("mensagem  ", rag_specialist.MENSAGEM_FORMATADOR_V3, HASH_MENSAGEM_FORMATADOR_PRE_REGISTRO)):
        h = av.sha256_texto(texto)
        print(f"{nome}: sha256 {h} ({'= pre-registro' if h == pre else 'DIFERENTE do pre-registro'})")
    print(f"juiz     : v1 ({juiz.JUIZ_MODELO}), --sem-calibracao, julga a {ALVO_DO_JUIZ} nas duas versoes; "
          f"formato_v1 sha256 {av.HASH_FORMATO}")
    teto = 0.0
    for v in VERSOES:
        est = av.estimar_custo(gabarito, settings.rag_top_k, settings.router_model, settings.general_model, regras=v)
        t = est["teto_usd"]
        extra = f" (etapa 2 US$ {t['respostas_etapa2']:.3f})" if "respostas_etapa2" in t else ""
        print(f"teto {v}  : respostas US$ {t['respostas']:.3f}{extra} + juiz US$ "
              f"{t['juiz_fidelidade'] + t['juiz_correcao']:.3f} por rodada; x{len(RODADAS)} = US$ {len(RODADAS) * t['total']:.3f}")
        teto += len(RODADAS) * t["total"]
    proj = projecao(settings, gabarito)
    if proj:
        total = sum(len(RODADAS) * (p["respostas"] + p["juiz"]) for p in proj.values())
        print(f"projecao : pelo custo REAL da Missao 9 (v1), por rodada: v1 respostas US$ {proj['v1']['respostas']:.4f}; "
              f"v3 respostas US$ {proj['v3']['respostas']:.4f} (etapa 2 ~US$ {proj['v3']['etapa2']:.4f}, "
              f"{proj['v3']['respostas'] / proj['v1']['respostas']:.2f}x a v1); juiz US$ {proj['v1']['juiz']:.4f}")
        print(f"           total projetado: 2 x ({proj['v1']['respostas']:.4f} + {proj['v1']['juiz']:.4f}) + "
              f"2 x ({proj['v3']['respostas']:.4f} + {proj['v3']['juiz']:.4f}) = US$ {total:.3f}")
    print(f"custo    : TETO estimado pelo script US$ {teto:.3f} (assume o raciocinio maximo do juiz; nao e o limite)")
    orc = sum(ORCAMENTO_RESPOSTAS_USD[v] + ORCAMENTO_JUIZ_USD for v, _ in ORDEM)
    print("orcamento: por invocacao: respostas " + ", ".join(f"{v} US$ {o:.2f}" for v, o in ORCAMENTO_RESPOSTAS_USD.items())
          + f"; juiz US$ {ORCAMENTO_JUIZ_USD:.2f}")
    print(f"           2 x {ORCAMENTO_RESPOSTAS_USD['v1']:.2f} + 2 x {ORCAMENTO_RESPOSTAS_USD['v3']:.2f} + "
          f"4 x {ORCAMENTO_JUIZ_USD:.2f} = US$ {orc:.2f} <= teto total US$ {TETO_TOTAL_USD:.2f} "
          "(sem folga: o corte e DEPOIS da pergunta que estoura)")
    print("comandos (de dentro de orchestrator/, NESTA ordem):")
    for i, cmd in enumerate(comandos(), 1):
        print(f"  {i}. {cmd}")
    print("depois    : .venv/bin/python -m orchestrator.rag.missao10 --comparar")
    if av._aviso_tracing():
        print("AVISO    : tracing do LangSmith ligado - perguntas, trechos e respostas vao para o LangSmith")
    if not settings.openrouter_api_key:
        print("AVISO    : ORCHESTRATOR_OPENROUTER_API_KEY ausente (rode de dentro de orchestrator/, com o .env)")
    return 0


def carregar_rodadas() -> dict[tuple[str, str], tuple[dict, dict]]:
    rodadas = {}
    for v, r in ORDEM:
        resp, julg = caminhos(v, r)
        if resp.is_file() and julg.is_file():
            rodadas[(v, r)] = (json.loads(resp.read_text(encoding="utf-8")), json.loads(julg.read_text(encoding="utf-8")))
    return rodadas


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--comparar", action="store_true", help="aplica a regra pre-registrada aos JSONs de m10/ (gratis)")
    p.add_argument("--diff-formato", action="store_true", help="difflib: regra 6 da v2 x FORMATO da v3 (gratis)")
    p.add_argument("--executar", action="store_true", help="roda a --etapa paga (LLM real no OpenRouter)")
    p.add_argument("--etapa", choices=("respostas", "julgar"))
    p.add_argument("--regras", choices=VERSOES, help="versao da resposta (obrigatoria com --etapa respostas)")
    p.add_argument("--orcamento", type=float, help="US$ maximo da invocacao (<= o pre-registrado)")
    p.add_argument("--respostas", type=Path, help="JSON de respostas a julgar")
    p.add_argument("--saida", type=Path, help="arquivo de saida (fixtures/rag/m10/...)")
    a = p.parse_args(argv)
    if sum((a.comparar, a.executar, a.diff_formato)) > 1:
        p.error("--comparar, --executar e --diff-formato sao exclusivos")
    if not a.executar:
        if any(x is not None for x in (a.etapa, a.regras, a.orcamento, a.respostas, a.saida)):
            p.error("--etapa/--regras/--orcamento/--respostas/--saida so valem com --executar")
        return a
    if not a.etapa or a.saida is None or a.orcamento is None:
        p.error("--executar exige --etapa, --orcamento e --saida")
    if a.etapa == "respostas":
        if not a.regras or a.respostas is not None:
            p.error("--etapa respostas exige --regras v1|v3 (e nao aceita --respostas)")
        teto = ORCAMENTO_RESPOSTAS_USD[a.regras]
    else:
        if a.regras or a.respostas is None:
            p.error("--etapa julgar exige --respostas (e nao aceita --regras: a versao esta no JSON)")
        teto = ORCAMENTO_JUIZ_USD
    if not 0 < a.orcamento <= teto:
        p.error(f"--orcamento {a.orcamento} fora do pre-registrado (0 < orcamento <= {teto})")
    return a


def _executar(args, settings, gabarito: list[dict]) -> int:
    if not settings.openrouter_api_key:
        print("erro: ORCHESTRATOR_OPENROUTER_API_KEY ausente (rode de dentro de orchestrator/, com o .env)", file=sys.stderr)
        return 2
    if args.saida.exists():
        print(f"erro: {args.saida} ja existe: nao sobrescrevo resultado medido", file=sys.stderr)
        return 2
    if av._aviso_tracing():
        print("AVISO: tracing do LangSmith ligado - perguntas, trechos e respostas vao para o LangSmith")
    try:
        if args.etapa == "respostas":
            if not Path(settings.rag_index_path).is_file():
                print(f"erro: indice ausente em {settings.rag_index_path} (rode python -m orchestrator.rag.ingest)",
                      file=sys.stderr)
                return 2
            dados = asyncio.run(av.etapa_respostas(gabarito, orcamento=args.orcamento, regras=args.regras,
                                                   aceitas=VERSOES))
        else:
            respostas = json.loads(args.respostas.read_text(encoding="utf-8"))
            calibracao = av.status_sem_calibracao(av.CALIBRACAO)
            print(f"AVISO: juiz SEM calibracao humana completa (como nas Missoes 8 e 9): itens marcados "
                  f"{calibracao['itens_marcados'] or 'nenhum'}; o JSON grava status nao_calibrada")
            dados = asyncio.run(av.etapa_julgar(respostas, gabarito, settings.openrouter_api_key,
                                                orcamento=args.orcamento, calibracao=calibracao, alvo=ALVO_DO_JUIZ))
    except av.FalhaInicial as exc:
        print(f"erro: {exc} - nada gravado", file=sys.stderr)
        return 2
    dados["missao"] = 10
    av._gravar(args.saida, dados)
    print(f"\nUS$ {dados['custo_usd']:.4f} -> {args.saida}")
    return 1 if dados["abortado_por_orcamento"] else 0


def main(argv=None) -> int:
    args = parse_args(argv)
    from orchestrator.config import settings

    if args.diff_formato:
        for d in diff_formato_v2_v3():
            print(f"[{d['item']}] {d['op']:<7} v2: {d['v2'] or '—'}\n{'':<19}v3: {d['v3'] or '—'}")
        return 0
    gabarito = av.carregar_gabarito()
    if args.executar:
        return _executar(args, settings, gabarito)
    if not args.comparar:
        return mostrar_plano(settings, gabarito)
    try:
        c = comparar(carregar_rodadas(), gabarito, av.carregar_fatos(), av.carregar_formato(), m9.indice_meta_m8())
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    print(relatorio(c))
    return 0 if c["valido"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
