"""Ferramenta de limites - Parte 3: o caminho inteiro, v1 x v5 (docs/RAG.md, "Parte 3").

- v1 = o padrao de hoje: regras v1 e ORCHESTRATOR_RAG_LIMITES desligado;
- v5 = regras v5 (v1 + regra 6) com a ficha v3 e a conta ligadas (graph/rag_limites.py).

Tres medicoes, sempre v1 x v5 em ordem intercalada (pre-registradas ANTES de medir):

A) mini-teste do frango: a q02, N = 10 por versao, grafo inteiro, classificacao CEGA
   (arquivo cego + mapa separado, como no mini-teste de 21/11).
B) regressao no gabarito: as 20 perguntas, N = 2 rodadas por versao, juiz v1
   (--sem-calibracao) na resposta final, como na Missao 10.
C) prova lacrada: prova10-v1.yaml, FORA do repo. O sha256 e conferido ANTES de ler;
   as perguntas nunca sao impressas (so posicoes p01..p10 e contagens) e tudo o que as
   contem e gravado fora do repo. N = 2 por versao, classificacao CEGA da conclusao.

    cd orchestrator
    .venv/bin/python -m orchestrator.rag.parte3                                   # plano (gratis)
    .venv/bin/python -m orchestrator.rag.parte3 --teste-conexao                   # PAGO, minimo: 1 chamada
    .venv/bin/python -m orchestrator.rag.parte3 --executar a --orcamento 0.06     # pago
    .venv/bin/python -m orchestrator.rag.parte3 --classificar a                   # gratis
    .venv/bin/python -m orchestrator.rag.parte3 --resultado a                     # gratis
    # B: --executar b --versao v1 --rodada r1 --orcamento 0.06, ... (ordem do plano)
    #    --julgar b --versao v1 --rodada r1 --orcamento 0.12, ...; depois --resultado b
    # C: --executar c --prova <arquivo> --orcamento 0.12; --classificar c --prova <arquivo>;
    #    --resultado c --prova <arquivo>

Falhas (as regras de antes): falha na 1a chamada = falha inicial (nada medido; ate 2);
falha de infra depois = tentativa INVALIDA, repetida UMA vez; 2a invalida encerra a
unidade sem resultado; estouro de orcamento = invalida sem repeticao. Na medicao, erro
do LLM da ficha (que no produto vira NAO VERIFICAVEL) conta como infra.

Emenda de 24/11/2026 (antes de qualquer resultado da A): A, B e C rodam com o motor
DeepSeek direto (llm_motor.py: deepseek-flash, pensamento desligado), forcado SO neste
processo, para a v1 e a v5 igualmente; o juiz da B continua o pre-registrado (OpenRouter).
As tentativas sao contadas POR MOTOR: as do OpenRouter (registradas antes da emenda, sem o
campo `motor_do_agente`) nao gastam as repeticoes nem o teto do motor novo.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import yaml

from orchestrator import llm_motor
from orchestrator.rag import avaliar_respostas as av
from orchestrator.rag import medir_extracao as me
from orchestrator.rag import mini_q02 as mq
from orchestrator.rag import missao9 as m9
from orchestrator.rag import missao10 as m10

VERSOES = ("v1", "v5")
CONFIG_DA_VERSAO = {
    "v1": {"rag_regras_versao": "v1", "rag_limites": False},
    "v5": {"rag_regras_versao": "v5", "rag_limites": True},
}

# --- congelado no pre-registro (docs/RAG.md, "Parte 3"); mudou -> o --executar recusa ---
HASH_REGRAS_V1 = m10.HASH_REGRAS_V1  # 3f4ca553... (Missoes 8-10 e mini-teste)
HASH_REGRAS_V5 = "12f836e2addedd74c8b2fc9848ec0cf72110fe36cf846a0891a2e7f3847f7d34"
HASH_REGRAS = {"v1": HASH_REGRAS_V1, "v5": HASH_REGRAS_V5}
CODIGO_PASSO = av.ORCHESTRATOR_DIR / "src" / "orchestrator" / "graph" / "rag_limites.py"
HASH_CODIGO_PASSO = "be379f946308820451a0c8d721ea699299434eeb1fbe5077d89c36f0611c59f4"
CODIGO_MOTOR = av.ORCHESTRATOR_DIR / "src" / "orchestrator" / "llm_motor.py"
HASH_CODIGO_MOTOR = "cdcba18eac02ed164e5f45402f48c719e3074cfcf2387b86cf4f95859b93e623"
HASH_PROVA10 = "819c0eb716736837c9d78e179aa8058869c48db89cd55879a9b1df5fece6b33f"
N_PROVA10 = 10

REPO_DIR = av.ORCHESTRATOR_DIR.parent
DIR_PARTE3 = av.ORCHESTRATOR_DIR / "fixtures" / "rag" / "parte3"
DIR_A = DIR_PARTE3 / "a"
DIR_B = DIR_PARTE3 / "b"
PROVA_PADRAO = REPO_DIR.parent / "lacre" / "prova10-v1.yaml"
NOME_DIR_C = "parte3-c"  # ao lado do arquivo lacrado, fora do repo

# A
A_PERGUNTA = "q02"
A_N = 10
CLASSES_A = mq.CLASSES_VALIDAS["q02"]  # RECUSA (certo) | ACEITA | AMBIGUA
# B
RODADAS = ("r1", "r2")
ORDEM_B = (("v1", "r1"), ("v5", "r1"), ("v1", "r2"), ("v5", "r2"))
METRICAS_SEM_QUEDA = m10.METRICAS_SEM_QUEDA
QUEDA_MAXIMA = 1.0
SIM_NAO_B = ("q01", "q02", "q04", "q05", "q10")
ALVO_DO_JUIZ = "resposta_final"
# C
C_N = 2
CLASSES_C = ("CERTA", "ERRADA", "PERGUNTA")

# Orcamento: teto por tentativa e teto total da medicao (cobre UMA repeticao).
TETO_TENTATIVA_USD = {"a": 0.06, "b-v1": 0.06, "b-v5": 0.07, "b-juiz": 0.12, "c": 0.12}
TETO_MEDICAO_USD = {"a": 0.12, "b": 1.00, "c": 0.24}

MARCA_FALHA_DO_PASSO = "a verificação da temperatura falhou agora"

# Emenda de 24/11/2026: o motor do agente nas tres medicoes (o .env nao muda).
PROVEDOR_DA_MEDICAO = "deepseek"
PROVEDOR_ANTES_DA_EMENDA = "openrouter"  # tentativas sem o campo `motor_do_agente`


# --- versoes ---------------------------------------------------------------------------


@contextmanager
def com_versao(versao: str):
    """Liga a versao no `settings` (regras + flag) so durante o bloco; restaura depois."""
    from orchestrator.config import settings

    if versao not in CONFIG_DA_VERSAO:
        raise ValueError(f"versao desconhecida: {versao!r} (validas: {', '.join(VERSOES)})")
    antes = {k: getattr(settings, k) for k in CONFIG_DA_VERSAO[versao]}
    for k, v in CONFIG_DA_VERSAO[versao].items():
        setattr(settings, k, v)
    try:
        yield
    finally:
        for k, v in antes.items():
            setattr(settings, k, v)


@contextmanager
def com_motor(provedor: str = PROVEDOR_DA_MEDICAO):
    """Liga o motor da medicao no `settings` so durante o bloco; restaura depois."""
    from orchestrator.config import settings

    if provedor not in llm_motor.PROVEDORES:
        raise ValueError(f"provedor desconhecido: {provedor!r}")
    antes = settings.llm_provedor
    settings.llm_provedor = provedor
    try:
        yield
    finally:
        settings.llm_provedor = antes


def sha256_arquivo(caminho: Path) -> str:
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


def conferir_sistema(settings) -> list[str]:
    """Diferencas entre o sistema e o pre-registrado (vazio = pode medir)."""
    from orchestrator.graph import rag_specialist

    problemas = []
    for v in VERSOES:
        h = av.sha256_texto(rag_specialist.regras_da_etapa1(v))
        if h != HASH_REGRAS[v]:
            problemas.append(f"regras {v}: sha256 {h} != {HASH_REGRAS[v]} (pre-registro)")
    if rag_specialist.usa_formatador("v5"):
        problemas.append("a v5 nao pode ter etapa 2 (formatador)")
    h = sha256_arquivo(CODIGO_PASSO)
    if h != HASH_CODIGO_PASSO:
        problemas.append(f"rag_limites.py: sha256 {h} != {HASH_CODIGO_PASSO} (pre-registro)")
    h = sha256_arquivo(CODIGO_MOTOR)
    if h != HASH_CODIGO_MOTOR:
        problemas.append(f"llm_motor.py: sha256 {h} != {HASH_CODIGO_MOTOR} (emenda de 24/11)")
    cfg = settings.model_copy(update={"llm_provedor": PROVEDOR_DA_MEDICAO})
    try:
        llm_motor.descrever(cfg)
    except llm_motor.MotorIndisponivel as exc:
        problemas.append(f"motor {PROVEDOR_DA_MEDICAO}: {exc}")
    problemas += [f"ficha v3: {p}" for p in me.conferir_pre_registro(settings, versao="v3")]
    return problemas


def _hashes_parte3() -> dict:
    from orchestrator.graph import rag_specialist

    return {
        "regras_v1": av.sha256_texto(rag_specialist.regras_da_etapa1("v1")),
        "regras_v5": av.sha256_texto(rag_specialist.regras_da_etapa1("v5")),
        "codigo_passo": sha256_arquivo(CODIGO_PASSO),
        "codigo_motor": sha256_arquivo(CODIGO_MOTOR),
        "ficha_v3": me.hashes_atuais(me.CONJUNTO, "v3"),
    }


def notas_limite(r: dict) -> list[str]:
    return [n for n in r.get("notas_de_outros_especialistas") or [] if n.startswith("[limite]")]


def falhou_o_passo(r: dict) -> bool:
    return any(MARCA_FALHA_DO_PASSO in n for n in notas_limite(r))


def problemas_da_versao(versao: str, respostas: Sequence[dict], rotulo: str) -> list[str]:
    """Integridade por resposta: a v1 nunca tem nota [limite]; o passo nao falhou."""
    problemas = []
    com_nota = [r["id"] for r in respostas if notas_limite(r)]
    if versao == "v1" and com_nota:
        problemas.append(f"{rotulo}: nota [limite] na v1 ({', '.join(com_nota)})")
    falhas = [r["id"] for r in respostas if falhou_o_passo(r)]
    if falhas:
        problemas.append(f"{rotulo}: o passo de limites falhou ({', '.join(falhas)}): infra")
    infra = [r["id"] for r in respostas if r.get("falha_de_infra")]
    if infra:
        problemas.append(f"{rotulo}: falha de infra ({', '.join(infra)})")
    return problemas


def problemas_do_motor(hashes: dict, respostas: Sequence[dict], rotulo: str) -> list[str]:
    """Emenda de 24/11: o llm_motor.py congelado e TODA resposta com o motor da medicao."""
    problemas = []
    if hashes.get("codigo_motor") != HASH_CODIGO_MOTOR:
        problemas.append(f"{rotulo}: llm_motor.py diferente da emenda de 24/11")
    fora = sorted({r.get("id") for r in respostas if r.get("provedor") != PROVEDOR_DA_MEDICAO})
    if fora:
        problemas.append(f"{rotulo}: resposta sem o motor {PROVEDOR_DA_MEDICAO} ({', '.join(map(str, fora))})")
    return problemas


# --- registro das tentativas (o molde do medir_extracao) ------------------------------


def _agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def motor_da_tentativa(t: dict) -> str:
    return t.get("motor_do_agente", PROVEDOR_ANTES_DA_EMENDA)


def falhas_iniciais_esgotadas(tentativas: Sequence[dict], unidade: str) -> bool:
    """Decisao do Max (24/11): as falhas iniciais NAO recomecam no motor novo. O limite
    (me.MAX_FALHAS_INICIAIS, o mesmo de todas as medicoes) conta as de TODOS os motores;
    a A ja teve 1 no OpenRouter, entao resta 1 no motor novo."""
    n = sum(t["unidade"] == unidade and t["estado"] == me.ESTADO_FALHA_INICIAL for t in tentativas)
    return n >= me.MAX_FALHAS_INICIAIS


def do_motor(tentativas: Sequence[dict], provedor: str = PROVEDOR_DA_MEDICAO) -> list[dict]:
    """So as tentativas feitas com este motor (emenda de 24/11: as repeticoes, as falhas
    iniciais e o teto da medicao contam por motor)."""
    return [t for t in tentativas if motor_da_tentativa(t) == provedor]


def unidades(medicao: str) -> tuple[str, ...]:
    if medicao == "a":
        return ("a",)
    if medicao == "c":
        return ("c",)
    return tuple(f"{v}-{r}" for v, r in ORDEM_B) + tuple(f"juiz-{v}-{r}" for v, r in ORDEM_B)


def concluida(tentativas: Sequence[dict], unidade: str) -> dict | None:
    for t in tentativas:
        if t["unidade"] == unidade and t["estado"] == me.ESTADO_CONCLUIDA:
            return t
    return None


def pode_executar(tentativas: Sequence[dict], medicao: str, unidade: str) -> tuple[bool, str]:
    if unidade not in unidades(medicao):
        return False, f"unidade {unidade!r} fora de {unidades(medicao)}"
    if concluida(tentativas, unidade):
        return False, f"{unidade} ja foi concluida"
    if medicao == "b":
        if unidade.startswith("juiz-"):
            if not concluida(tentativas, unidade.removeprefix("juiz-")):
                return False, f"{unidade}: as respostas {unidade.removeprefix('juiz-')} ainda nao foram concluidas"
        else:
            ordem = [f"{v}-{r}" for v, r in ORDEM_B]
            anteriores = ordem[: ordem.index(unidade)]
            faltando = [u for u in anteriores if not concluida(tentativas, u)]
            if faltando:
                return False, f"{unidade}: a ordem intercalada pede antes {', '.join(faltando)}"
    da_unidade = [t for t in tentativas if t["unidade"] == unidade]
    if any(t["estado"] == me.ESTADO_ORCAMENTO for t in da_unidade):
        return False, f"{unidade} estourou o orcamento: sem repeticao"
    invalidas = [t for t in da_unidade if t["estado"] in (me.ESTADO_INFRA, me.ESTADO_INICIADA)]
    if len(invalidas) > 1:
        return False, f"{unidade} ja foi invalidada {len(invalidas)} vezes: encerrada sem resultado"
    if sum(t["estado"] == me.ESTADO_FALHA_INICIAL for t in da_unidade) >= me.MAX_FALHAS_INICIAIS:
        return False, f"{unidade} ja teve {me.MAX_FALHAS_INICIAIS} falhas iniciais"
    return True, "ok"


def validar_orcamento(orcamento: float, medicao: str, chave_teto: str, tentativas: Sequence[dict]) -> None:
    teto = TETO_TENTATIVA_USD[chave_teto]
    if not 0 < orcamento <= teto:
        raise ValueError(f"--orcamento {orcamento} fora do pre-registrado (0 < orcamento <= {teto:.2f})")
    restante = TETO_MEDICAO_USD[medicao] - me.gasto_registrado(tentativas)
    if orcamento > restante + 1e-12:
        raise ValueError(f"--orcamento {orcamento} acima do que resta do teto da medicao (US$ {restante:.4f})")


def _iniciar(diretorio: Path, unidade: str, orcamento: float,
             motor: str = PROVEDOR_DA_MEDICAO) -> tuple[list[dict], dict]:
    tentativas = me.ler_registro(diretorio)
    n = 1 + sum(t["unidade"] == unidade and t["estado"] != me.ESTADO_FALHA_INICIAL for t in tentativas)
    t = {"unidade": unidade, "n": n, "estado": me.ESTADO_INICIADA, "arquivo": None,
         "orcamento_usd": orcamento, "custo_usd": None, "inicio": _agora(), "fim": None,
         "motor_do_agente": motor}
    tentativas.append(t)
    me.gravar_registro(tentativas, diretorio)
    return tentativas, t


def _fechar(diretorio: Path, tentativas: list[dict], t: dict, estado: str, custo: float,
            arquivo: str | None = None, erro_tipo: str | None = None) -> None:
    t.update({"estado": estado, "custo_usd": custo, "arquivo": arquivo, "fim": _agora()})
    if erro_tipo:
        t["erro_tipo"] = erro_tipo
    me.gravar_registro(tentativas, diretorio)


# --- coleta (A e C): grafo inteiro, ordem intercalada ----------------------------------


class FalhaInicial(av.FalhaInicial):
    def __init__(self, tipo: str):
        super().__init__(f"a 1a chamada falhou ({tipo}): nada medido")
        self.erro_tipo = tipo


def _config_da_coleta(settings) -> dict:
    return {
        "router_model": settings.router_model,
        "general_model": settings.general_model,
        "rag_search_mode": settings.rag_search_mode,
        "rag_top_k": settings.rag_top_k,
        "rag_colecao": settings.rag_colecao,
        "rag_rerank_model": settings.rag_rerank_model,
        "indice_meta": av._meta_do_indice(settings),
        "motor": llm_motor.descrever(settings),
        "metodo": "graph.ainvoke + callback (sem streaming); MemorySaver; n8n/gateway neutralizados; sem juiz",
    }


async def coletar(
    passos: Sequence[dict],
    itens: dict[str, dict],
    *,
    orcamento: float,
    experimento: str,
    graph_factory=None,
    responder: Callable | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """Roda os passos (cada um: indice_execucao, id, versao, amostra) pelo grafo. O log
    traz so posicao, versao, custo e o TIPO de erro: nunca pergunta nem resposta."""
    from langgraph.checkpoint.memory import MemorySaver

    from orchestrator.config import settings
    from orchestrator.graph import builder, rag_specialist
    from orchestrator.rag.smoke import neutralizar_efeitos_externos

    responder = responder or av.responder_pergunta
    externos = ("n8n_url", "n8n_api_key", "openclaw_gateway_url", "openclaw_gateway_token", "rag_enabled")
    antes = {k: getattr(settings, k) for k in externos}
    neutralizar_efeitos_externos(settings)
    settings.rag_enabled = True
    try:
        graph = (graph_factory or builder.build_graph)(MemorySaver())
        saida = {
            "versao": 1,
            "experimento": experimento,
            "data": _agora(),
            "git": av._git(),
            "config": {**_config_da_coleta(settings), "versoes": dict(CONFIG_DA_VERSAO)},
            "hashes": _hashes_parte3(),
            "custo_usd": 0.0,
            "custo_por_versao_usd": {v: 0.0 for v in VERSOES},
            "orcamento_usd": orcamento,
            "abortado_por_orcamento": False,
            "abortado_por_infra": None,
            "respostas": [],
        }
        total = len(passos)
        for passo in passos:
            idx, qid, v = passo["indice_execucao"], passo["id"], passo["versao"]
            with com_versao(v):
                t0 = time.monotonic()
                try:
                    r = await responder(graph, itens[qid])
                except Exception as exc:  # noqa: BLE001 - escapou do responder: infra
                    r = {"id": qid, "erro": f"{type(exc).__name__}: escapou do responder",
                         "erros_llm": [], "falha_de_infra": True, "chamadas_llm": []}
                duracao = time.monotonic() - t0
                regras = av.sha256_texto(rag_specialist.regras_da_etapa1())
                limites_ligado = settings.rag_limites
            infra = bool(r.get("falha_de_infra")) or falhou_o_passo(r)
            tipo = mq._tipo_do_erro(r) if r.get("falha_de_infra") else ("passo_de_limites" if infra else None)
            if idx == 1 and infra:
                raise FalhaInicial(tipo)
            custo = av._custo_das_chamadas(r.get("chamadas_llm", []), settings)
            registro = {**r, **passo, "regras_sha256": regras, "rag_limites": limites_ligado,
                        "provedor": llm_motor.provedor(settings),
                        "modelo_efetivo": llm_motor.modelo_efetivo(settings, settings.general_model),
                        "notas_limite": notas_limite(r), "custo_usd": custo, "tempo_total_s": duracao}
            saida["respostas"].append(registro)
            saida["custo_usd"] += custo
            saida["custo_por_versao_usd"][v] += custo
            log(f"[{idx:02d}/{total:02d}] {qid} a{passo['amostra']:02d} {v}: US$ {custo:.4f}  {duracao:.1f}s"
                + (f"  INFRA ({tipo})" if infra else ""))
            if infra:
                saida["abortado_por_infra"] = {"indice_execucao": idx, "id": qid, "versao": v, "erro_tipo": tipo}
                log("COLETA PARADA por falha de infra (tentativa INVALIDA; pode ser repetida uma vez)")
                break
            if saida["custo_usd"] > orcamento:
                saida["abortado_por_orcamento"] = True
                log(f"ORCAMENTO estourado (US$ {saida['custo_usd']:.4f} > {orcamento:.2f}): interrompido")
                break
        return saida
    finally:
        for k, v in antes.items():
            setattr(settings, k, v)


def passos_a() -> list[dict]:
    return mq.sequencia_execucao((A_PERGUNTA,), VERSOES, A_N)


def passos_c(n_perguntas: int = N_PROVA10) -> list[dict]:
    """Rodada 1 inteira, depois a 2; em cada pergunta, v1 e depois v5."""
    seq, idx = [], 0
    for amostra in range(1, C_N + 1):
        for pos in range(1, n_perguntas + 1):
            for v in VERSOES:
                idx += 1
                seq.append({"indice_execucao": idx, "amostra": amostra, "id": f"p{pos:02d}", "versao": v})
    return seq


def estado_da_coleta(saida: dict) -> str:
    if saida["abortado_por_infra"]:
        return me.ESTADO_INFRA
    if saida["abortado_por_orcamento"]:
        return me.ESTADO_ORCAMENTO
    return me.ESTADO_CONCLUIDA


# --- C: o arquivo lacrado ---------------------------------------------------------------


class ProvaRecusada(ValueError):
    """Mensagem sempre sem conteudo do arquivo (so tipo, posicoes e contagens)."""


def carregar_prova(caminho: Path, hash_esperado: str | None = None) -> list[dict]:
    """Confere o sha256 dos BYTES antes de interpretar qualquer coisa. Devolve os itens
    (dicts com `pergunta` str). Nunca imprime nem poe conteudo em mensagem de erro."""
    hash_esperado = hash_esperado or HASH_PROVA10
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ProvaRecusada("arquivo da prova nao encontrado")
    bruto = caminho.read_bytes()
    if hashlib.sha256(bruto).hexdigest() != hash_esperado:
        raise ProvaRecusada("sha256 da prova difere do pre-registrado: recusado, nada lido")
    try:
        dados = yaml.safe_load(bruto.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - a mensagem do yaml traz o trecho da linha
        raise ProvaRecusada(f"a prova nao e YAML legivel ({type(exc).__name__})") from None
    if isinstance(dados, dict):
        listas = [v for v in dados.values() if isinstance(v, list)]
        if len(listas) != 1:
            raise ProvaRecusada(f"formato inesperado: {len(listas)} listas no topo (esperada 1)")
        dados = listas[0]
    if not isinstance(dados, list):
        raise ProvaRecusada(f"formato inesperado: topo e {type(dados).__name__}")
    ruins = [i for i, it in enumerate(dados, 1)
             if not isinstance(it, dict) or not isinstance(it.get("pergunta"), str) or not it["pergunta"].strip()]
    if ruins:
        raise ProvaRecusada(f"formato inesperado: sem `pergunta` texto nas posicoes {ruins}")
    if len(dados) != N_PROVA10:
        raise ProvaRecusada(f"a prova tem {len(dados)} itens (esperados {N_PROVA10})")
    return dados


def itens_da_prova(prova: Sequence[dict]) -> dict[str, dict]:
    return {f"p{i:02d}": {"id": f"p{i:02d}", "tipo": "prova10", "pergunta": it["pergunta"]}
            for i, it in enumerate(prova, 1)}


def perguntas_de_temperatura(prova: Sequence[dict]) -> list[str]:
    """Pre-registrado: "pergunta de temperatura" e decidido SO pelo codigo
    (`rag_limites.tem_temperatura`), nunca pelo modelo nem pelo gabarito."""
    from orchestrator.graph import rag_limites

    return [f"p{i:02d}" for i, it in enumerate(prova, 1) if rag_limites.tem_temperatura(it["pergunta"])]


def diretorio_c(prova: Path, saida: Path | None = None) -> Path:
    d = Path(saida) if saida is not None else Path(prova).parent / NOME_DIR_C
    d = d.resolve()
    if d == REPO_DIR.resolve() or REPO_DIR.resolve() in d.parents:
        raise ProvaRecusada("a saida da C nao pode ficar dentro do repositorio (as perguntas iriam junto)")
    return d


# --- classificacao cega (A e C) ---------------------------------------------------------

CABECALHO_A = """\
# Classificacao CEGA da Parte 3 - medicao A (q02, frango congelado a -10 graus).
# Preencha `classe` em TODOS os itens: RECUSA (certo) | ACEITA (errado) | AMBÍGUA
# (nao conclui ou conclui as duas coisas; pedir mais informacao em vez de recusar
# tambem e AMBÍGUA). Quem classifica recebe SO este arquivo, sem o mapa.
"""
CABECALHO_C = """\
# Classificacao CEGA da Parte 3 - medicao C (prova lacrada). NAO colar em outro lugar.
# Para cada item, compare a CONCLUSAO da resposta com o `gabarito` e preencha `classe`:
#   CERTA    - conclui o que o gabarito conclui;
#   ERRADA   - conclui o contrario (ou outra coisa);
#   PERGUNTA - nao conclui: pede a informacao que falta ou diz que nao consegue verificar.
# Em `observacao`, NAO copie a pergunta nem a resposta (no maximo o motivo da classe).
# Quem classifica recebe SO este arquivo, sem o mapa.
"""


def gerar_cego(respostas: list[dict], cabecalho: str, gabarito: dict[str, dict] | None = None) -> tuple[str, dict]:
    """O embaralhamento e o elo do mini-teste (secrets); so o cabecalho muda e, na C,
    cada item leva o `gabarito` da prova (o item sem a pergunta)."""
    yaml_cego, mapa = mq.gerar_classificacao_cega({"respostas": respostas})
    if not yaml_cego.startswith(mq._INSTRUCOES_CEGAS):
        raise ValueError("o cabecalho do mini-teste mudou")
    dados = yaml.safe_load(yaml_cego[len(mq._INSTRUCOES_CEGAS):])
    if gabarito is not None:
        for it in dados["itens"]:
            it["gabarito"] = gabarito[it["pergunta_id"]]
    corpo = yaml.safe_dump(dados, allow_unicode=True, sort_keys=False, width=100)
    return cabecalho + "\n" + corpo, mapa


def normalizar_classe_c(valor) -> str | None:
    if not isinstance(valor, str):
        return None
    t = av.normalizar(valor)
    if t in ("certa", "errada"):
        return t.upper()
    if t.startswith(("pergunta", "nao verifica")):
        return "PERGUNTA"
    return None


def validar_classes(classificacao: dict, mapa_dados: dict, normalizar: Callable[[str, object], str | None]) -> dict:
    """codigo -> classe. Recusa elo divergente, codigo faltando/sobrando, pergunta trocada,
    classe pendente ou invalida."""
    if not classificacao.get("elo") or classificacao.get("elo") != mapa_dados.get("elo"):
        raise ValueError("elo ausente ou diferente entre a classificacao e o mapa")
    mapa = mapa_dados.get("mapa") or {}
    por_codigo = {it.get("codigo"): it for it in classificacao.get("itens") or []}
    if set(por_codigo) != set(mapa) or len(por_codigo) != len(classificacao.get("itens") or []):
        raise ValueError("os codigos da classificacao nao batem com o mapa")
    classes, pendentes, invalidas = {}, [], []
    for cod, m in mapa.items():
        it = por_codigo[cod]
        if it.get("pergunta_id") != m["pergunta_id"]:
            raise ValueError(f"{cod}: pergunta_id difere do mapa")
        if it.get("classe") in (None, ""):
            pendentes.append(cod)
            continue
        c = normalizar(m["pergunta_id"], it["classe"])
        if c is None:
            invalidas.append(cod)
        else:
            classes[cod] = c
    if pendentes:
        raise ValueError(f"classificacao incompleta ({len(pendentes)} pendente(s))")
    if invalidas:
        raise ValueError(f"classe invalida em: {', '.join(sorted(invalidas))}")
    return classes


def _sha_das_respostas(respostas: list[dict]) -> str:
    return av.sha256_texto(json.dumps({"respostas": respostas}, sort_keys=True, ensure_ascii=False))


def _integridade_da_coleta(dados: dict, mapa: dict, n_por_versao: int, indice_meta_m8) -> list[str]:
    problemas = []
    if mapa.get("respostas_sha256") != _sha_das_respostas(dados["respostas"]):
        problemas.append("o mapa nao e destas respostas")
    if dados.get("abortado_por_infra") or dados.get("abortado_por_orcamento"):
        problemas.append("coleta abortada")
    for v in VERSOES:
        rs = [r for r in dados["respostas"] if r["versao"] == v]
        if len(rs) != n_por_versao:
            problemas.append(f"{v}: {len(rs)} respostas (esperadas {n_por_versao})")
        problemas += problemas_da_versao(v, rs, v)
        errados = [r["id"] for r in rs if r.get("regras_sha256") != HASH_REGRAS[v]]
        if errados:
            problemas.append(f"{v}: regras diferentes do pre-registro ({', '.join(errados)})")
        flag = [r["id"] for r in rs if r.get("rag_limites") is not CONFIG_DA_VERSAO[v]["rag_limites"]]
        if flag:
            problemas.append(f"{v}: ORCHESTRATOR_RAG_LIMITES errado ({', '.join(flag)})")
    h = dados.get("hashes") or {}
    if (h.get("codigo_passo"), h.get("regras_v5")) != (HASH_CODIGO_PASSO, HASH_REGRAS_V5):
        problemas.append("codigo do passo ou regras v5 diferentes do pre-registro")
    if (h.get("ficha_v3") or {}) != me._pre_registro("v3"):
        problemas.append("ficha v3 diferente da Parte 2.2")
    problemas += problemas_do_motor(h, dados["respostas"], "coleta")
    if indice_meta_m8 is not None and (dados.get("config") or {}).get("indice_meta") != indice_meta_m8:
        problemas.append("indice diferente do da Missao 8 (indice_meta)")
    return problemas


def resultado_a(dados: dict, classificacao: dict, mapa: dict, indice_meta_m8=None) -> dict:
    classes = validar_classes(classificacao, mapa, mq.normalizar_classe)
    problemas = _integridade_da_coleta(dados, mapa, A_N, indice_meta_m8)
    por_versao = {v: {"RECUSA": 0, "ACEITA": 0, "AMBÍGUA": 0, "fora_do_rag": 0} for v in VERSOES}
    por_chave = {(r["versao"], r["indice_execucao"]): r for r in dados["respostas"]}
    for cod, m in mapa["mapa"].items():
        r = por_chave[(m["versao"], m["indice_execucao"])]
        por_versao[m["versao"]][classes[cod]] += 1
        if not r.get("rag_acionado"):
            por_versao[m["versao"]]["fora_do_rag"] += 1
    erros = {v: x["ACEITA"] + x["AMBÍGUA"] + x["fora_do_rag"] for v, x in por_versao.items()}
    nota_recusar = sum(1 for r in dados["respostas"] if r["versao"] == "v5"
                       and any(n.startswith("[limite] RECUSAR:") for n in r["notas_limite"]))
    return {"valido": not problemas, "problemas": problemas, "por_versao": por_versao, "erros": erros,
            "v5_com_nota_recusar": nota_recusar, "passa": not problemas and erros["v5"] == 0,
            "custo_usd": dados.get("custo_usd", 0.0)}


def resultado_c(dados: dict, classificacao: dict, mapa: dict, temperatura: Sequence[str], indice_meta_m8=None) -> dict:
    classes = validar_classes(classificacao, mapa, lambda _qid, valor: normalizar_classe_c(valor))
    problemas = _integridade_da_coleta(dados, mapa, N_PROVA10 * C_N, indice_meta_m8)
    conta = {v: {g: dict.fromkeys(CLASSES_C, 0) for g in ("temperatura", "demais")} for v in VERSOES}
    erradas = {v: {"temperatura": [], "demais": []} for v in VERSOES}
    for cod, m in mapa["mapa"].items():
        grupo = "temperatura" if m["pergunta_id"] in temperatura else "demais"
        conta[m["versao"]][grupo][classes[cod]] += 1
        if classes[cod] == "ERRADA":
            erradas[m["versao"]][grupo].append(f"{m['pergunta_id']}/a{m['amostra']}")
    c1 = conta["v5"]["temperatura"]["ERRADA"] == 0
    c2 = conta["v5"]["demais"]["ERRADA"] <= conta["v1"]["demais"]["ERRADA"]
    return {"valido": not problemas, "problemas": problemas, "n_temperatura": len(temperatura),
            "conta": conta, "erradas": erradas,
            "criterios": {"temperatura_zero_erradas_v5": c1, "demais_v5_nao_erra_mais": c2},
            "passa": not problemas and c1 and c2, "custo_usd": dados.get("custo_usd", 0.0)}


# --- B: regressao no gabarito (o molde da Missao 10) -------------------------------------


def comparar_b(rodadas: dict, gabarito: list[dict], fatos: dict, fmt: dict, indice_meta_m8=None) -> dict:
    """`rodadas[(versao, rodada)] = (respostas, julgamento)`. Criterios b) e c) da Missao 10."""
    faltando = [f"{v}-{r}" for v, r in ORDEM_B if (v, r) not in rodadas]
    if faltando:
        raise ValueError(f"rodadas faltando: {', '.join(faltando)}")
    problemas = []
    if set(fmt.get("sim_nao") or ()) != set(SIM_NAO_B):
        problemas.append(f"perguntas de Sim/Nao do formato_v1.yaml mudaram: {fmt.get('sim_nao')}")
    indices = set()
    for (v, r), (resp, julg) in rodadas.items():
        nome = f"{v}-{r}"
        problemas += m9._checar_integridade(v, r, resp, julg, HASH_REGRAS)
        p3 = resp.get("parte3") or {}
        if p3.get("rag_limites") is not CONFIG_DA_VERSAO[v]["rag_limites"]:
            problemas.append(f"{nome}: ORCHESTRATOR_RAG_LIMITES errado ({p3.get('rag_limites')!r})")
        h = p3.get("hashes") or {}
        if (h.get("codigo_passo"), h.get("regras_v5"), h.get("ficha_v3")) != (
                HASH_CODIGO_PASSO, HASH_REGRAS_V5, me._pre_registro("v3")):
            problemas.append(f"{nome}: codigo do passo, regras v5 ou ficha v3 diferentes do pre-registro")
        problemas += problemas_do_motor(h, resp.get("perguntas", []), nome)
        problemas += problemas_da_versao(v, resp.get("perguntas", []), nome)
        if julg.get("alvo") != ALVO_DO_JUIZ:
            problemas.append(f"{nome}: juiz julgou {julg.get('alvo')!r}, nao {ALVO_DO_JUIZ!r}")
        if resp.get("abortado_por_orcamento") or julg.get("abortado_por_orcamento"):
            problemas.append(f"{nome}: abortada por orcamento")
        indices.add(json.dumps((resp.get("config") or {}).get("indice_meta"), sort_keys=True))
    if len(indices) != 1 or (indice_meta_m8 is not None and indices != {json.dumps(indice_meta_m8, sort_keys=True)}):
        problemas.append("indice diferente entre as rodadas ou em relacao a Missao 8 (indice_meta)")

    esperado = m9.esperado_sim_nao(gabarito, SIM_NAO_B)
    por_rodada = {}
    for (v, r), (resp, julg) in rodadas.items():
        m = av.calcular_metricas(resp, gabarito, fatos, julg, fmt)
        viol, fixas = m9.violacoes_sim_nao(resp, esperado)
        pendentes = {k: m[k].get("pendentes", 0) for k in METRICAS_SEM_QUEDA}
        if any(pendentes.values()):
            problemas.append(f"{v}-{r}: juiz com pendencia {pendentes}")
        por_rodada[f"{v}-{r}"] = {**{k: m[k]["acertos"] for k in METRICAS_SEM_QUEDA},
                                  "n": {k: m[k]["n"] for k in METRICAS_SEM_QUEDA},
                                  "violacoes_sim_nao": viol, "fixas_fora_do_c": fixas,
                                  "custo_respostas_usd": resp.get("custo_usd", 0.0),
                                  "custo_juiz_usd": julg.get("custo_usd", 0.0),
                                  "com_nota_limite": [x["id"] for x in resp.get("perguntas", []) if notas_limite(x)]}
    medias = {v: {k: sum(por_rodada[f"{v}-{r}"][k] for r in RODADAS) / len(RODADAS) for k in METRICAS_SEM_QUEDA}
              for v in VERSOES}
    b = {k: medias["v1"][k] - medias["v5"][k] <= QUEDA_MAXIMA for k in METRICAS_SEM_QUEDA}
    viol_v5 = [{**x, "rodada": r} for r in RODADAS for x in por_rodada[f"v5-{r}"]["violacoes_sim_nao"]]
    return {"valido": not problemas, "problemas": problemas, "por_rodada": por_rodada, "medias": medias,
            "criterios": {"b_sem_queda": b, "c_sem_sim_nao_contraditorio_v5": not viol_v5},
            "violacoes_v5": viol_v5, "passa": not problemas and all(b.values()) and not viol_v5,
            "custo_total_usd": sum(x["custo_respostas_usd"] + x["custo_juiz_usd"] for x in por_rodada.values())}


def carregar_b(diretorio: Path = DIR_B) -> dict:
    tentativas = me.ler_registro(diretorio)
    rodadas = {}
    for v, r in ORDEM_B:
        tr, tj = concluida(tentativas, f"{v}-{r}"), concluida(tentativas, f"juiz-{v}-{r}")
        if tr and tj:
            rodadas[(v, r)] = tuple(json.loads((diretorio / t["arquivo"]).read_text(encoding="utf-8"))
                                    for t in (tr, tj))
    return rodadas


# --- trava da ordem A -> B -> C (emenda de 24/11/2026, antes de qualquer medicao) --------
# A prova lacrada roda UMA vez: a B so roda com a A aprovada e a C so com a A e a B
# aprovadas. Uma reprovacao bloqueia o que vem depois (a prova continua intacta).

# "2.3" = a revalidacao da ficha v3 no deepseek-flash (medir_extracao --versao v3-flash),
# decisao do Max de 24/11: a A so roda com ela aprovada.
PRE_REQUISITOS = {"a": ("2.3",), "b": ("a",), "c": ("a", "b")}
NOME_RESULTADO = "resultado.json"


def _entradas_a(diretorio: Path) -> tuple[dict, dict, dict]:
    t = concluida(me.ler_registro(diretorio), "a")
    if t is None:
        raise FileNotFoundError("a coleta A nao foi concluida")
    dados = json.loads((diretorio / t["arquivo"]).read_text(encoding="utf-8"))
    classificacao = yaml.safe_load((diretorio / "classificacao-cega.yaml").read_text(encoding="utf-8"))
    mapa = json.loads((diretorio / "mapa-cego.json").read_text(encoding="utf-8"))
    return dados, classificacao, mapa


def calcular_resultado(medicao: str) -> dict:
    """O resultado de A ou B recalculado das entradas (levanta se faltar alguma)."""
    if medicao == "a":
        return resultado_a(*_entradas_a(DIR_A), m9.indice_meta_m8())
    return comparar_b(carregar_b(DIR_B), av.carregar_gabarito(), av.carregar_fatos(), av.carregar_formato(),
                      m9.indice_meta_m8())


def gravar_resultado(medicao: str, res: dict) -> None:
    d = DIR_A if medicao == "a" else DIR_B
    d.mkdir(parents=True, exist_ok=True)
    (d / NOME_RESULTADO).write_text(json.dumps(
        {"medicao": medicao, "passa": res["passa"], "valido": res["valido"], "data": _agora()},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def veredito(medicao: str) -> tuple[bool | None, str]:
    """(passa, descricao) de A ou B. None = ainda sem resultado. Exige o resultado.json do
    --resultado E recalcula das entradas: um resultado.json editado ou velho nao libera nada."""
    if medicao == "2.3":
        return me.veredito_v3_flash()
    nome = medicao.upper()
    arquivo = (DIR_A if medicao == "a" else DIR_B) / NOME_RESULTADO
    if not arquivo.is_file():
        return None, f"falta o --resultado {medicao}"
    try:
        gravado = json.loads(arquivo.read_text(encoding="utf-8"))
        res = calcular_resultado(medicao)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, f"as entradas de {nome} nao fecham ({type(exc).__name__}): rode o --resultado {medicao} de novo"
    if gravado.get("passa") is not res["passa"]:
        return None, f"o resultado.json de {nome} nao bate com as entradas: rode o --resultado {medicao} de novo"
    return res["passa"], f"{nome} {'PASSA' if res['passa'] else 'NAO PASSA'}"


def trava_da_ordem(medicao: str, veredito_de: Callable[[str], tuple[bool | None, str]] | None = None) -> str | None:
    """None = pode rodar; senao, o motivo (qual medicao falta ou reprovou)."""
    veredito_de = veredito_de or veredito
    for anterior in PRE_REQUISITOS[medicao]:
        passa, descricao = veredito_de(anterior)
        if anterior == "2.3":
            if passa is None:
                return f"a A so roda depois da Parte 2.3 (a ficha v3 no deepseek-flash) aprovada ({descricao})"
            if not passa:
                return f"Parte 2.3 reprovou ({descricao}). A A fica bloqueada: o Max decide o proximo passo."
            continue
        if passa is None:
            return (f"a ordem e A -> B -> C: a {medicao.upper()} so roda depois de {anterior.upper()} aprovada "
                    f"({descricao})")
        if not passa:
            fim = (" A C fica bloqueada e a prova lacrada continua intacta para uma proxima versao."
                   if medicao == "c" else f" A {medicao.upper()} fica bloqueada.")
            return f"{anterior.upper()} reprovou ({descricao}).{fim}"
    return None


# --- relatorios -------------------------------------------------------------------------


def relatorio_a(res: dict) -> str:
    linhas = ["| Versão | RECUSA (certo) | ACEITA | AMBÍGUA | fora do RAG | erros |", "|---|---|---|---|---|---|"]
    for v in VERSOES:
        x = res["por_versao"][v]
        linhas.append(f"| {v} | {x['RECUSA']} | {x['ACEITA']} | {x['AMBÍGUA']} | {x['fora_do_rag']} | "
                      f"{res['erros'][v]}/{A_N} |")
    linhas += ["", f"- A) erros da v5 = 0 em {A_N}: {'sim' if res['erros']['v5'] == 0 else 'NÃO'}",
               f"- diagnóstico (não decide): respostas v5 com nota [limite] RECUSAR: {res['v5_com_nota_recusar']}/{A_N}"]
    if res["problemas"]:
        linhas.append("\n**Coleta INVÁLIDA**: " + "; ".join(res["problemas"]))
    linhas.append(f"\n**A {'PASSA' if res['passa'] else 'NÃO PASSA'}.** Custo da coleta: US$ {res['custo_usd']:.4f}.")
    return "\n".join(linhas)


def relatorio_b(c: dict) -> str:
    pr = c["por_rodada"]
    linhas = ["| Métrica | " + " | ".join(f"{v}-{r}" for v, r in ORDEM_B) + " | média v1 | média v5 |",
              "|---" * (len(ORDEM_B) + 3) + "|"]
    for k in METRICAS_SEM_QUEDA:
        linhas.append(f"| {m10.NOMES[k]} (n={pr['v1-r1']['n'][k]}) | "
                      + " | ".join(str(pr[f"{v}-{r}"][k]) for v, r in ORDEM_B)
                      + f" | {c['medias']['v1'][k]:.1f} | {c['medias']['v5'][k]:.1f} |")
    cr = c["criterios"]
    linhas += ["", "- B) queda ≤ 1,0: " + ", ".join(f"{m10.NOMES[k]} {'ok' if ok else 'CAIU'}"
                                                  for k, ok in cr["b_sem_queda"].items()),
               "- B) zero Sim/Não contraditório na v5 (q01, q02, q04, q05, q10): "
               + ("sim" if cr["c_sem_sim_nao_contraditorio_v5"] else "NÃO ("
                  + ", ".join("{id} {rodada}: veio {veio}, esperado {esperado}".format(**x) for x in c["violacoes_v5"])
                  + ")")]
    for nome, x in pr.items():
        if x["com_nota_limite"] or x["fixas_fora_do_c"]:
            linhas.append(f"- {nome}: nota [limite] em {', '.join(x['com_nota_limite']) or '—'}; "
                          f"resposta fixa fora do c): {', '.join(x['fixas_fora_do_c']) or '—'}")
    if c["problemas"]:
        linhas.append("\n**Comparação INVÁLIDA**: " + "; ".join(c["problemas"]))
    linhas.append(f"\n**B {'PASSA' if c['passa'] else 'NÃO PASSA'}.** Custo total medido: US$ {c['custo_total_usd']:.4f}.")
    return "\n".join(linhas)


def relatorio_c(res: dict) -> str:
    """So contagens e posicoes (p01..p10): nenhuma pergunta."""
    linhas = [f"Perguntas de temperatura (pelo código): {res['n_temperatura']} de {N_PROVA10}", "",
              "| Versão | Grupo | CERTA | ERRADA | PERGUNTA |", "|---|---|---|---|---|"]
    for v in VERSOES:
        for g in ("temperatura", "demais"):
            x = res["conta"][v][g]
            linhas.append(f"| {v} | {g} | {x['CERTA']} | {x['ERRADA']} | {x['PERGUNTA']} |")
    cr = res["criterios"]
    linhas += ["", f"- C) temperatura, zero ERRADA na v5: {'sim' if cr['temperatura_zero_erradas_v5'] else 'NÃO'}"
               + (f" ({', '.join(res['erradas']['v5']['temperatura'])})" if res["erradas"]["v5"]["temperatura"] else ""),
               f"- C) demais, ERRADA v5 ≤ v1: {'sim' if cr['demais_v5_nao_erra_mais'] else 'NÃO'}"]
    if res["problemas"]:
        linhas.append("\n**Coleta INVÁLIDA**: " + "; ".join(res["problemas"]))
    linhas.append(f"\n**C {'PASSA' if res['passa'] else 'NÃO PASSA'}.** Custo da coleta: US$ {res['custo_usd']:.4f}.")
    return "\n".join(linhas)


# --- estimativa (gratis; dados ja vistos da Parte 2.2: NAO e medicao) ---------------------


def estimativa_notas() -> dict:
    """Que nota o passo daria para cada uma das 200 fichas v3 GRAVADAS na Parte 2.2 (o
    AIMessage refeito do `bruto`, sem LLM). Confere: decisao so de ficha certa, nenhuma
    nota onde o esperado e aplica=false, e toda pergunta de temperatura com nota."""
    from decimal import Decimal

    from langchain_core.messages import AIMessage

    from orchestrator.graph import rag_limites
    from orchestrator.rag import limites_extracao_v3 as lx3

    esperado = {i["id"]: i for i in me.carregar_conjunto()}
    saida = {}
    for t in me.ler_registro(me.DIR_MEDICAO_V3):
        if t["estado"] != me.ESTADO_CONCLUIDA:
            continue
        d = json.loads((me.DIR_MEDICAO_V3 / t["arquivo"]).read_text(encoding="utf-8"))
        tipos, por_id, achados = {}, {}, []
        for x in d["respostas"]:
            q, e = x["pergunta"], esperado[x["id"]]
            if not rag_limites.precisa_de_ficha(q):
                tipo = "sem chamada"
            else:
                chamadas = [] if x.get("bruto") is None else [
                    {"name": lx3.NOME_FERRAMENTA, "args": x["bruto"], "id": "c"}]
                ficha = lx3.interpretar(q, AIMessage(content="", tool_calls=chamadas), tabela=rag_limites._tabela())
                nota = rag_limites.nota_da_ficha(q, ficha)
                tipo = "nenhuma" if nota is None else (
                    "nao_verificavel" if rag_limites.NAO_VERIFICAVEL in nota else "decisao")
                ee = e["esperado"]
                if tipo == "decisao" and not (
                        ee["aplica"] and (ficha.contexto, ficha.categoria) == (ee["contexto"], ee["categoria"])
                        and ee["valor"] is not None and ficha.valor == Decimal(str(ee["valor"]))):
                    achados.append(f"{x['id']}: decisao de ficha errada")
            if not e["esperado"]["aplica"] and tipo in ("decisao", "nao_verificavel"):
                achados.append(f"{x['id']}: nota {tipo} numa pergunta com aplica=false esperado")
            if e["esperado"]["aplica"] and tipo in ("nenhuma", "sem chamada"):
                achados.append(f"{x['id']}: pergunta de temperatura sem nota")
            chave = f"{e['tipo']}/{tipo}"
            tipos[chave] = tipos.get(chave, 0) + 1
            por_id[x["id"]] = tipo
        saida[t["rodada"]] = {"tipos": dict(sorted(tipos.items())), "por_id": por_id, "achados": achados}
    return saida


def relatorio_estimativa(est: dict, gabarito: list[dict]) -> str:
    from orchestrator.graph import rag_limites

    linhas = ["ESTIMATIVA sobre as fichas ja gravadas da Parte 2.2 (NAO e medicao)"]
    for rodada, x in est.items():
        linhas.append(f"[{rodada}] " + "; ".join(f"{k}: {n}" for k, n in x["tipos"].items()))
        linhas.append(f"  i04: {x['por_id'].get('i04')}; i10: {x['por_id'].get('i10')}; "
                      f"i06: {x['por_id'].get('i06')}")
        linhas.append("  achados: " + ("; ".join(x["achados"]) or "nenhum"))
    pref = [g["id"] for g in gabarito if rag_limites.precisa_de_ficha(g["pergunta"])]
    linhas.append(f"gabarito q01-q20: o codigo chama a ficha em {', '.join(pref) or 'nenhuma'}")
    return "\n".join(linhas)


# --- plano e projecao (gratis; a C nao abre o arquivo) ---------------------------------


def _media(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def custos_reais() -> dict:
    """Custos REAIS ja medidos: q02 v1 (mini-teste), respostas e juiz v1 por rodada
    (Missao 10) e a ficha v3 por chamada (maior da Parte 2.2)."""
    mini = json.loads(mq.RESPOSTAS_PADRAO.read_text(encoding="utf-8"))
    q02 = [r["custo_usd"] for r in mini["respostas"] if r["id"] == "q02" and r["versao"] == "v1"]
    resp, julg = [], []
    for r in m10.RODADAS:
        pr, pj = m10.caminhos("v1", r)
        resp.append(json.loads(pr.read_text(encoding="utf-8"))["custo_usd"])
        julg.append(json.loads(pj.read_text(encoding="utf-8"))["custo_usd"])
    ficha = []
    for t in me.ler_registro(me.DIR_MEDICAO_V3):
        if t["estado"] == me.ESTADO_CONCLUIDA:
            d = json.loads((me.DIR_MEDICAO_V3 / t["arquivo"]).read_text(encoding="utf-8"))
            ficha += [x["custo_usd"] for x in d["respostas"]]
    return {"q02_v1": _media(q02), "b_respostas_v1": _media(resp), "b_juiz_v1": _media(julg),
            "por_resposta_v1": _media(resp) / 20, "ficha_max": max(ficha) if ficha else 0.0}


def projecao(settings, gabarito: list[dict]) -> dict:
    from orchestrator.graph import rag_limites, rag_specialist

    real = custos_reais()  # medidos pelo OpenRouter (Missoes 8-10, mini-teste, Parte 2.2)
    # Motor deepseek: os custos antigos x o fator de preco por token (pico, sem cache).
    # E so projecao: o numero de tokens do modelo novo pode ser outro. O juiz nao muda.
    deepseek = llm_motor.provedor(settings) == "deepseek"
    fator = llm_motor.fator_vs_openrouter_antigo() if deepseek else 1.0
    real = {**real, **{k: real[k] * fator for k in ("q02_v1", "b_respostas_v1", "por_resposta_v1", "ficha_max")}}
    pe = (llm_motor.PRECO_DEEPSEEK_FLASH["pico"]["entrada_cache_miss"] if deepseek
          else av.PRECOS.get(settings.general_model, av.PRECO_DESCONHECIDO)[0])
    regra6 = len(rag_specialist._REGRA_LIMITES_V5) / av.CHARS_POR_TOKEN * pe / 1e6
    nota = 600 / av.CHARS_POR_TOKEN * pe / 1e6  # a nota [limite] no prompt do synth (folga)
    com_ficha = real["ficha_max"] + nota
    pref_b = [g["id"] for g in gabarito if rag_limites.precisa_de_ficha(g["pergunta"])]
    a = {"v1": A_N * real["q02_v1"], "v5": A_N * (real["q02_v1"] + regra6 + com_ficha)}
    b_v5 = real["b_respostas_v1"] + len(gabarito) * regra6 + len(pref_b) * com_ficha
    b = {"v1": len(RODADAS) * real["b_respostas_v1"], "v5": len(RODADAS) * b_v5,
         "juiz": len(ORDEM_B) * real["b_juiz_v1"]}
    # C: todas as 10 com a ficha (conservador: o arquivo nao e aberto no plano)
    c = {"v1": C_N * N_PROVA10 * real["por_resposta_v1"],
         "v5": C_N * N_PROVA10 * (real["por_resposta_v1"] + regra6 + com_ficha)}
    total = {k: sum(x.values()) for k, x in (("a", a), ("b", b), ("c", c))}
    return {"real": real, "fator_de_preco": fator, "prefiltro_b": pref_b, "regra6_usd": regra6, "com_ficha_usd": com_ficha,
            "a": a, "b": b, "b_v5_por_rodada": b_v5, "c": c, "total": total, "total_geral": sum(total.values())}


def comandos() -> dict[str, list[str]]:
    base = ".venv/bin/python -m orchestrator.rag.parte3"
    b = [f"{base} --executar b --versao {v} --rodada {r} --orcamento {TETO_TENTATIVA_USD['b-' + v]:.2f}"
         for v, r in ORDEM_B]
    b += [f"{base} --julgar b --versao {v} --rodada {r} --orcamento {TETO_TENTATIVA_USD['b-juiz']:.2f}"
          for v, r in ORDEM_B]
    prova = "~/Documentos/Kali\\ Linux/lacre/prova10-v1.yaml"
    return {
        "teste": [f"{base} --teste-conexao", f"{base} --teste-ficha"],
        "2.3": me.comandos(me.orcamento_v3_flash(None), me.VERSAO_FLASH),
        "a": [f"{base} --executar a --orcamento {TETO_TENTATIVA_USD['a']:.2f}", f"{base} --classificar a",
              f"{base} --resultado a"],
        "b": [*b, f"{base} --resultado b"],
        "c": [f"{base} --executar c --prova {prova} --orcamento {TETO_TENTATIVA_USD['c']:.2f}",
              f"{base} --classificar c --prova {prova}", f"{base} --resultado c --prova {prova}"],
    }


def mostrar_plano(settings, gabarito: list[dict]) -> int:
    meta_m8, meta = m9.indice_meta_m8(), av._meta_do_indice(settings)
    print("Parte 3 - ferramenta de limites no agente, v1 x v5 (NADA executado)")
    problemas = conferir_sistema(settings)
    print("pre-registro: " + ("OK (regras v1 e v5, rag_limites.py, llm_motor.py e ficha v3 = pre-registro e emendas)" if not problemas
                              else "DIFERENTE: " + "; ".join(problemas)))
    print(f"versoes     : v1 = regras v1 + RAG_LIMITES desligado; v5 = regras v5 ({HASH_REGRAS_V5[:12]}...) "
          "+ RAG_LIMITES ligado")
    print(f"indice      : {settings.rag_index_path}; indice_meta {'IGUAL' if meta and meta == meta_m8 else 'DIFERENTE'} "
          "ao da Missao 8")
    print(f"busca       : modo {settings.rag_search_mode}, top_k {settings.rag_top_k}, rerank "
          f"{settings.rag_rerank_model or 'nao'}; modelos {settings.router_model} / {settings.general_model}")
    mt = llm_motor.descrever(settings)
    print(f"motor       : {mt['provedor']} ({mt['base_url']}), modelo efetivo {mt['modelo_efetivo_general']}"
          + (f" ({mt['versao_documentada']}), pensamento {mt['pensamento']}" if mt["provedor"] == "deepseek" else "")
          + "; supervisor, ficha e redator. O juiz da B continua no OpenRouter (pre-registrado)")
    if mt["provedor"] == "deepseek":
        pp, pf = llm_motor.PRECO_DEEPSEEK_FLASH["pico"], llm_motor.PRECO_DEEPSEEK_FLASH["fora_de_pico"]
        print(f"preco       : {llm_motor.DEEPSEEK_MODELO}, US$ por 1M: entrada cache hit {pp['entrada_cache_hit']} / "
              f"cache miss {pp['entrada_cache_miss']} / saida {pp['saida']} no pico (fora de pico: "
              f"{pf['entrada_cache_hit']} / {pf['entrada_cache_miss']} / {pf['saida']}); o custo usa SEMPRE o pico. "
              f"Fonte {llm_motor.FONTE_PRECO}, lida em {llm_motor.DATA_PRECO}")
    print(f"chaves      : DEEPSEEK_API_KEY {'existe' if settings.deepseek_api_key else 'NAO EXISTE'}; "
          f"ORCHESTRATOR_OPENROUTER_API_KEY (juiz da B) {'existe' if settings.openrouter_api_key else 'NAO EXISTE'}")
    reg_a = me.ler_registro(DIR_A)
    antigas = do_motor(reg_a, PROVEDOR_ANTES_DA_EMENDA)
    novas = do_motor(reg_a, mt["provedor"])
    if antigas and mt["provedor"] != PROVEDOR_ANTES_DA_EMENDA:
        print(f"A antes     : {len(antigas)} tentativas no {PROVEDOR_ANTES_DA_EMENDA} ("
              + ", ".join(sorted({t['estado'] for t in antigas})) + f"), US$ {me.gasto_registrado(antigas):.4f}, "
              "sem resultado; nao contam para o motor novo (emenda de 24/11)")
    fi = sum(t["unidade"] == "a" and t["estado"] == me.ESTADO_FALHA_INICIAL for t in reg_a)
    print(f"A {mt['provedor']:<9} : {len(novas)} tentativa(s); resta US$ "
          f"{TETO_MEDICAO_USD['a'] - me.gasto_registrado(novas):.4f} do teto da medicao; falhas iniciais: "
          f"{fi} de {me.MAX_FALHAS_INICIAIS} (todos os motores), resta {max(me.MAX_FALHAS_INICIAIS - fi, 0)}")
    p23 = me.projecao_v3_flash()
    print(f"Parte 2.3   : a ficha v3 no deepseek-flash, 2 x 100 chamadas; projecao US$ "
          f"{p23['duas_rodadas_usd'] if p23 else float('nan'):.4f} (US$ {me._tetos(me.VERSAO_FLASH)[0]:.2f}/rodada, "
          f"teto US$ {me._tetos(me.VERSAO_FLASH)[1]:.2f}); {me.veredito_v3_flash()[1]}")
    p = projecao(settings, gabarito)
    r = p["real"]
    print(f"custo real  : q02 v1 US$ {r['q02_v1']:.5f}/resposta (mini-teste); B v1 US$ {r['b_respostas_v1']:.4f} "
          f"respostas + US$ {r['b_juiz_v1']:.4f} juiz por rodada (M10); ficha ate US$ {r['ficha_max']:.6f}/chamada (P2.2)"
          + (f"; ja x {p['fator_de_preco']:.4f} (preco do motor novo / preco antigo; o juiz nao)" if p["fator_de_preco"] != 1
             else ""))
    print(f"v5 a mais   : regra 6 ~US$ {p['regra6_usd']:.6f}/resposta; ficha + nota ~US$ {p['com_ficha_usd']:.6f} "
          "quando o codigo acha numero/temperatura")
    print(f"pre-filtro B: o codigo chama a ficha em {', '.join(p['prefiltro_b']) or 'nenhuma'} (das 20)")
    a, b, c = p["a"], p["b"], p["c"]
    print(f"A projecao  : v1 US$ {a['v1']:.4f} + v5 US$ {a['v5']:.4f} = US$ {p['total']['a']:.4f}; "
          f"teto US$ {TETO_TENTATIVA_USD['a']:.2f} por tentativa, US$ {TETO_MEDICAO_USD['a']:.2f} com a repeticao")
    print(f"B projecao  : respostas v1 US$ {b['v1']:.4f} + v5 US$ {b['v5']:.4f} + juiz US$ {b['juiz']:.4f} = "
          f"US$ {p['total']['b']:.4f}; teto por tentativa v1 US$ {TETO_TENTATIVA_USD['b-v1']:.2f}, v5 US$ "
          f"{TETO_TENTATIVA_USD['b-v5']:.2f}, juiz US$ {TETO_TENTATIVA_USD['b-juiz']:.2f}; teto da medicao US$ "
          f"{TETO_MEDICAO_USD['b']:.2f}")
    print(f"C projecao  : v1 US$ {c['v1']:.4f} + v5 US$ {c['v5']:.4f} = US$ {p['total']['c']:.4f} (as 10 com ficha); "
          f"teto US$ {TETO_TENTATIVA_USD['c']:.2f} por tentativa, US$ {TETO_MEDICAO_USD['c']:.2f} com a repeticao")
    sem_rep = TETO_TENTATIVA_USD["a"] + 2 * (TETO_TENTATIVA_USD["b-v1"] + TETO_TENTATIVA_USD["b-v5"]) \
        + 4 * TETO_TENTATIVA_USD["b-juiz"] + TETO_TENTATIVA_USD["c"]
    print(f"total       : projetado US$ {p['total_geral']:.4f}; teto sem repeticao US$ {sem_rep:.2f}; teto maximo "
          f"(com as repeticoes) US$ {sum(TETO_MEDICAO_USD.values()):.2f}")
    print("C           : o arquivo lacrado NAO e aberto no plano; o --executar confere o sha256 antes de ler")
    estados = {m: veredito(m)[1] for m in ("2.3", "a", "b")}
    print(f"ordem       : 2.3 -> A -> B -> C (travas de 24/11): 2.3: {estados['2.3']}; A: {estados['a']}; "
          f"B: {estados['b']}; "
          + "; ".join(f"--executar {m}: {'liberado' if trava_da_ordem(m) is None else 'BLOQUEADO'}" for m in "abc"))
    print("pagos, nesta ordem: 1. --teste-conexao; 2. --teste-ficha; 3. Parte 2.3 r1, r2 e --resultado; "
          "4. so se a 2.3 passar, a A (depois B e C, pelas travas)")
    for m, cmds in comandos().items():
        print(f"comandos {m.upper()}  :")
        for i, cmd in enumerate(cmds, 1):
            print(f"  {i}. {cmd}")
    if av._aviso_tracing():
        print("AVISO       : tracing do LangSmith ligado (a C recusa rodar assim)")
    if not settings.openrouter_api_key:
        print("AVISO       : ORCHESTRATOR_OPENROUTER_API_KEY ausente (o juiz da B precisa; rode de dentro de orchestrator/)")
    if mt["provedor"] == "deepseek" and not settings.deepseek_api_key:
        print("AVISO       : DEEPSEEK_API_KEY ausente (o motor da medicao precisa; rode de dentro de orchestrator/)")
    return 0


def _teste(args, settings) -> int:
    """--teste-conexao / --teste-ficha: PAGOS, minimos; mostram so ok, modelo e custo."""
    print(f"motor       : deepseek ({llm_motor.DEEPSEEK_BASE_URL}), modelo pedido {llm_motor.DEEPSEEK_MODELO}, "
          "pensamento desligado")
    r = (llm_motor.teste_conexao if args.teste_conexao else llm_motor.teste_ficha)(settings)
    if not r["ok"]:
        status = f", HTTP {r['status_http']}" if r.get("status_http") else ""
        print(f"conexao     : FALHOU ({r['erro_tipo']}{status})")
        return 1
    print("conexao     : OK")
    print(f"modelo      : {r['modelo_devolvido'] or '(nao devolvido)'}")
    if args.teste_conexao:
        print(f"resposta    : {'comecou com ok' if r['respondeu_ok'] else 'NAO comecou com ok'}")
    else:
        print(f"ferramenta  : {'veio (tool_choice nomeado funciona)' if r['chamou_a_ferramenta'] else 'NAO veio'}")
    tk = r["tokens"] or {}
    print(f"custo       : US$ {r['custo_usd']:.6f} (tokens x preco oficial, tarifa de pico; cache hit "
          f"{tk.get('entrada_cache_hit', '?')}, miss {tk.get('entrada_cache_miss', '?')}, saida {tk.get('saida', '?')})")
    return 0


# --- CLI --------------------------------------------------------------------------------


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    acao = p.add_mutually_exclusive_group()
    acao.add_argument("--executar", choices=("a", "b", "c"), help="PAGO: uma tentativa da medicao")
    acao.add_argument("--julgar", choices=("b",), help="PAGO: o juiz de uma rodada da B")
    acao.add_argument("--classificar", choices=("a", "c"), help="gratis: arquivo cego + mapa")
    acao.add_argument("--resultado", choices=("a", "b", "c"), help="gratis: aplica a regra pre-registrada")
    acao.add_argument("--estimativa", action="store_true", help="gratis: notas sobre as fichas da Parte 2.2")
    acao.add_argument("--teste-conexao", action="store_true",
                      help="PAGO (minimo): 1 chamada 'responda so: ok' com o motor deepseek; mostra ok, modelo e custo")
    acao.add_argument("--teste-ficha", action="store_true",
                      help="PAGO (minimo, opcional): 1 chamada do extrator com o motor deepseek (tool_choice nomeado)")
    p.add_argument("--versao", choices=VERSOES)
    p.add_argument("--rodada", choices=RODADAS)
    p.add_argument("--orcamento", type=float)
    p.add_argument("--prova", type=Path, help="o arquivo lacrado (so na C)")
    p.add_argument("--saida-c", type=Path, help="pasta da C (fora do repo; padrao: ao lado do arquivo lacrado)")
    a = p.parse_args(argv)
    pago = bool(a.executar or a.julgar)
    if pago and a.orcamento is None:
        p.error("--executar/--julgar exigem --orcamento")
    if not pago and a.orcamento is not None:
        p.error("--orcamento so vale com --executar/--julgar")
    medicao = a.executar or a.julgar or a.classificar or a.resultado
    precisa_vr = medicao == "b" and pago
    if precisa_vr != bool(a.versao and a.rodada) or (not precisa_vr and (a.versao or a.rodada)):
        p.error("--versao e --rodada valem (e sao obrigatorias) so no --executar/--julgar da B")
    if (medicao == "c") != (a.prova is not None):
        p.error("--prova vale (e e obrigatoria) so na C")
    if a.saida_c is not None and medicao != "c":
        p.error("--saida-c so vale na C")
    return a


def _gravar_json(caminho: Path, dados: dict) -> None:
    av._gravar(caminho, dados)


def _executar(args, settings, gabarito: list[dict]) -> int:
    medicao = args.executar or args.julgar
    motivo = trava_da_ordem(medicao)  # antes de tudo: na C, antes ate de ler a prova
    if motivo:
        print(f"RECUSADO: {motivo}")
        return 2
    if args.julgar and not settings.openrouter_api_key:  # o juiz continua no OpenRouter
        print("erro: ORCHESTRATOR_OPENROUTER_API_KEY ausente (rode de dentro de orchestrator/, com o .env)", file=sys.stderr)
        return 2
    if args.executar:
        try:  # o motor da medicao (emenda de 24/11); a mensagem so cita o NOME da chave
            llm_motor.conexao(settings, settings.general_model)
        except llm_motor.MotorIndisponivel as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 2
    problemas = conferir_sistema(settings)
    if problemas:
        print("RECUSADO: o sistema nao e o pre-registrado:", *problemas, sep="\n  - ")
        return 2
    if medicao == "c":
        if av._aviso_tracing():
            print("RECUSADO: tracing do LangSmith ligado (as perguntas lacradas iriam para o LangSmith)")
            return 2
        prova = carregar_prova(args.prova)
        diretorio, unidade, chave = diretorio_c(args.prova, args.saida_c), "c", "c"
    else:
        if av._aviso_tracing():
            print("AVISO: tracing do LangSmith ligado - perguntas, trechos e respostas vao para o LangSmith")
        diretorio = DIR_A if medicao == "a" else DIR_B
        if medicao == "a":
            unidade, chave = "a", "a"
        elif args.executar:
            unidade, chave = f"{args.versao}-{args.rodada}", f"b-{args.versao}"
        else:
            unidade, chave = f"juiz-{args.versao}-{args.rodada}", "b-juiz"
    if not args.julgar and not Path(settings.rag_index_path).is_file():
        print(f"erro: indice ausente em {settings.rag_index_path}", file=sys.stderr)
        return 2
    tentativas = me.ler_registro(diretorio)
    if concluida(tentativas, unidade):  # concluida com qualquer motor: nao roda de novo
        print(f"RECUSADO: {unidade} ja foi concluida")
        return 2
    if falhas_iniciais_esgotadas(tentativas, unidade):
        print(f"RECUSADO: {unidade} ja teve {me.MAX_FALHAS_INICIAIS} falhas iniciais (contando todos os motores)")
        return 2
    do_motor_atual = do_motor(tentativas, llm_motor.provedor(settings))
    ok, motivo = pode_executar(do_motor_atual, medicao, unidade)
    if not ok:
        print(f"RECUSADO: {motivo} (motor {llm_motor.provedor(settings)})")
        return 2
    try:
        validar_orcamento(args.orcamento, medicao, chave, do_motor_atual)
    except ValueError as exc:
        print(f"RECUSADO: {exc}")
        return 2

    tentativas, t = _iniciar(diretorio, unidade, args.orcamento, llm_motor.provedor(settings))
    arquivo = f"{'julgamento' if args.julgar else 'respostas'}-{unidade.removeprefix('juiz-')}-t{t['n']}.json"
    try:
        if medicao in ("a", "c"):
            passos, itens, nome = ((passos_a(), {A_PERGUNTA: mq.filtrar_gabarito(gabarito, (A_PERGUNTA,))[0]},
                                    "parte3-a") if medicao == "a" else (passos_c(), itens_da_prova(prova), "parte3-c"))
            dados = asyncio.run(coletar(passos, itens, orcamento=args.orcamento, experimento=nome))
            estado = estado_da_coleta(dados)
        elif args.executar:
            with com_versao(args.versao):
                dados = asyncio.run(av.etapa_respostas(gabarito, orcamento=args.orcamento, regras=args.versao,
                                                       aceitas=VERSOES))
                dados["parte3"] = {"versao": args.versao, "rag_limites": settings.rag_limites,
                                   "hashes": _hashes_parte3(), "motor": llm_motor.descrever(settings)}
            for x in dados["perguntas"]:
                x["notas_limite"] = notas_limite(x)
                x["provedor"] = llm_motor.provedor(settings)
                x["modelo_efetivo"] = llm_motor.modelo_efetivo(settings, settings.general_model)
            infra = problemas_da_versao(args.versao, dados["perguntas"], unidade)
            estado = (me.ESTADO_ORCAMENTO if dados["abortado_por_orcamento"]
                      else me.ESTADO_INFRA if infra else me.ESTADO_CONCLUIDA)
        else:
            resp_t = concluida(tentativas, f"{args.versao}-{args.rodada}")
            respostas = json.loads((diretorio / resp_t["arquivo"]).read_text(encoding="utf-8"))
            calibracao = av.status_sem_calibracao(av.CALIBRACAO)
            dados = asyncio.run(av.etapa_julgar(respostas, gabarito, settings.openrouter_api_key,
                                                orcamento=args.orcamento, calibracao=calibracao, alvo=ALVO_DO_JUIZ))
            erros = [i for parte in ("fidelidade", "correcao") for i, x in dados[parte].items() if x.get("erro")]
            estado = (me.ESTADO_ORCAMENTO if dados["abortado_por_orcamento"]
                      else me.ESTADO_INFRA if erros else me.ESTADO_CONCLUIDA)
    except av.FalhaInicial as exc:
        _fechar(diretorio, tentativas, t, me.ESTADO_FALHA_INICIAL, 0.0, erro_tipo=getattr(exc, "erro_tipo", None))
        print(f"falha inicial ({getattr(exc, 'erro_tipo', None) or type(exc).__name__}): nada medido; registrada")
        return 2
    dados["parte3_medicao"] = medicao
    _gravar_json(diretorio / arquivo, dados)
    _fechar(diretorio, tentativas, t, estado, dados["custo_usd"], arquivo)
    print(f"\n{unidade}: {estado}; US$ {dados['custo_usd']:.4f} -> {diretorio / arquivo}")
    return 0 if estado == me.ESTADO_CONCLUIDA else 1


def _classificar(args) -> int:
    medicao = args.classificar
    if medicao == "c":
        prova = carregar_prova(args.prova)
        diretorio = diretorio_c(args.prova, args.saida_c)
        gabarito = {f"p{i:02d}": {k: v for k, v in it.items() if k != "pergunta"} for i, it in enumerate(prova, 1)}
        cabecalho = CABECALHO_C
    else:
        diretorio, gabarito, cabecalho = DIR_A, None, CABECALHO_A
    t = concluida(me.ler_registro(diretorio), medicao)
    if t is None:
        print(f"erro: a coleta {medicao.upper()} nao foi concluida", file=sys.stderr)
        return 2
    destino, mapa_path = diretorio / "classificacao-cega.yaml", diretorio / "mapa-cego.json"
    if destino.exists() or mapa_path.exists():
        print("erro: a classificacao cega ja foi gerada (nao sobrescrevo)", file=sys.stderr)
        return 2
    dados = json.loads((diretorio / t["arquivo"]).read_text(encoding="utf-8"))
    yaml_cego, mapa = gerar_cego(dados["respostas"], cabecalho, gabarito)
    destino.write_text(yaml_cego, encoding="utf-8")
    mapa_path.write_text(json.dumps(mapa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"arquivo cego: {destino}\nmapa (NAO abrir ate as {mapa['total']} classes): {mapa_path}")
    return 0


def _resultado(args, gabarito: list[dict]) -> int:
    medicao = args.resultado
    if medicao == "b":
        try:
            c = comparar_b(carregar_b(), gabarito, av.carregar_fatos(), av.carregar_formato(), m9.indice_meta_m8())
        except ValueError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 2
        print(relatorio_b(c))
        gravar_resultado("b", c)
        return 0 if c["valido"] else 1
    if medicao == "c":
        prova = carregar_prova(args.prova)
        diretorio = diretorio_c(args.prova, args.saida_c)
    else:
        diretorio = DIR_A
    t = concluida(me.ler_registro(diretorio), medicao)
    if t is None:
        print(f"erro: a coleta {medicao.upper()} nao foi concluida", file=sys.stderr)
        return 2
    dados = json.loads((diretorio / t["arquivo"]).read_text(encoding="utf-8"))
    classificacao = yaml.safe_load((diretorio / "classificacao-cega.yaml").read_text(encoding="utf-8"))
    mapa = json.loads((diretorio / "mapa-cego.json").read_text(encoding="utf-8"))
    try:
        if medicao == "a":
            res = resultado_a(dados, classificacao, mapa, m9.indice_meta_m8())
            print(relatorio_a(res))
            gravar_resultado("a", res)
        else:
            res = resultado_c(dados, classificacao, mapa, perguntas_de_temperatura(prova), m9.indice_meta_m8())
            print(relatorio_c(res))
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    return 0 if res["valido"] else 1


def main(argv=None) -> int:
    args = parse_args(argv)
    from orchestrator.config import settings

    if args.teste_conexao or args.teste_ficha:
        return _teste(args, settings)
    gabarito = av.carregar_gabarito()
    if args.estimativa:
        print(relatorio_estimativa(estimativa_notas(), gabarito))
        return 0
    try:
        if args.executar or args.julgar:
            with com_motor():
                return _executar(args, settings, gabarito)
        if args.classificar:
            return _classificar(args)
        if args.resultado:
            return _resultado(args, gabarito)
    except ProvaRecusada as exc:
        print(f"RECUSADO: {exc}")
        return 2
    except Exception as exc:  # na C, a mensagem pode trazer texto lacrado
        if (args.executar or args.classificar or args.resultado) == "c":
            print(f"erro na C ({type(exc).__name__}); detalhe omitido para nao vazar a prova", file=sys.stderr)
            return 2
        raise
    with com_motor():
        return mostrar_plano(settings, gabarito)


if __name__ == "__main__":
    raise SystemExit(main())
