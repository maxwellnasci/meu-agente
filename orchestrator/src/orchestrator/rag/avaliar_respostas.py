"""Missao 8: avaliacao de PONTA A PONTA do RAG (roteamento + resposta).

As 20 perguntas do gabarito passam pelo grafo INTEIRO (supervisor ->
specialist_rag -> supervisor -> synthesize_final) com o LLM REAL, como no
smoke. Mede, NAO otimiza: nenhuma mudanca de prompt ou de roteamento aqui.

    cd orchestrator
    python -m orchestrator.rag.avaliar_respostas                               # 0. plano + custo (gratis)
    python -m orchestrator.rag.avaliar_respostas --executar --etapa respostas  # 1. pago: grafo com LLM real
    python -m orchestrator.rag.avaliar_respostas --calibracao                  # 2. gratis: arquivo p/ o Max marcar
    #                                                                            3. o Max marca as 8 (sem ver o juiz)
    python -m orchestrator.rag.avaliar_respostas --executar --etapa julgar     # 4. pago: juiz (exige 3 feito)
    #   ... --executar --etapa julgar --sem-calibracao                         #    desvio de 20/11: sem o 3 completo
    python -m orchestrator.rag.avaliar_respostas --concordancia                # 5. gratis: humano x juiz
    python -m orchestrator.rag.avaliar_respostas --relatorio                   # 6. gratis: metricas dos JSONs

Calibracao CEGA, garantida em codigo: o juiz so roda depois de a calibracao
estar marcada, e o log do juiz nao mostra veredito. Antes do juiz, o
`--relatorio` mostra so as metricas deterministicas.
DESVIO de 20/11/2026 (Max): a calibracao parou em 1/8. A flag explicita
`--sem-calibracao` libera o juiz e grava `calibracao.status = nao_calibrada`
no julgamento; o `--relatorio` entao mostra o juiz rotulado "NAO calibrada".
Sem a flag, a trava acima continua igual.

Falha de infraestrutura (erro de LLM capturado por um no, ex. 429/timeout no
supervisor, que cai no fallback) fica registrada em `erros_llm` e marcada
"infra" no relatorio. Conta como ERRO nas metricas e nao ha nova rodada
(pre-registro). Se a PRIMEIRA pergunta (ou a primeira chamada do juiz) falhar,
a etapa para sem gravar o arquivo (chave errada, schema recusado...).

Tudo o que foi gerado vai para `fixtures/rag/m8/` (versionado), para
reavaliar sem custo. Criterios pre-registrados em docs/RAG.md (Missao 8).

Isolamento (igual ao smoke): n8n e gateway do OpenClaw neutralizados no
`settings`, `rag_enabled` ligado so neste processo, MemorySaver e um
thread_id novo por pergunta. O `.env` (cwd) so fornece a chave do OpenRouter
e os modelos.

Resposta CRUA x FINAL: o `garantir_citacao` anexa "Fontes consultadas..."
quando o LLM nao cita. Um espiao (so neste processo, repassa a chamada sem
mudar nada) guarda o texto do LLM antes do anexo. As metricas (b), (c)
espontanea, (d), (e), (f) e (g) usam a CRUA; a (c) final e so informativa.

(g) formato (pre-registro de 20/11, `fixtures/rag/formato_v1.yaml` com hash
conferido): Sim/Nao na 1a linha (nas sim/nao), principal <= 3 linhas de 80
caracteres antes da 1a linha em branco, ultima linha oferecendo detalhes.
Deterministica, sem LLM. Linha de base: as regras atuais nao pedem o formato.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import yaml
from langchain_core.callbacks import BaseCallbackHandler

from orchestrator.rag import juiz
from orchestrator.rag.ingest import ORCHESTRATOR_DIR

GABARITO = ORCHESTRATOR_DIR / "fixtures" / "rag" / "gabarito.yaml"
FATOS_CHAVE = ORCHESTRATOR_DIR / "fixtures" / "rag" / "fatos_chave_v1.yaml"
HASH_FATOS_CHAVE = "16600f54fc6bc459bf5171af7b23552bd264a07fd07d388c5523f39c3258b4ca"
# Metrica (g) formato: pre-registrada em 20/11/2026 (depois da coleta, antes do calculo).
FORMATO = ORCHESTRATOR_DIR / "fixtures" / "rag" / "formato_v1.yaml"
HASH_FORMATO = "6f5605e7e4fc4ae7fc63f3f4613a16c618577718ad0bd00f3c87961115bd2def"
DIR_SAIDA = ORCHESTRATOR_DIR / "fixtures" / "rag" / "m8"
CALIBRACAO = DIR_SAIDA / "calibracao_v1.yaml"
COM_FONTE = ("direta", "multi_secao")

ORCAMENTO_USD = 1.00  # por etapa paga; estourou -> interrompe e grava o parcial
# US$ por 1M tokens (entrada, saida), tabela publica do OpenRouter em 19/11/2026.
# So vale quando o OpenRouter nao devolve `cost` no usage.
PRECOS = {
    "deepseek/deepseek-chat": (0.2574, 1.0287),
    "google/gemini-3.8-flash": (0.825, 4.125),
}
PRECO_DESCONHECIDO = (5.0, 30.0)  # modelo fora da tabela: conta caro (orcamento conservador)

LIMIAR_CONCORDANCIA = 7  # de 8: >= 7 aceitavel; <= 6 juiz nao confiavel (sem ajustar prompt)
N_CALIBRACAO = 8
CALIBRACAO_FIXAS = ("q18", "q19", "q15")

# Estimativa do plano (teto): ~3 caracteres por token (PT + JSON schema).
CHARS_POR_TOKEN = 3.0
CHARS_POR_TRECHO = 750  # maior nota medida: 3.715 caracteres em 5 trechos
SAIDA_SUPERVISOR = (150, 100)
SAIDA_SYNTH = 600
SAIDA_JUIZ_FIDELIDADE = 600 + 2000  # JSON + raciocinio "low"
SAIDA_JUIZ_CORRECAO = 300 + 1500

FRASE_ANEXO = "Fontes consultadas no manual:"

# --- normalizacao e checagens deterministicas -------------------------------

_SINAIS = str.maketrans({"−": "-", "–": "-", "—": "-", " ": " ",
                         "“": '"', "”": '"', "‘": "'", "’": "'"})
_TITULO_CITADO = re.compile(r'secao\s*"[^"]*"')
_RECUSA = re.compile(
    r"\bnao (cobre|sei|trata|preve|fala|define|menciona|estabelece|traz|especifica)\b"
    r"|\bnao ha (informacao|previsao|regra|mencao)"
)
_CITACAO = re.compile(r'\bpop ?-? ?\d+|secao\s*"[^"]*"|secao \d+')
_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")


def normalizar(texto: str) -> str:
    """Sem acento, minusculas, sinais de menos/aspas unificados, espacos colapsados."""
    texto = (texto or "").translate(_SINAIS)
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)).lower()
    return " ".join(texto.split())


def sem_titulos_citados(texto_normalizado: str) -> str:
    """Tira o TITULO das secoes citadas (secao "2. Sangria") antes da checagem
    de fatos; os codigos de POP ficam (a q13 exige "POP-07")."""
    return _TITULO_CITADO.sub("secao", texto_normalizado)


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def carregar_gabarito(path: Path = GABARITO) -> list[dict]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))["perguntas"]


def carregar_fatos(path: Path = FATOS_CHAVE, hash_esperado: str = HASH_FATOS_CHAVE) -> dict[str, list[tuple[str, re.Pattern]]]:
    atual = juiz.sha256_arquivo(path)
    if atual != hash_esperado:
        raise juiz.PromptAdulterado(f"fatos-chave ({Path(path).name}) mudaram: {atual} != pre-registrado {hash_esperado}")
    dados = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {qid: [(f["nome"], re.compile(f["padrao"])) for f in fatos] for qid, fatos in dados["fatos"].items()}


def checar_fatos(resposta: str, fatos: Sequence[tuple[str, re.Pattern]]) -> dict:
    texto = sem_titulos_citados(normalizar(resposta))
    achados = [nome for nome, rx in fatos if rx.search(texto)]
    ausentes = [nome for nome, _ in fatos if nome not in achados]
    return {"acerto": not ausentes, "fracao": len(achados) / len(fatos) if fatos else 0.0,
            "encontrados": achados, "ausentes": ausentes}


def checar_citacao(resposta: str, item: dict) -> bool:
    """Cita TODAS as fontes do gabarito (POP + titulo da secao; numa
    multi_secao, as duas). Mesmo criterio do `garantir_citacao`."""
    from orchestrator.graph.rag_specialist import _cita_fonte_completa, codigo_pop

    return all(_cita_fonte_completa(resposta, codigo_pop(a), s)
               for a, s in zip(item["arquivo_fonte"], item["secao_fonte"], strict=True))


def _numeros(texto_normalizado: str) -> set[str]:
    def canon(n: str) -> str:
        n = re.sub(r"[.,]0+$", "", n)
        return re.sub(r"^0+(?=\d)", "", n)

    return {canon(n) for n in _NUMERO.findall(texto_normalizado)}


def checar_sem_resposta(resposta: str, trechos: Sequence[dict]) -> dict:
    """(e) deterministica: frase de recusa E nenhum numero que nao esteja nos
    trechos (fora as citacoes POP-XX / secao). Sem trecho, qualquer numero erra."""
    texto = normalizar(resposta)
    recusa = bool(_RECUSA.search(texto))
    nos_trechos = _numeros(normalizar(" ".join(t["texto"] for t in trechos)))
    inventados = sorted(_numeros(_CITACAO.sub(" ", texto)) - nos_trechos)
    return {"acerto": recusa and not inventados, "recusa": recusa, "numeros_fora_dos_trechos": inventados}


# --- (g) formato, deterministica (fixtures/rag/formato_v1.yaml) -------------

_MD_QUALQUER = re.compile(r"[*_`]")
_MD_INICIO = re.compile(r"^\s*(?:[#>]+\s*)*(?:(?:[-+•]|\d+[.)])\s+)?")


def carregar_formato(path: Path = FORMATO, hash_esperado: str = HASH_FORMATO) -> dict:
    atual = juiz.sha256_arquivo(path)
    if atual != hash_esperado:
        raise juiz.PromptAdulterado(f"criterio de formato ({Path(path).name}) mudou: {atual} != pre-registrado {hash_esperado}")
    dados = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {
        "sim_nao": frozenset(dados["perguntas_sim_nao"]),
        "inicio": re.compile(dados["regex_inicio"]),
        "max_linhas": int(dados["max_linhas"]),
        "largura": int(dados["largura_linha"]),
        "oferta": re.compile(dados["regex_oferta"]),
        "citacao": re.compile(dados["regex_citacao"]),
        "rotulo_citacao": re.compile(dados["regex_rotulo_citacao"]),
    }


def limpar_linha(linha: str) -> str:
    """Tira markdown: * _ ` em qualquer posicao; # > e marcador de lista do inicio."""
    return _MD_INICIO.sub("", _MD_QUALQUER.sub("", linha)).strip()


def _so_citacao(linha_normalizada: str, fmt: dict) -> bool:
    resto = fmt["rotulo_citacao"].sub(" ", fmt["citacao"].sub(" ", linha_normalizada))
    return not re.search(r"[a-z0-9]", resto)


def checar_formato(resposta: str, qid: str, fmt: dict) -> dict:
    """(g): (a) 1a linha comeca por Sim/Nao (so nas sim/nao; senao None),
    (b) principal (antes da 1a linha em branco) <= max_linhas, cada linha
    valendo ceil(caracteres/largura), (c) ultima linha (sem as linhas so de
    citacao) termina com "?" e oferece detalhes."""
    linhas = [limpar_linha(x) for x in (resposta or "").split("\n")]
    nao_vazias = [x for x in linhas if x]
    sim_nao = None
    if qid in fmt["sim_nao"]:
        sim_nao = bool(nao_vazias) and bool(fmt["inicio"].search(normalizar(nao_vazias[0])))
    principal = []
    for x in linhas:
        if x:
            principal.append(x)
        elif principal:
            break  # 1a linha em branco depois do texto: comeca o complemento
    n_linhas = sum(-(-len(x) // fmt["largura"]) for x in principal)
    fim = [normalizar(x) for x in nao_vazias]
    while fim and _so_citacao(fim[-1], fmt):
        fim.pop()
    oferece = bool(fim) and fim[-1].endswith("?") and bool(fmt["oferta"].search(fim[-1]))
    return {"sim_nao": sim_nao, "linhas_principal": n_linhas,
            "principal_curta": bool(principal) and n_linhas <= fmt["max_linhas"], "oferece_detalhes": oferece}


# --- execucao do grafo ------------------------------------------------------

_TRECHO = re.compile(
    r'<trecho n="(\d+)" pop="([^"]*)" secao="([^"]*)" marca="([0-9a-f]+)">\n(.*?)\n</trecho n="\1" marca="\4">',
    re.DOTALL,
)


def extrair_trechos(scratchpad: Sequence[str]) -> list[dict]:
    import html

    trechos = []
    for nota in scratchpad:
        if nota.startswith("[rag]"):
            for n, pop, secao, _, texto in _TRECHO.findall(nota):
                trechos.append({"n": int(n), "pop": html.unescape(pop), "secao": html.unescape(secao), "texto": texto})
    return trechos


class FalhaInicial(RuntimeError):
    """A primeira pergunta/chamada da etapa falhou: nada e gravado."""


class ColetorGrafo(BaseCallbackHandler):
    """Caminho no grafo (nos do LangGraph), uso de cada chamada de LLM e erros
    de LLM que o proprio no capturou (o grafo nao levanta: o supervisor cai no
    fallback openclaw, o que pareceria uma decisao de roteamento)."""

    def __init__(self) -> None:
        self.caminho: list[str] = []
        self.chamadas: list[dict] = []
        self.erros_llm: list[dict] = []
        self._no_da_chamada: dict = {}

    def on_chain_start(self, serialized, inputs, *, run_id=None, metadata=None, **kwargs):
        nome = kwargs.get("name") or (serialized or {}).get("name")
        if nome and (metadata or {}).get("langgraph_node") == nome:
            self.caminho.append(nome)

    def on_chat_model_start(self, serialized, messages, *, run_id=None, metadata=None, **kwargs):
        self._no_da_chamada[run_id] = (metadata or {}).get("langgraph_node")

    def on_llm_end(self, response, *, run_id=None, **kwargs):
        saida = getattr(response, "llm_output", None) or {}
        msg = None
        try:
            msg = response.generations[0][0].message
        except (AttributeError, IndexError):
            pass
        meta = getattr(msg, "response_metadata", None) or {}
        modelo = saida.get("model_name") or meta.get("model_name")
        uso = saida.get("token_usage") or meta.get("token_usage")
        self.chamadas.append({
            "no": self._no_da_chamada.pop(run_id, None),
            "modelo_devolvido": modelo,
            "token_usage": uso,
            "usage_metadata": getattr(msg, "usage_metadata", None),
        })

    def on_llm_error(self, error, *, run_id=None, **kwargs):
        self.erros_llm.append({"no": self._no_da_chamada.pop(run_id, None), "erro_tipo": type(error).__name__})


def custo_usd(modelo_pedido: str, token_usage: dict | None, usage_metadata: dict | None = None) -> float:
    """`cost` do OpenRouter se vier; senao, tokens x tabela PRECOS."""
    uso = token_usage or {}
    if isinstance(uso.get("cost"), int | float):
        return float(uso["cost"])
    entrada = uso.get("prompt_tokens") or (usage_metadata or {}).get("input_tokens") or 0
    saida = uso.get("completion_tokens") or (usage_metadata or {}).get("output_tokens") or 0
    pe, ps = PRECOS.get(modelo_pedido, PRECO_DESCONHECIDO)
    return (entrada * pe + saida * ps) / 1_000_000


def _git() -> dict:
    def run(*args):
        r = subprocess.run(["git", *args], cwd=ORCHESTRATOR_DIR, capture_output=True, text=True, check=False)
        return r.stdout.strip() if r.returncode == 0 else None

    status = run("status", "--porcelain")
    return {"sha": run("rev-parse", "HEAD"), "sujo": bool(status) if status is not None else None}


def _hashes_do_sistema(settings) -> dict:
    from orchestrator.graph import nodes, rag_specialist
    from orchestrator.schemas.routing import dispatch_tool

    return {
        "gabarito": juiz.sha256_arquivo(GABARITO),
        "fatos_chave": juiz.sha256_arquivo(FATOS_CHAVE),
        "regras_do_manual": sha256_texto(rag_specialist.REGRAS_DO_MANUAL),
        "prompt_supervisor": sha256_texto(nodes.supervisor_system_prompt(True)),
        "prompt_synthesize": sha256_texto(nodes._SYNTHESIZE_SYSTEM_PROMPT),
        "tool_dispatch": sha256_texto(json.dumps(dispatch_tool(True), sort_keys=True, ensure_ascii=False)),
    }


def _meta_do_indice(settings) -> dict | None:
    from orchestrator.rag.store import open_index, read_meta

    try:
        conn = open_index(Path(settings.rag_index_path))
    except FileNotFoundError:
        return None
    try:
        return read_meta(conn)
    finally:
        conn.close()


async def responder_pergunta(graph, item: dict) -> dict:
    """Uma pergunta pelo grafo. `ainvoke` (nao `astream_events`) para o LLM
    rodar sem streaming e devolver o `usage`; o caminho vem do callback."""
    from orchestrator.graph import rag_specialist
    from orchestrator.graph.state import fresh_turn_input

    coletor = ColetorGrafo()
    cruas: list[str] = []
    original = rag_specialist.garantir_citacao

    def espiao(resposta, fontes):
        cruas.append(resposta)
        return original(resposta, fontes)

    config = {"configurable": {"thread_id": f"m8-{item['id']}-{uuid.uuid4().hex[:8]}"}, "callbacks": [coletor]}
    rag_specialist.garantir_citacao = espiao
    erro = None
    estado: dict = {}
    try:
        await graph.ainvoke(fresh_turn_input(item["pergunta"]), config=config)
        estado = (await graph.aget_state(config)).values
    except Exception as exc:  # noqa: BLE001 - registra e segue para a proxima pergunta
        erro = f"{type(exc).__name__}: {exc}"
    finally:
        rag_specialist.garantir_citacao = original

    scratchpad = estado.get("internal_scratchpad") or []
    final = estado.get("final_result")
    crua = cruas[-1] if cruas else final
    return {
        "id": item["id"],
        "tipo": item["tipo"],
        "pergunta": item["pergunta"],
        "caminho": coletor.caminho,
        "rag_acionado": "specialist_rag" in coletor.caminho,
        "trechos": extrair_trechos(scratchpad),
        "notas_de_outros_especialistas": [n.splitlines()[0] for n in scratchpad if not n.startswith("[rag]")],
        "resposta_crua": crua,
        "resposta_final": final,
        "resposta_fixa_sem_llm": bool(final) and not cruas,
        "anexo_de_citacao": crua != final,
        "last_error": estado.get("last_error"),
        "erro": erro,
        "erros_llm": coletor.erros_llm,
        "falha_de_infra": bool(erro or coletor.erros_llm),
        "chamadas_llm": coletor.chamadas,
    }


def _custo_das_chamadas(chamadas: list[dict], settings) -> float:
    pedido = {"supervisor": settings.router_model, "synthesize_final": settings.general_model}
    return sum(custo_usd(pedido.get(c.get("no"), c.get("modelo_devolvido") or ""), c.get("token_usage"),
                         c.get("usage_metadata"))
               for c in chamadas)


async def etapa_respostas(perguntas: list[dict], *, orcamento: float = ORCAMENTO_USD, graph_factory=None,
                          responder: Callable = responder_pergunta, log=print) -> dict:
    from langgraph.checkpoint.memory import MemorySaver

    from orchestrator.config import settings
    from orchestrator.graph import builder
    from orchestrator.rag.smoke import neutralizar_efeitos_externos

    neutralizar_efeitos_externos(settings)
    settings.rag_enabled = True  # SO neste processo; o .env continua como esta
    graph = (graph_factory or builder.build_graph)(MemorySaver())

    saida = {
        "versao": 1,
        "missao": 8,
        "data": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git": _git(),
        "config": {
            "router_model": settings.router_model,
            "general_model": settings.general_model,
            "temperatura_supervisor": 0,
            "temperatura_synthesize": None,  # o no nao define: padrao do provedor (rodada = amostra)
            "rag_search_mode": settings.rag_search_mode,
            "rag_top_k": settings.rag_top_k,
            "rag_colecao": settings.rag_colecao,
            "rag_rerank_model": settings.rag_rerank_model,
            "indice_meta": _meta_do_indice(settings),
            "metodo": "graph.ainvoke + callback (sem streaming); MemorySaver; n8n/gateway neutralizados",
            "provedor_devolvido": "o OpenRouter nao expoe o provedor no response_metadata do langchain; ver modelo_devolvido",
        },
        "hashes": _hashes_do_sistema(settings),
        "custo_usd": 0.0,
        "orcamento_usd": orcamento,
        "abortado_por_orcamento": False,
        "perguntas": [],
    }
    for i, item in enumerate(perguntas):
        r = await responder(graph, item)
        if i == 0 and r.get("falha_de_infra"):
            raise FalhaInicial(f"a 1a pergunta ({item['id']}) falhou: erro={r.get('erro')} erros_llm={r.get('erros_llm')}")
        r["custo_usd"] = _custo_das_chamadas(r["chamadas_llm"], settings)
        saida["perguntas"].append(r)
        saida["custo_usd"] += r["custo_usd"]
        log(f"{item['id']}: {' -> '.join(r['caminho']) or '(sem caminho)'}  US$ {r['custo_usd']:.4f}"
            + ("  INFRA " + str(r.get("erro") or r.get("erros_llm")) if r.get("falha_de_infra") else ""))
        if saida["custo_usd"] > orcamento:
            saida["abortado_por_orcamento"] = True
            log(f"ORCAMENTO estourado (US$ {saida['custo_usd']:.4f} > {orcamento:.2f}): interrompido")
            break
    return saida


async def etapa_julgar(respostas: dict, gabarito: list[dict], api_key: str, *, orcamento: float = ORCAMENTO_USD,
                       llm_factory=juiz.criar_llm, log=print, calibracao: dict | None = None) -> dict:
    pf, pc = juiz.prompt_fidelidade(), juiz.prompt_correcao()
    llm_f, llm_c = llm_factory(api_key, pf), llm_factory(api_key, pc)
    por_id = {g["id"]: g for g in gabarito}
    saida = {
        "versao": 1,
        "missao": 8,
        "data": datetime.now().astimezone().isoformat(timespec="seconds"),
        "juiz": {"modelo": juiz.JUIZ_MODELO, "temperatura": juiz.JUIZ_TEMPERATURA,
                 "reasoning_effort": juiz.JUIZ_REASONING_EFFORT, "saida": "json_schema strict"},
        "hashes": {"prompt_fidelidade": pf.hash, "prompt_correcao": pc.hash,
                   "respostas": sha256_texto(json.dumps(respostas, sort_keys=True, ensure_ascii=False))},
        "respostas_data": respostas.get("data"),
        # "calibrada" (caminho pre-registrado) ou "nao_calibrada" (--sem-calibracao, desvio de 20/11).
        "calibracao": calibracao or {"status": "calibrada"},
        "custo_usd": 0.0,
        "orcamento_usd": orcamento,
        "abortado_por_orcamento": False,
        "fidelidade": {},
        "correcao": {},
    }

    async def chamar(llm, mensagens):
        try:
            dados, uso = await juiz.julgar(llm, mensagens)
            erro = None
        except Exception as exc:  # noqa: BLE001 - registra; a metrica fica "pendente"
            dados, uso, erro = None, {}, f"{type(exc).__name__}: {exc}"
        custo = custo_usd(juiz.JUIZ_MODELO, uso.get("token_usage"), uso.get("usage_metadata"))
        saida["custo_usd"] += custo
        return {"juiz": dados, "uso": uso, "custo_usd": custo, "erro": erro}

    primeira = True
    for r in respostas["perguntas"]:
        if r.get("resposta_crua") is None:
            continue
        f = await chamar(llm_f, juiz.montar_fidelidade(pf, r["pergunta"], r["trechos"], r["resposta_crua"]))
        if f["juiz"] is not None:
            f.update(juiz.veredito_fidelidade(f["juiz"]))
        saida["fidelidade"][r["id"]] = f
        c = await chamar(llm_c, juiz.montar_correcao(pc, por_id[r["id"]], r["resposta_crua"]))
        if c["juiz"] is not None:
            c["correta"] = bool(c["juiz"].get("correta"))
        saida["correcao"][r["id"]] = c
        if primeira and (f["erro"] or c["erro"]):
            raise FalhaInicial(f"a 1a chamada do juiz ({r['id']}) falhou: {f['erro'] or c['erro']}")
        primeira = False
        # Sem veredito no log: so progresso e custo (a calibracao humana e cega).
        falhas = [n for n, x in (("fidelidade", f), ("correcao", c)) if x["erro"]]
        log(f"{r['id']}: julgado  US$ {f['custo_usd'] + c['custo_usd']:.4f}"
            + (f"  FALHA do juiz em {', '.join(falhas)}" if falhas else ""))
        if saida["custo_usd"] > orcamento:
            saida["abortado_por_orcamento"] = True
            log(f"ORCAMENTO estourado (US$ {saida['custo_usd']:.4f} > {orcamento:.2f}): interrompido")
            break
    return saida


# --- metricas ---------------------------------------------------------------

def calcular_metricas(respostas: dict, gabarito: list[dict], fatos: dict, julgamento: dict | None = None,
                      formato: dict | None = None) -> dict:
    """Denominadores FIXOS pelo gabarito: pergunta ausente ou fora do rag conta como erro."""
    fmt = formato or carregar_formato()
    por_id = {r["id"]: r for r in respostas["perguntas"]}
    fid = (julgamento or {}).get("fidelidade", {})
    cor = (julgamento or {}).get("correcao", {})
    linhas = []
    for g in gabarito:
        r = por_id.get(g["id"]) or {}
        crua, final = r.get("resposta_crua") or "", r.get("resposta_final") or ""
        rag = bool(r.get("rag_acionado"))
        linha = {"id": g["id"], "tipo": g["tipo"], "respondida": bool(r), "rag_acionado": rag,
                 "caminho": r.get("caminho", []), "infra": bool(r.get("falha_de_infra"))}
        # (g) formato: nao depende do rag; pergunta ausente (crua vazia) erra em tudo.
        linha["formato"] = checar_formato(crua, g["id"], fmt)
        if g["tipo"] in COM_FONTE:
            linha["fatos"] = checar_fatos(crua, fatos[g["id"]])
            linha["citacao_espontanea"] = rag and checar_citacao(crua, g)
            linha["citacao_final"] = rag and checar_citacao(final, g)
        else:
            linha["sem_resposta_det"] = checar_sem_resposta(crua, r.get("trechos", []))
        f, c = fid.get(g["id"]) or {}, cor.get(g["id"]) or {}
        linha["fiel_estrito"] = f.get("fiel_estrito")
        linha["sem_grave"] = f.get("sem_grave")
        linha["correta_juiz"] = c.get("correta")
        linhas.append(linha)

    def conta(chave, filtro=lambda x: True, sub=None):
        alvo = [x for x in linhas if filtro(x)]
        vals = [(x[chave][sub] if sub else x[chave]) for x in alvo]
        if any(v is None for v in vals):
            return {"acertos": sum(1 for v in vals if v), "n": len(alvo), "pendentes": sum(1 for v in vals if v is None)}
        return {"acertos": sum(1 for v in vals if v), "n": len(alvo)}

    def com_fonte(x):
        return x["tipo"] in COM_FONTE

    def sem_resp(x):
        return x["tipo"] == "sem_resposta"
    def formato_total(x):
        f = x["formato"]
        return f["principal_curta"] and f["oferece_detalhes"] and f["sim_nao"] is not False

    for x in linhas:
        x["formato"]["total"] = formato_total(x) if com_fonte(x) else None
    sim_nao_ids = fmt["sim_nao"]
    discord = [x["id"] for x in linhas if sem_resp(x) and x["correta_juiz"] is not None
               and x["correta_juiz"] != x["sem_resposta_det"]["acerto"]]
    return {
        "completo": len(por_id) == len(gabarito) and not respostas.get("abortado_por_orcamento"),
        "a_roteamento": conta("rag_acionado"),
        "a_roteamento_por_tipo": {t: conta("rag_acionado", lambda x, t=t: x["tipo"] == t)
                                  for t in ("direta", "multi_secao", "sem_resposta")},
        "b_fatos": conta("fatos", com_fonte, "acerto"),
        "b_fracao_media": (sum(x["fatos"]["fracao"] for x in linhas if com_fonte(x))
                           / max(1, sum(1 for x in linhas if com_fonte(x)))),
        "c_citacao_espontanea": conta("citacao_espontanea", com_fonte),
        "c_citacao_final": conta("citacao_final", com_fonte),
        "d_fiel_estrito": conta("fiel_estrito"),
        "d_sem_grave": conta("sem_grave"),
        "e_sem_resposta_det": conta("sem_resposta_det", sem_resp, "acerto"),
        "e_sem_resposta_juiz": conta("correta_juiz", sem_resp),
        "e_discordancias": discord,
        "falhas_de_infra": [x["id"] for x in linhas if x["infra"]],
        "f_correcao": conta("correta_juiz", com_fonte),
        "g_sim_nao": conta("formato", lambda x: x["id"] in sim_nao_ids, "sim_nao"),
        "g_principal_curta": conta("formato", com_fonte, "principal_curta"),
        "g_oferece_detalhes": conta("formato", sub="oferece_detalhes"),
        "g_oferece_detalhes_com_fonte": conta("formato", com_fonte, "oferece_detalhes"),
        "g_total": conta("formato", com_fonte, "total"),
        "g_formato": {"versao": 1, "hash": HASH_FORMATO, "sim_nao": sorted(sim_nao_ids),
                      "max_linhas": fmt["max_linhas"], "largura_linha": fmt["largura"]},
        "linhas": linhas,
    }


def _fmt(m: dict) -> str:
    s = f"{m['acertos']}/{m['n']}"
    return s + (f" ({m['pendentes']} pendente(s))" if m.get("pendentes") else "")


def _sim(v) -> str:
    return "—" if v is None else ("sim" if v else "não")


def relatorio_markdown(m: dict, juiz_nao_calibrado: bool = False) -> str:
    nc = " — **NÃO calibrada**" if juiz_nao_calibrado else ""
    gf = m["g_formato"]
    linhas = [
        "| Métrica | Resultado |",
        "|---|---|",
        (
            f"| (a) roteamento: rag acionado | {_fmt(m['a_roteamento'])} "
            f"(direta {_fmt(m['a_roteamento_por_tipo']['direta'])}, multi_secao "
            f"{_fmt(m['a_roteamento_por_tipo']['multi_secao'])}, "
            f"sem_resposta {_fmt(m['a_roteamento_por_tipo']['sem_resposta'])}) |"
        ),
        f"| (b) fatos-chave, tudo ou nada | {_fmt(m['b_fatos'])} (fração média {m['b_fracao_media']:.2f}) |",
        f"| (c) citação espontânea (resposta crua) | {_fmt(m['c_citacao_espontanea'])} |",
        f"| (c) citação final (com anexo, informativa) | {_fmt(m['c_citacao_final'])} |",
        f"| (d) fidelidade estrita (juiz{nc}) | {_fmt(m['d_fiel_estrito'])} |",
        f"| (d) sem afirmação grave (juiz{nc}) | {_fmt(m['d_sem_grave'])} |",
        f"| (e) sem_resposta, determinística | {_fmt(m['e_sem_resposta_det'])} |",
        f"| (e) sem_resposta, juiz (criterio_acerto{nc}) | {_fmt(m['e_sem_resposta_juiz'])}"
        + (f"; discordam: {', '.join(m['e_discordancias'])}" if m["e_discordancias"] else "") + " |",
        f"| (f) correção (juiz vê o gabarito{nc}) | {_fmt(m['f_correcao'])} |",
        f"| (g-a) formato: 1ª linha começa por Sim/Não ({', '.join(gf['sim_nao'])}) | {_fmt(m['g_sim_nao'])} |",
        (
            f"| (g-b) formato: principal ≤ {gf['max_linhas']} linhas de {gf['largura_linha']} caracteres | "
            f"{_fmt(m['g_principal_curta'])} |"
        ),
        (
            f"| (g-c) formato: termina oferecendo detalhes (17 + 3 sem_resposta) | {_fmt(m['g_oferece_detalhes'])} "
            f"(com fonte {_fmt(m['g_oferece_detalhes_com_fonte'])}) |"
        ),
        f"| (g) formato total (todos os critérios aplicáveis) | {_fmt(m['g_total'])} |",
        "",
        "| q | tipo | rag | fatos ausentes | cita (crua/final) | fiel | sem grave | correta | sem_resp det | formato a/b/c (linhas) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for x in m["linhas"]:
        if "fatos" in x:
            fatos = ", ".join(x["fatos"]["ausentes"]) or "—"
            cita = f"{_sim(x['citacao_espontanea'])}/{_sim(x['citacao_final'])}"
            det = "—"
        else:
            fatos, cita = "n/a", "n/a"
            d = x["sem_resposta_det"]
            det = _sim(d["acerto"]) + (f" (números fora: {', '.join(d['numeros_fora_dos_trechos'])})"
                                       if d["numeros_fora_dos_trechos"] else "")
        rag = _sim(x["rag_acionado"]) + (" (infra)" if x["infra"] else "")
        fo = x["formato"]
        formato = (f"{'n/a' if fo['sim_nao'] is None else _sim(fo['sim_nao'])}/{_sim(fo['principal_curta'])}/"
                   f"{_sim(fo['oferece_detalhes'])} ({fo['linhas_principal']})")
        linhas.append(f"| {x['id']} | {x['tipo']} | {rag} | {fatos} | {cita} | "
                      f"{_sim(x['fiel_estrito'])} | {_sim(x['sem_grave'])} | {_sim(x['correta_juiz'])} | {det} | {formato} |")
    if juiz_nao_calibrado:
        linhas.append("\n**Juiz NÃO calibrado** (desvio de 20/11/2026: calibração humana interrompida após 1 de 8 "
                      "itens, por custo de tempo; ver docs/RAG.md). As métricas (d), (e) pelo juiz e (f) não têm "
                      "concordância humana medida.")
    if m["falhas_de_infra"]:
        linhas.append(f"\n**Falha de infraestrutura** (erro de LLM capturado no grafo; conta como erro, sem nova rodada): "
                      f"{', '.join(m['falhas_de_infra'])}.")
    if not m["completo"]:
        linhas.append("\n**Execução INCOMPLETA** (pergunta faltando ou orçamento estourado): as faltantes contam como erro.")
    return "\n".join(linhas)


# --- calibracao humana ------------------------------------------------------

def selecionar_calibracao(m: dict, n: int = N_CALIBRACAO) -> list[str]:
    """Regra pre-registrada, SEM olhar o juiz: q18, q19, q15; a 1a direta que
    errou a (b); a 1a direta que acertou a (b); completa com as proximas por id."""
    escolhidas = list(CALIBRACAO_FIXAS)
    diretas = [x for x in m["linhas"] if x["tipo"] == "direta"]
    for quer in (False, True):
        alvo = next((x["id"] for x in diretas if x["fatos"]["acerto"] is quer and x["id"] not in escolhidas), None)
        if alvo:
            escolhidas.append(alvo)
    for x in m["linhas"]:
        if len(escolhidas) >= n:
            break
        if x["id"] not in escolhidas:
            escolhidas.append(x["id"])
    ordem = [x["id"] for x in m["linhas"]]
    return sorted(escolhidas[:n], key=ordem.index)


_INSTRUCOES_CALIBRACAO = """\
# Calibracao humana da Missao 8 (docs/RAG.md). Preencha SO o bloco `marcacao`
# de cada item, ANTES de abrir o julgamento-*.json (este arquivo nao tem o
# veredito do juiz, de proposito).
#
#   fiel:     sim | nao  -> TODA afirmacao da resposta_crua esta nos trechos?
#             (encaminhamento generico do tipo "consulte o juridico" fora dos
#             trechos tambem conta como NAO fiel; dizer que o manual nao cobre
#             o assunto nao conta como afirmacao). Sem trecho, afirmacao
#             factual = nao fiel.
#   correta:  sim | nao  -> a conclusao bate com o gabarito (o sim/nao e os
#             valores/prazos/codigos essenciais)? Nas sem_resposta, vale o
#             criterio_acerto (e o aceita_tambem).
#   *_justificativa: uma frase.
#
# Depois: python -m orchestrator.rag.avaliar_respostas --concordancia
# Limiar pre-registrado, por dimensao: >= 7/8 aceitavel; <= 6/8 juiz NAO
# confiavel (registrado, sem ajustar o prompt). n=8 e pouco: ruido nos dois casos.
"""


def gerar_calibracao(respostas: dict, gabarito: list[dict], ids: Sequence[str]) -> str:
    por_id = {r["id"]: r for r in respostas["perguntas"]}
    g_id = {g["id"]: g for g in gabarito}
    itens = []
    for qid in ids:
        r, g = por_id[qid], g_id[qid]
        itens.append({
            "id": qid,
            "tipo": g["tipo"],
            "pergunta": g["pergunta"],
            "caminho": " -> ".join(r["caminho"]),
            "trechos": [{"n": t["n"], "fonte": f"{t['pop']}, seção \"{t['secao']}\"", "texto": t["texto"]}
                        for t in r["trechos"]],
            "resposta_crua": r["resposta_crua"],
            "gabarito": {k: g[k] for k in ("resposta_esperada", "criterio_acerto", "aceita_tambem") if g.get(k)},
            "marcacao": {"fiel": None, "fiel_justificativa": "", "correta": None, "correta_justificativa": ""},
        })
    corpo = yaml.safe_dump({"versao": 1, "respostas_data": respostas.get("data"), "itens": itens},
                           allow_unicode=True, sort_keys=False, width=100)
    return _INSTRUCOES_CALIBRACAO + "\n" + corpo


def _booleano(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        t = normalizar(v)
        if t in ("sim", "s", "true"):
            return True
        if t in ("nao", "n", "false"):
            return False
    return None


def calibracao_marcada(path: Path) -> bool:
    """O arquivo existe e TODOS os itens tem fiel e correta (sim/nao)?"""
    if not Path(path).is_file():
        return False
    dados = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    itens = dados.get("itens") or []
    return bool(itens) and all(
        _booleano(i["marcacao"].get("fiel")) is not None and _booleano(i["marcacao"].get("correta")) is not None
        for i in itens
    )


MOTIVO_SEM_CALIBRACAO = ("desvio de 20/11/2026 decidido pelo Max: calibracao humana interrompida apos 1 item "
                         "(q01) por custo de tempo; metricas do juiz NAO calibradas (docs/RAG.md, Missao 8)")


def status_sem_calibracao(path: Path) -> dict:
    """O que o --sem-calibracao grava no julgamento: status, motivo e os itens ja marcados."""
    itens = []
    if Path(path).is_file():
        dados = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        itens = dados.get("itens") or []
    marcados = [i["id"] for i in itens
                if _booleano(i["marcacao"].get("fiel")) is not None and _booleano(i["marcacao"].get("correta")) is not None]
    return {"status": "nao_calibrada", "motivo": MOTIVO_SEM_CALIBRACAO, "itens_marcados": marcados,
            "itens_previstos": len(itens) or N_CALIBRACAO}


def calcular_concordancia(calibracao: dict, julgamento: dict, limiar: int = LIMIAR_CONCORDANCIA) -> dict:
    """Humano x juiz, por dimensao. Recusa marcacao incompleta."""
    faltando = [i["id"] for i in calibracao["itens"]
                if _booleano(i["marcacao"].get("fiel")) is None or _booleano(i["marcacao"].get("correta")) is None]
    if faltando:
        raise ValueError(f"marcacao incompleta (fiel e correta: sim/nao) em: {', '.join(faltando)}")
    resultado = {}
    for dim, humano_chave, juiz_de in (("fidelidade", "fiel", lambda q: julgamento["fidelidade"].get(q, {}).get("fiel_estrito")),
                                       ("correcao", "correta", lambda q: julgamento["correcao"].get(q, {}).get("correta"))):
        itens = []
        for i in calibracao["itens"]:
            h, j = _booleano(i["marcacao"][humano_chave]), juiz_de(i["id"])
            itens.append({"id": i["id"], "humano": h, "juiz": j, "concorda": j is not None and h == j})
        n = len(itens)
        acordos = sum(1 for x in itens if x["concorda"])
        resultado[dim] = {
            "concordancia": acordos, "n": n, "itens": itens,
            "veredito": (f"aceitavel (>= {limiar}/{n}; n={n} e pouco, ruido)" if acordos >= limiar
                         else f"juiz NAO confiavel (<= {limiar - 1}/{n}); registrado, sem ajustar o prompt"),
        }
    return resultado


# --- plano e custo ----------------------------------------------------------

def estimar_custo(perguntas: Sequence[dict], top_k: int, router_model: str, general_model: str) -> dict:
    from orchestrator.graph import nodes, rag_specialist
    from orchestrator.schemas.routing import dispatch_tool

    def tokens(chars: float) -> int:
        return int(chars / CHARS_POR_TOKEN) + 1

    maior = max(len(p["pergunta"]) for p in perguntas)
    sup1 = tokens(len(nodes.supervisor_system_prompt(True)) + len(json.dumps(dispatch_tool(True))) + maior + 200)
    sup2 = sup1 + tokens(400)
    synth = tokens(len(nodes._SYNTHESIZE_SYSTEM_PROMPT) + len(rag_specialist.REGRAS_DO_MANUAL)
                   + top_k * CHARS_POR_TRECHO + maior + 400)
    pf, pc = juiz.prompt_fidelidade(), juiz.prompt_correcao()
    jf = tokens(len(pf.sistema) + len(pf.usuario) + len(json.dumps(pf.schema)) + top_k * CHARS_POR_TRECHO + 2000)
    jc = tokens(len(pc.sistema) + len(pc.usuario) + len(json.dumps(pc.schema)) + 1500 + 2000)
    n = len(perguntas)

    def usd(modelo, ent, sai):
        pe, ps = PRECOS.get(modelo, PRECO_DESCONHECIDO)
        return (ent * pe + sai * ps) / 1_000_000

    resp = n * (usd(router_model, sup1, SAIDA_SUPERVISOR[0]) + usd(router_model, sup2, SAIDA_SUPERVISOR[1])
                + usd(general_model, synth, SAIDA_SYNTH))
    jfid = n * usd(juiz.JUIZ_MODELO, jf, SAIDA_JUIZ_FIDELIDADE)
    jcor = n * usd(juiz.JUIZ_MODELO, jc, SAIDA_JUIZ_CORRECAO)
    return {
        "tokens_por_pergunta": {"supervisor_1": sup1, "supervisor_2": sup2, "synthesize": synth,
                                "juiz_fidelidade": jf, "juiz_correcao": jc},
        "chamadas": {"respostas": 3 * n, "juiz": 2 * n},
        "teto_usd": {"respostas": resp, "juiz_fidelidade": jfid, "juiz_correcao": jcor, "total": resp + jfid + jcor},
    }


def _ultimo(prefixo: str) -> Path | None:
    arquivos = sorted(DIR_SAIDA.glob(f"{prefixo}-*.json"))
    return arquivos[-1] if arquivos else None


def _gravar(path: Path, dados: dict) -> None:
    if path.exists():
        raise FileExistsError(f"{path} ja existe: nao sobrescrevo resultado medido (use --saida)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _aviso_tracing() -> bool:
    return any(os.environ.get(v, "").lower() == "true" for v in ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING"))


def mostrar_plano(settings, perguntas: list[dict]) -> int:
    indice = Path(settings.rag_index_path)
    print("Missao 8 - avaliacao de ponta a ponta (NADA executado; acrescente --executar)")
    print(f"indice   : {indice} ({'ok' if indice.is_file() else 'AUSENTE - rode python -m orchestrator.rag.ingest'})")
    print(f"busca    : modo {settings.rag_search_mode}, top_k {settings.rag_top_k}, colecao {settings.rag_colecao}, "
          f"rerank {settings.rag_rerank_model or 'nao'}")
    print(f"responde : supervisor {settings.router_model} (temperatura 0), resposta {settings.general_model} "
          "(temperatura nao definida no no: cada rodada e uma amostra)")
    print(f"juiz     : {juiz.JUIZ_MODELO}, temperatura {juiz.JUIZ_TEMPERATURA}, reasoning {juiz.JUIZ_REASONING_EFFORT}")
    print("hashes   :")
    for k, v in {**_hashes_do_sistema(settings), "juiz_fidelidade_v1": juiz.HASH_PROMPT_FIDELIDADE,
                 "juiz_correcao_v1": juiz.HASH_PROMPT_CORRECAO}.items():
        print(f"  {k:<20} {v}")
    print(f"perguntas: {len(perguntas)} ({', '.join(p['id'] for p in perguntas)})")
    est = estimar_custo(perguntas, settings.rag_top_k, settings.router_model, settings.general_model)
    t = est["teto_usd"]
    print(f"tokens/pergunta (entrada, teto): {est['tokens_por_pergunta']}")
    print(f"custo TETO: respostas US$ {t['respostas']:.3f} ({est['chamadas']['respostas']} chamadas) + juiz "
          f"US$ {t['juiz_fidelidade'] + t['juiz_correcao']:.3f} ({est['chamadas']['juiz']} chamadas) "
          f"= US$ {t['total']:.3f}; orcamento por etapa US$ {ORCAMENTO_USD:.2f}")
    print(f"saida    : {DIR_SAIDA}/respostas-<data>.json e julgamento-<data>.json")
    if _aviso_tracing():
        print("AVISO    : tracing do LangSmith ligado - perguntas, trechos e respostas vao para o LangSmith")
    if not settings.openrouter_api_key:
        print("AVISO    : ORCHESTRATOR_OPENROUTER_API_KEY ausente (rode de dentro de orchestrator/, com o .env)")
    return 0


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--executar", action="store_true", help="roda a --etapa paga (LLM real no OpenRouter)")
    p.add_argument("--etapa", choices=("respostas", "julgar"), help="etapa paga a executar")
    p.add_argument("--relatorio", action="store_true", help="metricas a partir dos JSONs (gratis)")
    p.add_argument("--calibracao", action="store_true", help="gera o arquivo de marcacao humana (gratis)")
    p.add_argument("--concordancia", action="store_true", help="humano x juiz (gratis)")
    p.add_argument("--respostas", type=Path, help="JSON de respostas (padrao: o mais recente em fixtures/rag/m8)")
    p.add_argument("--julgamento", type=Path, help="JSON do juiz (padrao: o mais recente)")
    p.add_argument("--saida", type=Path, help="arquivo de saida da etapa (padrao: <etapa>-<data>.json)")
    p.add_argument("--orcamento", type=float, default=ORCAMENTO_USD, help="US$ maximo por etapa paga")
    p.add_argument("--sem-calibracao", action="store_true",
                   help="julgar SEM a calibracao humana completa (desvio de 20/11); grava status nao_calibrada")
    a = p.parse_args(argv)
    if a.executar and not a.etapa:
        p.error("--executar exige --etapa respostas|julgar")
    if a.sem_calibracao and not (a.executar and a.etapa == "julgar"):
        p.error("--sem-calibracao so vale com --executar --etapa julgar")
    return a


def main(argv=None) -> int:
    args = parse_args(argv)
    from orchestrator.config import settings

    gabarito = carregar_gabarito()
    fatos = carregar_fatos()
    hoje = datetime.now().astimezone().strftime("%Y-%m-%d")

    if args.relatorio or args.calibracao or args.concordancia:
        caminho_r = args.respostas or _ultimo("respostas")
        if caminho_r is None:
            print("erro: nenhum respostas-*.json em fixtures/rag/m8 (rode --executar --etapa respostas)", file=sys.stderr)
            return 2
        respostas = json.loads(caminho_r.read_text(encoding="utf-8"))
        caminho_j = args.julgamento or _ultimo("julgamento")
        julgamento = json.loads(caminho_j.read_text(encoding="utf-8")) if caminho_j else None
        if args.calibracao:
            m = calcular_metricas(respostas, gabarito, fatos)  # sem o juiz: a selecao nao o ve
            ids = selecionar_calibracao(m)
            destino = args.saida or CALIBRACAO
            if destino.exists():
                print(f"erro: {destino} ja existe (pode ter marcacao sua): nao sobrescrevo", file=sys.stderr)
                return 2
            destino.write_text(gerar_calibracao(respostas, gabarito, ids), encoding="utf-8")
            print(f"calibracao ({', '.join(ids)}) em {destino}")
            return 0
        if args.concordancia:
            if julgamento is None:
                print("erro: nenhum julgamento-*.json", file=sys.stderr)
                return 2
            calib = yaml.safe_load(CALIBRACAO.read_text(encoding="utf-8"))
            try:
                c = calcular_concordancia(calib, julgamento)
            except ValueError as exc:
                print(f"erro: {exc}", file=sys.stderr)
                return 2
            for dim, v in c.items():
                print(f"{dim}: {v['concordancia']}/{v['n']} -> {v['veredito']}")
                for x in v["itens"]:
                    print(f"  {x['id']}: humano={_sim(x['humano'])} juiz={_sim(x['juiz'])}"
                          f"{'' if x['concorda'] else '  <- discorda'}")
            _gravar(args.saida or DIR_SAIDA / f"concordancia-{hoje}.json", c)
            return 0
        nao_calibrado = (julgamento or {}).get("calibracao", {}).get("status") == "nao_calibrada"
        if julgamento is not None and not nao_calibrado and not calibracao_marcada(CALIBRACAO):
            print("calibracao ainda nao marcada: o relatorio omite o juiz (d, e-juiz, f) para nao quebrar a "
                  "calibracao cega")
            julgamento, caminho_j = None, None
        print(f"respostas: {caminho_r.name}; julgamento: {caminho_j.name if caminho_j else '(nenhum: d/e-juiz/f pendentes)'}\n")
        print(relatorio_markdown(calcular_metricas(respostas, gabarito, fatos, julgamento),
                                 juiz_nao_calibrado=nao_calibrado))
        return 0

    if not args.executar:
        return mostrar_plano(settings, gabarito)

    if not settings.openrouter_api_key:
        print("erro: ORCHESTRATOR_OPENROUTER_API_KEY ausente (rode de dentro de orchestrator/, com o .env)", file=sys.stderr)
        return 2
    if _aviso_tracing():
        print("AVISO: tracing do LangSmith ligado - perguntas, trechos e respostas vao para o LangSmith")

    if args.etapa == "respostas":
        if not Path(settings.rag_index_path).is_file():
            print(f"erro: indice ausente em {settings.rag_index_path} (rode python -m orchestrator.rag.ingest)", file=sys.stderr)
            return 2
        destino = args.saida or DIR_SAIDA / f"respostas-{hoje}.json"
        if destino.exists():
            print(f"erro: {destino} ja existe: nao sobrescrevo resultado medido", file=sys.stderr)
            return 2
        try:
            dados = asyncio.run(etapa_respostas(gabarito, orcamento=args.orcamento))
        except FalhaInicial as exc:
            print(f"erro: {exc} - nada gravado", file=sys.stderr)
            return 2
        _gravar(destino, dados)
        print(f"\nUS$ {dados['custo_usd']:.4f} -> {destino}")
        return 1 if dados["abortado_por_orcamento"] else 0

    caminho_r = args.respostas or _ultimo("respostas")
    if caminho_r is None:
        print("erro: rode antes --executar --etapa respostas", file=sys.stderr)
        return 2
    destino = args.saida or DIR_SAIDA / f"julgamento-{hoje}.json"
    if destino.exists():
        print(f"erro: {destino} ja existe: nao sobrescrevo resultado medido", file=sys.stderr)
        return 2
    calibracao = {"status": "calibrada"}
    if args.sem_calibracao:
        calibracao = status_sem_calibracao(CALIBRACAO)
        print(f"AVISO: juiz SEM calibracao humana completa (desvio de 20/11): itens marcados "
              f"{calibracao['itens_marcados'] or 'nenhum'}; o JSON grava status nao_calibrada")
    elif not calibracao_marcada(CALIBRACAO):
        print(f"erro: o juiz so roda depois da calibracao marcada ({CALIBRACAO}); rode --calibracao e marque "
              "as 8 respostas antes (calibracao cega, pre-registro da Missao 8), ou use --sem-calibracao "
              "(desvio registrado em docs/RAG.md)", file=sys.stderr)
        return 2
    respostas = json.loads(caminho_r.read_text(encoding="utf-8"))
    try:
        dados = asyncio.run(etapa_julgar(respostas, gabarito, settings.openrouter_api_key, orcamento=args.orcamento,
                                         calibracao=calibracao))
    except FalhaInicial as exc:
        print(f"erro: {exc} - nada gravado", file=sys.stderr)
        return 2
    _gravar(destino, dados)
    print(f"\nUS$ {dados['custo_usd']:.4f} -> {destino}")
    return 1 if dados["abortado_por_orcamento"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
