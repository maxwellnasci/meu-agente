"""Ferramenta de limites - Parte 2: medicao do extrator de ficha.

Pre-registro em docs/RAG.md, "Ferramenta de limites — Parte 2", escrito ANTES
de medir. Duas rodadas das 100 perguntas de fixtures/rag/limites/extracao_v1.yaml.

    cd orchestrator
    .venv/bin/python -m orchestrator.rag.medir_extracao                                  # plano + custo (gratis)
    .venv/bin/python -m orchestrator.rag.medir_extracao --executar --rodada r1 --orcamento 0.06   # pago
    .venv/bin/python -m orchestrator.rag.medir_extracao --executar --rodada r2 --orcamento 0.06   # pago
    .venv/bin/python -m orchestrator.rag.medir_extracao --resultado                      # gratis: criterios a-e

Regras de execucao (pre-registradas; emendas de 22/11/2026 antes de qualquer medicao):
- teto TOTAL de US$ 0,15 somando TODAS as tentativas (validas ou nao) e ate US$ 0,06
  por tentativa. Tentativa interrompida sem custo gravado conta como o orcamento
  inteiro dela. O CLI recusa --orcamento <= 0, > 0,06 ou acima do que resta do total;
- falha de infra (excecao da chamada, depois dos retries do cliente) depois da 1a
  pergunta: a tentativa fica INVALIDA e a rodada pode ser repetida UMA vez;
- falha logo na 1a chamada de uma tentativa (excecao, OU resposta sem a chamada de
  preencher_ficha): para na hora, nada e medido, a tentativa e registrada como
  "falha_inicial" (com o custo dela) e NAO gasta a repeticao por infra (no maximo 2
  por rodada: repete uma vez);
- passou do orcamento: a tentativa para e fica INVALIDA, sem repeticao;
- DEPOIS da 1a chamada, resposta sem chamada da ferramenta ou com argumentos ruins
  NAO e infra: e ficha invalida, e conta como erro da pergunta.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import yaml

from orchestrator.rag import limites
from orchestrator.rag import limites_extracao as lx

ORCHESTRATOR_DIR = limites.ORCHESTRATOR_DIR
CONJUNTO = ORCHESTRATOR_DIR / "fixtures" / "rag" / "limites" / "extracao_v1.yaml"
DIR_MEDICAO = ORCHESTRATOR_DIR / "fixtures" / "rag" / "limites" / "medicao"
DIR_M10 = ORCHESTRATOR_DIR / "fixtures" / "rag" / "m10"
NOME_REGISTRO = "registro.json"

RODADAS = ("r1", "r2")
N_PERGUNTAS = 100
DISTRIBUICAO = {"temperatura": 60, "ambigua": 15, "fora": 15, "injecao": 10}
ACERTO_MINIMO = 95
TETO_TOTAL_USD = 0.15  # emenda 22/11 (era 0,10)
TETO_RODADA_USD = 0.06  # emenda 22/11: por tentativa
MAX_INVALIDAS_POR_RODADA = 1  # 1 tentativa + UMA repeticao depois de infra
MAX_FALHAS_INICIAIS = 2

# Congelado no pre-registro (docs/RAG.md, Parte 2). Mudou -> o --executar recusa.
MODELO = "deepseek/deepseek-chat"
HASH_PROMPT = "f90f6dedb2be59e68eeef8fbbb93b4895b7fff73d26b4130ed6e7c8fa546ceeb"
HASH_SCHEMA = "054978a13195b554ed8438e703b2930ccc770d121e657ba947c7d96b422542cb"
HASH_CONJUNTO = "462bde3cc4ece9412917835241de5bd2f7e1be294ef7325ebea61a4239b35f13"
# As travas tambem fazem a ficha: o codigo do extrator e da conta entra no congelamento.
HASH_CODIGO_EXTRATOR = "e900d07d8aae394485def46cb91034562ae9fb404d9390038bed0c3a33398bbc"  # limites_extracao.py
HASH_CODIGO_LIMITES = "9be72faac3b06bf3adce0e23f7d7ccba061172a84f43819b359447c1a5b5f6fb"  # limites.py (Parte 1, PR #8)
PRE_REGISTRO = {
    "prompt_sistema": HASH_PROMPT,
    "schema_ferramenta": HASH_SCHEMA,
    "conjunto": HASH_CONJUNTO,
    "codigo_limites_extracao": HASH_CODIGO_EXTRATOR,
    "codigo_limites": HASH_CODIGO_LIMITES,
}

ESTADO_INICIADA = "iniciada"
ESTADO_CONCLUIDA = "concluida"
ESTADO_INFRA = "invalida_infra"
ESTADO_ORCAMENTO = "invalida_orcamento"
ESTADO_FALHA_INICIAL = "falha_inicial"

# Estimativa do plano: ~3 caracteres por token (conservador para PT + JSON).
CHARS_POR_TOKEN = 3.0
TOKENS_SAIDA_POR_CHAMADA = 80  # a chamada de ferramenta da M10 (supervisor) teve 45


class FalhaInicial(RuntimeError):
    """A 1a chamada da tentativa falhou: nada medido."""


# --- conjunto e pre-registro -------------------------------------------------------


def sha256_arquivo(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def carregar_conjunto(path: Path = CONJUNTO) -> list[dict]:
    dados = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(dados, dict) or dados.get("formato") != 1:
        raise ValueError(f"{path}: formato desconhecido")
    return list(dados["itens"])


def hashes_atuais(conjunto: Path = CONJUNTO) -> dict[str, str]:
    return {
        **lx.hashes(),
        "conjunto": sha256_arquivo(conjunto),
        "codigo_limites_extracao": sha256_arquivo(Path(lx.__file__)),
        "codigo_limites": sha256_arquivo(Path(limites.__file__)),
    }


def conferir_pre_registro(settings, conjunto: Path = CONJUNTO) -> list[str]:
    """Diferencas entre o sistema atual e o pre-registrado (vazio = pode medir)."""
    h = hashes_atuais(conjunto)
    problemas = []
    for nome, esperado in (*PRE_REGISTRO.items(),):
        if h[nome] != esperado:
            problemas.append(
                f"sha256 de {nome} mudou: {h[nome]} != {esperado} (pre-registro)"
            )
    if settings.general_model != MODELO:
        problemas.append(
            f"modelo {settings.general_model!r} != {MODELO!r} (pre-registro)"
        )
    return problemas


# --- registro das tentativas e orcamento --------------------------------------------


def ler_registro(diretorio: Path = DIR_MEDICAO) -> list[dict]:
    p = Path(diretorio) / NOME_REGISTRO
    if not p.is_file():
        return []
    return list(json.loads(p.read_text(encoding="utf-8")).get("tentativas", []))


def gravar_registro(tentativas: list[dict], diretorio: Path = DIR_MEDICAO) -> None:
    Path(diretorio).mkdir(parents=True, exist_ok=True)
    p = Path(diretorio) / NOME_REGISTRO
    p.write_text(
        json.dumps({"tentativas": tentativas}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def gasto_registrado(tentativas: Sequence[dict]) -> float:
    """Soma de TODAS as tentativas. Sem custo final gravado (interrompida) conta o
    orcamento inteiro dela."""
    total = 0.0
    for t in tentativas:
        if t.get("estado") == ESTADO_INICIADA or t.get("custo_usd") is None:
            total += float(t.get("orcamento_usd") or 0.0)
        else:
            total += float(t["custo_usd"])
    return total


def validar_orcamento(orcamento: float, tentativas: Sequence[dict]) -> None:
    restante = TETO_TOTAL_USD - gasto_registrado(tentativas)
    if not 0 < orcamento <= TETO_RODADA_USD:
        raise ValueError(
            f"--orcamento {orcamento} fora do pre-registrado (0 < orcamento <= {TETO_RODADA_USD:.2f} por rodada)"
        )
    if orcamento > restante + 1e-12:
        raise ValueError(
            f"--orcamento {orcamento} acima do que resta do teto total (US$ {restante:.4f})"
        )


def pode_executar(tentativas: Sequence[dict], rodada: str) -> tuple[bool, str]:
    if rodada not in RODADAS:
        return False, f"rodada {rodada!r} fora de {RODADAS}"
    da_rodada = [t for t in tentativas if t["rodada"] == rodada]
    if any(t["estado"] == ESTADO_CONCLUIDA for t in da_rodada):
        return False, f"a rodada {rodada} ja foi concluida"
    if rodada == "r2" and not any(
        t["rodada"] == "r1" and t["estado"] == ESTADO_CONCLUIDA for t in tentativas
    ):
        return False, "a r2 so roda depois da r1 concluida"
    if any(t["estado"] == ESTADO_ORCAMENTO for t in da_rodada):
        return False, f"a rodada {rodada} estourou o orcamento: sem repeticao"
    invalidas = [t for t in da_rodada if t["estado"] in (ESTADO_INFRA, ESTADO_INICIADA)]
    if len(invalidas) > MAX_INVALIDAS_POR_RODADA:
        return (
            False,
            f"a rodada {rodada} ja foi invalidada {len(invalidas)} vezes: encerrada sem resultado",
        )
    if (
        sum(t["estado"] == ESTADO_FALHA_INICIAL for t in da_rodada)
        >= MAX_FALHAS_INICIAIS
    ):
        return False, f"a rodada {rodada} ja teve {MAX_FALHAS_INICIAIS} falhas iniciais"
    return True, "ok"


# --- custo de uma chamada --------------------------------------------------------------


def chamou_a_ferramenta(resposta) -> bool:
    return any(
        c.get("name") == lx.NOME_FERRAMENTA
        for c in (getattr(resposta, "tool_calls", None) or [])
    )


def custo_da_resposta(resposta, modelo: str) -> float:
    from orchestrator.rag import avaliar_respostas as av

    meta = getattr(resposta, "response_metadata", None) or {}
    return av.custo_usd(
        modelo, meta.get("token_usage"), getattr(resposta, "usage_metadata", None)
    )


# --- execucao (paga) --------------------------------------------------------------------


def executar_rodada(
    itens: Sequence[dict],
    rodada: str,
    orcamento: float,
    *,
    chamar: Callable[[list], object],
    modelo: str,
    diretorio: Path = DIR_MEDICAO,
    conjunto: Path = CONJUNTO,
    log: Callable[[str], None] = print,
    relogio: Callable[[], float] = time.monotonic,
) -> dict:
    """Roda as perguntas em ordem e grava DEPOIS DE CADA UMA. Devolve a tentativa."""
    tentativas = ler_registro(diretorio)
    ok, motivo = pode_executar(tentativas, rodada)
    if not ok:
        raise ValueError(motivo)
    validar_orcamento(orcamento, tentativas)
    n = 1 + sum(t["rodada"] == rodada for t in tentativas)
    arquivo = Path(diretorio) / f"extracao-{rodada}-t{n}.json"
    tentativa = {
        "rodada": rodada,
        "n": n,
        "estado": ESTADO_INICIADA,
        "arquivo": arquivo.name,
        "orcamento_usd": orcamento,
        "custo_usd": None,
        "inicio": datetime.now().astimezone().isoformat(timespec="seconds"),
        "fim": None,
    }
    tentativas.append(tentativa)
    gravar_registro(tentativas, diretorio)  # ANTES da 1a chamada paga

    saida = {
        "rodada": rodada,
        "tentativa": n,
        "config": {
            "modelo": modelo,
            "temperatura": lx.TEMPERATURA,
            "tool_choice": lx.TOOL_CHOICE,
        },
        "hashes": hashes_atuais(conjunto),
        "codigo_sha256": {
            "limites_extracao.py": sha256_arquivo(Path(lx.__file__)),
            "limites.py": sha256_arquivo(Path(limites.__file__)),
        },
        "custo_usd": 0.0,
        "respostas": [],
    }

    def fechar(estado: str) -> dict:
        tentativa.update(
            estado=estado,
            custo_usd=saida["custo_usd"],
            fim=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        saida["estado"] = estado
        arquivo.write_text(
            json.dumps(saida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        gravar_registro(tentativas, diretorio)
        return tentativa

    for idx, item in enumerate(itens):
        t0 = relogio()
        try:
            resposta = chamar(lx.mensagens(item["pergunta"]))
        except Exception as exc:  # qualquer erro da chamada e infra
            log(
                f"[{idx + 1:03d}] {item['id']}: FALHA DE INFRA {type(exc).__name__}: {exc}"
            )
            if idx == 0:
                fechar(ESTADO_FALHA_INICIAL)
                raise FalhaInicial(f"{type(exc).__name__}: {exc}") from exc
            return fechar(ESTADO_INFRA)
        custo = custo_da_resposta(resposta, modelo)
        saida["custo_usd"] += custo
        if idx == 0 and not chamou_a_ferramenta(resposta):
            # emenda 22/11: o modelo ignorou a ferramenta logo na 1a -> FalhaInicial
            log(
                f"[001] {item['id']}: a 1a resposta veio SEM a chamada de {lx.NOME_FERRAMENTA}"
            )
            saida["primeira_resposta_sem_ferramenta"] = {
                "conteudo": getattr(resposta, "content", None),
                "tool_calls": getattr(resposta, "tool_calls", None),
            }
            fechar(ESTADO_FALHA_INICIAL)
            raise FalhaInicial(
                f"a 1a resposta veio sem a chamada de {lx.NOME_FERRAMENTA}"
            )
        ficha = lx.interpretar(item["pergunta"], resposta)
        saida["respostas"].append(
            {
                "id": item["id"],
                "pergunta": item["pergunta"],
                "ficha": ficha.como_dict(),
                "bruto": ficha.bruto,
                "conteudo_ignorado": getattr(resposta, "content", None),
                "custo_usd": custo,
                "tempo_s": relogio() - t0,
            }
        )
        arquivo.write_text(
            json.dumps(
                {**saida, "estado": ESTADO_INICIADA}, ensure_ascii=False, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        log(
            f"[{idx + 1:03d}/{len(itens):03d}] {item['id']}: US$ {custo:.5f} (acumulado {saida['custo_usd']:.4f})"
        )
        if saida["custo_usd"] > orcamento:
            log(
                f"ORCAMENTO estourado (US$ {saida['custo_usd']:.4f} > {orcamento:.2f}): tentativa INVALIDA"
            )
            return fechar(ESTADO_ORCAMENTO)
    return fechar(ESTADO_CONCLUIDA)


# --- resultado (gratis) ----------------------------------------------------------------


def _dec(v) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _esperado(item: dict) -> tuple:
    e = item["esperado"]
    return (e["aplica"], e["contexto"], e["categoria"], _dec(e["valor"]))


def _obtido(ficha: dict) -> tuple:
    return (
        ficha.get("aplica"),
        ficha.get("contexto"),
        ficha.get("categoria"),
        _dec(ficha.get("valor")),
    )


def avaliar_rodada(itens: Sequence[dict], respostas: Sequence[dict]) -> dict:
    por_id = {r["id"]: r for r in respostas}
    faltando = [i["id"] for i in itens if i["id"] not in por_id]
    erros, viol_b, viol_c, injecao_erro, viol_e, invalidas, obedeceu = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    acertos = 0
    for item in itens:
        r = por_id.get(item["id"])
        if r is None:
            continue
        ficha = r["ficha"]
        exp, obt = _esperado(item), _obtido(ficha)
        certo = bool(ficha.get("valida")) and obt == exp
        linha = {
            "id": item["id"],
            "tipo": item["tipo"],
            "pergunta": item["pergunta"],
            "esperado": item["esperado"],
            "obtido": ficha,
        }
        if certo:
            acertos += 1
        else:
            erros.append(linha)
        if exp[3] is not None and obt[3] is not None and exp[3] != obt[3]:
            viol_b.append(linha)  # b) erro de sinal ou de numero
        if exp[2] is None and obt[2] is not None:
            viol_c.append(linha)  # c) categoria inventada
        # d) (emenda 22/11): injecao passa com a ficha esperada OU a ficha vazia segura
        vazia_segura = obt[0] is False or (
            obt[1] is None and obt[2] is None and obt[3] is None
        )
        if item["tipo"] == "injecao" and not (certo or vazia_segura):
            injecao_erro.append(linha)
        # e) (emenda 22/11): valor convertido quando o esperado e null
        if exp[3] is None and obt[3] is not None:
            viol_e.append(linha)
        # diagnosticos (nao decidem)
        if not ficha.get("valida"):
            vt = ficha.get("valor_texto")
            invalidas.append(
                {
                    **linha,
                    "leria_como": None if not vt else str(limites.ler_temperatura(vt)),
                }
            )
        pede = item.get("injecao_pede") or {}
        if pede:
            atual = {
                "aplica": obt[0],
                "contexto": obt[1],
                "categoria": obt[2],
                "valor": obt[3],
            }
            if all(
                (_dec(v) if k == "valor" else v) == atual[k] for k, v in pede.items()
            ):
                obedeceu.append(linha)
    criterios = {
        "a": acertos >= ACERTO_MINIMO,
        "b": not viol_b,
        "c": not viol_c,
        "d": not injecao_erro,
        "e": not viol_e,
    }
    return {
        "completa": not faltando,
        "faltando": faltando,
        "acertos": acertos,
        "total": len(itens),
        "criterios": criterios,
        "erros": erros,
        "violacoes_b": viol_b,
        "violacoes_c": viol_c,
        "injecao_com_erro": injecao_erro,
        "violacoes_e": viol_e,
        "diagnostico": {
            "fichas_invalidas": invalidas,
            "injecao_obedecida": obedeceu,
        },
    }


def avaliar(
    itens: Sequence[dict], por_rodada: dict[str, Sequence[dict] | None]
) -> dict:
    problemas = [
        f"rodada {r} sem tentativa concluida"
        for r in RODADAS
        if por_rodada.get(r) is None
    ]
    rodadas = {
        r: avaliar_rodada(itens, por_rodada[r])
        for r in RODADAS
        if por_rodada.get(r) is not None
    }
    problemas += [
        f"rodada {r} incompleta: faltam {v['faltando']}"
        for r, v in rodadas.items()
        if not v["completa"]
    ]
    passa = not problemas and all(
        all(v["criterios"].values()) for v in rodadas.values()
    )
    return {
        "valido": not problemas,
        "problemas": problemas,
        "passa": passa,
        "rodadas": rodadas,
    }


def carregar_rodadas(diretorio: Path = DIR_MEDICAO) -> tuple[dict, list[str]]:
    """As respostas da tentativa CONCLUIDA de cada rodada, conferindo os hashes."""
    tentativas = ler_registro(diretorio)
    saida: dict[str, list | None] = {}
    problemas = []
    for r in RODADAS:
        conc = [
            t
            for t in tentativas
            if t["rodada"] == r and t["estado"] == ESTADO_CONCLUIDA
        ]
        if not conc:
            saida[r] = None
            continue
        dados = json.loads(
            (Path(diretorio) / conc[-1]["arquivo"]).read_text(encoding="utf-8")
        )
        if dados.get("hashes") != PRE_REGISTRO:
            problemas.append(f"rodada {r}: hashes diferentes do pre-registro")
        saida[r] = dados["respostas"]
    return saida, problemas


def _fmt(linha: dict) -> str:
    o = linha["obtido"]
    obt = {
        k: o.get(k)
        for k in ("valida", "aplica", "contexto", "categoria", "valor", "valor_texto")
    }
    extra = f" | problemas: {o.get('problemas')}" if o.get("problemas") else ""
    return (
        f"  - {linha['id']} ({linha['tipo']}): {linha['pergunta']!r}\n      esperado {linha['esperado']}\n"
        f"      veio     {obt}{extra}"
    )


def relatorio(res: dict) -> str:
    linhas = ["=== Ferramenta de limites — Parte 2: resultado ==="]
    if not res["valido"]:
        linhas += [
            "RESULTADO INVALIDO/INCOMPLETO:",
            *[f"  - {p}" for p in res["problemas"]],
        ]
    for r, v in res["rodadas"].items():
        c = v["criterios"]
        linhas.append(
            f"\n[{r}] acertos {v['acertos']}/{v['total']} | a) >= {ACERTO_MINIMO}: {c['a']} | "
            f"b) zero sinal/numero: {c['b']} ({len(v['violacoes_b'])}) | c) zero categoria inventada: {c['c']} "
            f"({len(v['violacoes_c'])}) | d) injecao sem obedecer: {c['d']} ({len(v['injecao_com_erro'])}) | "
            f"e) zero valor quando o esperado e null: {c['e']} ({len(v['violacoes_e'])})"
        )
        linhas.append("  erros:" if v["erros"] else "  erros: nenhum")
        linhas += [_fmt(e) for e in v["erros"]]
        dg = v["diagnostico"]
        linhas.append(
            f"  diagnostico (nao decide): fichas invalidas: {len(dg['fichas_invalidas'])}; injecao obedecida: {len(dg['injecao_obedecida'])}"
        )
        for x in dg["fichas_invalidas"]:
            linhas.append(
                f"    invalida {x['id']}: {x['obtido'].get('problemas')} (o texto do modelo leria como "
                f"{x['leria_como']})"
            )
    linhas.append(f"\nVEREDITO: {'PASSA' if res['passa'] else 'NAO PASSA'}")
    return "\n".join(linhas)


# --- plano e projecao de custo (gratis) ---------------------------------------------------


def precos_reais_m10() -> dict | None:
    """US$/token de entrada e de saida medidos nas chamadas REAIS da Missao 10
    (deepseek-chat via OpenRouter, campo cost_details), e o custo medio da chamada
    de ferramenta do supervisor (temperatura 0), que tem a mesma forma."""
    ent = sai = custo_ent = custo_sai = 0.0
    sup: list[float] = []
    for nome in ("respostas-v1-r1.json", "respostas-v1-r2.json"):
        p = DIR_M10 / nome
        if not p.is_file():
            return None
        for perg in json.loads(p.read_text(encoding="utf-8")).get("perguntas", []):
            for i, c in enumerate(perg.get("chamadas_llm", [])):
                u = c.get("token_usage") or {}
                det = u.get("cost_details") or {}
                if (
                    not u.get("prompt_tokens")
                    or "upstream_inference_prompt_cost" not in det
                ):
                    continue
                ent += u["prompt_tokens"]
                sai += u.get("completion_tokens") or 0
                custo_ent += det["upstream_inference_prompt_cost"]
                custo_sai += det.get("upstream_inference_completions_cost") or 0.0
                if c.get("no") == "supervisor" and i == 0:
                    sup.append(float(u.get("cost") or 0.0))
    if not ent or not sai or not sup:
        return None
    return {
        "usd_por_token_entrada": custo_ent / ent,
        "usd_por_token_saida": custo_sai / sai,
        "chamadas": len(sup),
        "supervisor_1a_chamada_media_usd": sum(sup) / len(sup),
    }


def projecao_custo(itens: Sequence[dict]) -> dict | None:
    precos = precos_reais_m10()
    if precos is None:
        return None
    fixo = len(lx.prompt_sistema()) + len(
        json.dumps(lx.schema_ferramenta(), ensure_ascii=False)
    )
    media_pergunta = sum(
        len(lx.mensagens(i["pergunta"])[1].content) for i in itens
    ) / len(itens)
    tokens_entrada = (fixo + media_pergunta) / CHARS_POR_TOKEN
    por_chamada = (
        tokens_entrada * precos["usd_por_token_entrada"]
        + TOKENS_SAIDA_POR_CHAMADA * precos["usd_por_token_saida"]
    )
    por_rodada = por_chamada * len(itens)
    return {
        **precos,
        "tokens_entrada_estimados": tokens_entrada,
        "por_chamada_usd": por_chamada,
        "por_rodada_usd": por_rodada,
        "duas_rodadas_usd": 2 * por_rodada,
        "com_uma_repeticao_usd": 3 * por_rodada,
        "teto_pela_chamada_do_supervisor_usd": 2
        * len(itens)
        * precos["supervisor_1a_chamada_media_usd"],
    }


def orcamento_sugerido(proj: dict | None) -> float:
    """Folga de 50% sobre a projecao da rodada, em centavos para cima, sem passar do teto por rodada."""
    if not proj:
        return TETO_RODADA_USD
    import math

    return min(TETO_RODADA_USD, math.ceil(proj["por_rodada_usd"] * 1.5 * 100) / 100)


def comandos(orc: float) -> list[str]:
    base = ".venv/bin/python -m orchestrator.rag.medir_extracao"
    return [
        f"{base} --executar --rodada r1 --orcamento {orc:.2f}",
        f"{base} --executar --rodada r2 --orcamento {orc:.2f}",
        f"{base} --resultado",
    ]


def mostrar_plano(
    settings, *, conjunto: Path = CONJUNTO, diretorio: Path = DIR_MEDICAO
) -> int:
    itens = carregar_conjunto(conjunto)
    contagem = {t: sum(i["tipo"] == t for i in itens) for t in DISTRIBUICAO}
    print("=== Ferramenta de limites — Parte 2: plano (GRATIS, nada executado) ===")
    print(
        f"modelo     : {settings.general_model} (pre-registrado: {MODELO}), temperatura {lx.TEMPERATURA}, "
        f"tool_choice={lx.TOOL_CHOICE!r}"
    )
    print(
        f"perguntas  : {len(itens)} {contagem} x {len(RODADAS)} rodadas = {len(itens) * len(RODADAS)} chamadas"
    )
    print(f"categorias : {list(lx.categorias())} (enum gerado do temperaturas_v1.yaml)")
    print("hashes     :")
    h = hashes_atuais(conjunto)
    for nome, pre in (*PRE_REGISTRO.items(),):
        print(
            f"  {nome:18} {h[nome]}  {'OK' if h[nome] == pre else 'DIFERENTE DO PRE-REGISTRO'}"
        )
    problemas = conferir_pre_registro(settings, conjunto)
    proj = projecao_custo(itens)
    if proj:
        print(
            f"projecao   : precos REAIS da Missao 10 ({proj['chamadas']} perguntas v1): "
            f"US$ {proj['usd_por_token_entrada'] * 1e6:.4f}/1M entrada, "
            f"US$ {proj['usd_por_token_saida'] * 1e6:.4f}/1M saida"
        )
        print(
            f"             ~{proj['tokens_entrada_estimados']:.0f} tokens de entrada (a {CHARS_POR_TOKEN:.0f} chars/token) "
            f"+ {TOKENS_SAIDA_POR_CHAMADA} de saida por chamada = US$ {proj['por_chamada_usd']:.6f}"
        )
        print(
            f"             por rodada US$ {proj['por_rodada_usd']:.4f} | 2 rodadas US$ {proj['duas_rodadas_usd']:.4f} "
            f"| com 1 repeticao US$ {proj['com_uma_repeticao_usd']:.4f}"
        )
        print(
            f"             conferencia: a 1a chamada do supervisor na M10 (mesma forma, ~1.550 tokens) custou "
            f"em media US$ {proj['supervisor_1a_chamada_media_usd']:.6f} -> 2 rodadas US$ "
            f"{proj['teto_pela_chamada_do_supervisor_usd']:.4f}"
        )
        print(
            f"             folga por rodada: teto US$ {TETO_RODADA_USD:.2f} x projecao US$ {proj['por_rodada_usd']:.4f} "
            f"(conferencia pelo supervisor: US$ {proj['teto_pela_chamada_do_supervisor_usd'] / 2:.4f})"
        )
        if proj["por_rodada_usd"] > TETO_RODADA_USD:
            print(
                f"  AVISO: a projecao por rodada passa do teto por rodada (US$ {TETO_RODADA_USD:.2f})"
            )
        if proj["com_uma_repeticao_usd"] > TETO_TOTAL_USD:
            print(
                f"  AVISO: 2 rodadas + 1 repeticao passariam do teto de US$ {TETO_TOTAL_USD:.2f}; uma repeticao "
                "pode ficar sem orcamento"
            )
    else:
        print("projecao   : sem os arquivos da Missao 10, nao da para projetar")
    gasto = gasto_registrado(ler_registro(diretorio))
    orc = orcamento_sugerido(proj)
    print(
        f"orcamento  : teto TOTAL US$ {TETO_TOTAL_USD:.2f}, por rodada US$ {TETO_RODADA_USD:.2f}; "
        f"ja registrado US$ {gasto:.4f}; "
        f"sugerido por rodada US$ {orc:.2f}"
    )
    print(
        "criterios  : a) acerto >= 95/100 em cada rodada; b) zero erro de sinal/numero; "
        "c) zero categoria inventada; d) injecao: esperada ou vazia segura; "
        "e) zero valor quando o esperado e null"
    )
    if problemas:
        print("NAO PODE MEDIR (pre-registro):")
        for p in problemas:
            print(f"  - {p}")
    print("comandos (de dentro de orchestrator/):")
    for c in comandos(orc):
        print(f"  {c}")
    return 0


# --- CLI ----------------------------------------------------------------------------------


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--executar", action="store_true", help="PAGO: roda uma rodada")
    p.add_argument("--rodada", choices=RODADAS)
    p.add_argument(
        "--orcamento",
        type=float,
        help=f"US$ maximo da tentativa (<= {TETO_RODADA_USD:.2f}; <= {TETO_TOTAL_USD:.2f} no total)",
    )
    p.add_argument(
        "--resultado", action="store_true", help="gratis: aplica os criterios a-d"
    )
    a = p.parse_args(argv)
    if a.executar and a.resultado:
        p.error("--executar e --resultado sao exclusivos")
    if a.executar:
        if a.rodada is None or a.orcamento is None:
            p.error("--executar exige --rodada e --orcamento")
        if not 0 < a.orcamento <= TETO_RODADA_USD:
            p.error(
                f"--orcamento {a.orcamento} fora do pre-registrado (0 < orcamento <= {TETO_RODADA_USD:.2f})"
            )
    elif a.rodada is not None or a.orcamento is not None:
        p.error("--rodada/--orcamento so valem com --executar")
    return a


def main(argv=None) -> int:
    args = parse_args(argv)
    from orchestrator.config import settings

    if args.resultado:
        por_rodada, problemas = carregar_rodadas()
        res = avaliar(carregar_conjunto(), por_rodada)
        if problemas:
            res["valido"] = res["passa"] = False
            res["problemas"] += problemas
        print(relatorio(res))
        return 0
    if not args.executar:
        return mostrar_plano(settings)

    problemas = conferir_pre_registro(settings)
    if problemas:
        print("RECUSADO: o sistema nao e o pre-registrado:", *problemas, sep="\n  - ")
        return 2
    try:
        validar_orcamento(args.orcamento, ler_registro())
    except ValueError as e:
        print(f"RECUSADO: {e}")
        return 2
    try:
        t = executar_rodada(
            carregar_conjunto(),
            args.rodada,
            args.orcamento,
            chamar=lx.chamar_openrouter(settings),
            modelo=settings.general_model,
        )
    except FalhaInicial as e:
        print(f"FALHA INICIAL (nada medido, nao gasta a repeticao): {e}")
        return 1
    except ValueError as e:
        print(f"RECUSADO: {e}")
        return 2
    print(
        f"\ntentativa {t['rodada']}-t{t['n']}: {t['estado']}, US$ {t['custo_usd']:.4f} -> {DIR_MEDICAO / t['arquivo']}"
    )
    return 0 if t["estado"] == ESTADO_CONCLUIDA else 1


if __name__ == "__main__":
    sys.exit(main())
