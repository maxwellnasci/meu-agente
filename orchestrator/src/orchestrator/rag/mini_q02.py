"""Mini-teste q02 e q04: v1 (padrao) x v4 (proposta Antigravity, Regra 6).

SINAL barato (sem juiz pago) para medir no modelo de producao se a proposta v4
corrige os erros de conclusao da q02 e da q04. Nao adota nada: o padrao de
producao (`settings.rag_regras_versao = "v1"`) e o `REGRAS_POR_VERSAO` do bot
permanecem intactos; a v4 so existe por parametro dentro deste script.
Pre-registro em `docs/exploracao/mini-teste-q02.md`, escrito ANTES de medir.

    cd orchestrator
    .venv/bin/python -m orchestrator.rag.mini_q02                           # plano + custo (gratis)
    .venv/bin/python -m orchestrator.rag.mini_q02 --executar --orcamento 0.10  # pago: 40 respostas intercaladas
    .venv/bin/python -m orchestrator.rag.mini_q02 --classificar-arquivo     # gratis: arquivo cego + mapa
    #   ... o Max cola SO o classificacao-cega.yaml no chat; o Claude classifica os 40; o Max confere ...
    .venv/bin/python -m orchestrator.rag.mini_q02 --resultado               # gratis: aplica criterios 1-3
"""

import argparse
import asyncio
import json
import random
import re
import secrets
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import yaml

from orchestrator.rag import avaliar_respostas as av
from orchestrator.rag import juiz
from orchestrator.rag import missao10 as m10

PERGUNTAS_IDS = ("q02", "q04")
VERSOES = ("v1", "v4")
N_AMOSTRAS = 10
TOTAL_RESPOSTAS = len(PERGUNTAS_IDS) * len(VERSOES) * N_AMOSTRAS
TETO_ORCAMENTO_USD = 0.10
# Emenda M-01: a semente do embaralhamento cego NAO e fixa nem publica. E sorteada
# com `secrets` no --classificar-arquivo e gravada SO no mapa-cego.json.
BITS_SEMENTE = 128
MAX_TENTATIVAS_FALHA_INICIAL = 2  # Emenda B-03: FalhaInicial permite repetir UMA vez
MAX_COLETAS = 2  # Emenda E-B03: 1 coleta + UMA nova coleta completa, so apos INVALIDA por infra

REPO_DIR = av.ORCHESTRATOR_DIR.parent
CAMINHO_PROPOSTA_V4 = REPO_DIR / "docs" / "exploracao" / "regras-proposta.txt"
DIR_SAIDA = av.ORCHESTRATOR_DIR / "fixtures" / "rag" / "explore" / "mini-q02"
RESPOSTAS_PADRAO = DIR_SAIDA / "respostas.json"
CLASSIFICACAO_PADRAO = DIR_SAIDA / "classificacao-cega.yaml"
MAPA_PADRAO = DIR_SAIDA / "mapa-cego.json"
# Emenda E-B03: controle FIXO em DIR_SAIDA (nao depende de --saida), com DOIS
# contadores separados: o registro das FalhaInicial e o registro das coletas. Cada
# coleta entra como "iniciada" ANTES da 1a chamada paga; interrupcao (Ctrl+C, kill,
# queda de energia) deixa "iniciada" = INVALIDA, sem nova coleta.
NOME_REGISTRO_FALHA_INICIAL = "falha-inicial.json"
NOME_REGISTRO_COLETAS = "coletas.json"
ESTADO_INICIADA = "iniciada"
ESTADO_CONCLUIDA = "concluida"
ESTADO_INFRA_1A = "invalida_infra_1a"  # libera UMA nova coleta completa
ESTADO_INFRA_2A = "invalida_infra_2a_encerra"  # encerra a exploracao sem resultado
ESTADO_ORCAMENTO = "invalida_orcamento"  # nao e infra: sem nova coleta
ESTADO_FALHA_INICIAL = "falha_inicial"  # so no registro de FalhaInicial

# Hashes CONGELADOS no pre-registro (docs/exploracao/mini-teste-q02.md).
# v1: identica as Missoes 8, 9 e 10.
# v4: arquivo docs/exploracao/regras-proposta.txt carregado como "\n\n" + texto.rstrip("\n"),
# que comeca byte a byte por REGRAS_DO_MANUAL (v4 = v1 + acrescimo).
HASH_REGRAS_V1 = m10.HASH_REGRAS_V1
HASH_ARQUIVO_V4 = "4c23e9c03e040c9972d438fb58aa43f9c18f6990d13b9f8bb99a0fa16497070b"
HASH_REGRAS_V4 = "646921f245b120a1faeac60df499054dc238a1f863f537e91d59147a3600e1a0"
HASH_REGRAS_PRE_REGISTRO = {"v1": HASH_REGRAS_V1, "v4": HASH_REGRAS_V4}

CLASSE_CERTA = {"q02": "RECUSA", "q04": "NÃO TROCA"}
CLASSES_VALIDAS = {
    "q02": ("RECUSA", "ACEITA", "AMBÍGUA"),
    "q04": ("NÃO TROCA", "TROCA", "AMBÍGUA"),
}
_CLASSE_NORMALIZADA = {
    "q02": {"recusa": "RECUSA", "aceita": "ACEITA", "ambigua": "AMBÍGUA"},
    "q04": {"nao troca": "NÃO TROCA", "troca": "TROCA", "ambigua": "AMBÍGUA"},
}

# Criterio 3: detectar resposta que diz que o manual nao cobre o assunto, evitando
# falso positivo em negativas corretas como "o manual nao preve troca apos o prazo"
# (resposta certa da q04 na M10). Emenda B-02: lista ampliada, texto ja normalizado
# (sem acento, minusculas). "preve", "permite", "aceita" etc. NAO entram de proposito.
_SUJEITO_MANUAL = (
    r"(?:manual(?:\s+de\s+procedimentos)?|pop(?:[\s-]*\d+)?|procedimento"
    r"|trechos?(?:\s+recebidos|\s+do\s+manual)?)"
)
_VERBO_COBERTURA = (
    r"(?:cobre|cobrem|trata|tratam|aborda|abordam|contempla|contemplam"
    r"|menciona|mencionam|especifica|especificam)"
)
_DIZ_NAO_COBRE = re.compile(
    # "o manual/o POP(-01)/o procedimento/os trechos nao cobre(m)/trata/aborda/contempla/menciona/especifica"
    rf"\b{_SUJEITO_MANUAL}\s+nao\s+{_VERBO_COBERTURA}\b"
    r"|\bnao\s+cobrem?\s+(?:isso|esse|essa|este|esta|o\s+assunto|a\s+situacao|o\s+caso|especificamente)\b"
    r"|\bnao\s+especificam?\b"
    r"|\bnao\s+encontrei\b[^.]{0,60}?\b(?:manual|trechos?|pop)\b"
    r"|\bnao\s+ha\s+informac(?:ao|oes)\b"
    r"|\bnao\s+constam?\s+(?:no|nos|na|nas|em)\s+(?:manual|trechos?|pop|procedimento)\b"
)

# Cabecalho do arquivo cego: deliberadamente SEM mencionar nomes de versoes nem hashes.
_INSTRUCOES_CEGAS = """\
# Classificacao CEGA do mini-teste (q02 e q04).
# Preencha o campo `classe` de TODOS os itens antes de rodar `--resultado`.
#
# Classes permitidas:
#   q02: RECUSA (certo) | ACEITA (errado) | AMBÍGUA (nao conclui ou conclui as duas coisas)
#   q04: NÃO TROCA (certo) | TROCA (errado) | AMBÍGUA
#
# Regra para AMBÍGUA: a resposta nao deixa claro o que o funcionario deve fazer
# AGORA com aquele produto. "Sim, se estiver dentro de 24 h" para uma compra de
# anteontem conta como TROCA (errado), nao como AMBÍGUA.
#
# Quem classifica recebe SO este arquivo (sem mapa-cego.json e sem respostas.json).
# O campo `elo` so liga este arquivo ao mapa: e aleatorio e nao revela nada.
"""


# --- regras (v1 intacta; v4 restrita a este script) -------------------------


def carregar_regras_v4(path: Path = CAMINHO_PROPOSTA_V4, *, verificar_hash: bool = True) -> str:
    """Carrega docs/exploracao/regras-proposta.txt, normaliza quebras de borda para
    bater com a concatenacao de REGRAS_DO_MANUAL (`"\\n\\n" + texto.rstrip("\\n")`),
    confere que comeca EXATAMENTE pela v1 e (por padrao) confere os hashes congelados."""
    from orchestrator.graph import rag_specialist

    caminho = Path(path)
    if not caminho.is_file():
        raise FileNotFoundError(f"proposta v4 ausente em {caminho}")
    bruto = caminho.read_text(encoding="utf-8")
    texto = "\n\n" + bruto.rstrip("\n")
    v1 = rag_specialist.REGRAS_DO_MANUAL
    if not texto.startswith(v1):
        raise ValueError("a proposta v4 NAO comeca exatamente pelo texto da v1 (REGRAS_DO_MANUAL)")
    if len(texto) <= len(v1):
        raise ValueError("a proposta v4 nao tem acrescimo alem da v1")
    if verificar_hash:
        h_arq = juiz.sha256_arquivo(caminho)
        if h_arq != HASH_ARQUIVO_V4:
            raise ValueError(f"sha256 do arquivo v4 mudou: {h_arq} != pre-registrado {HASH_ARQUIVO_V4}")
        h_txt = av.sha256_texto(texto)
        if h_txt != HASH_REGRAS_V4:
            raise ValueError(f"sha256 do texto v4 mudou: {h_txt} != pre-registrado {HASH_REGRAS_V4}")
    return texto


def regras_do_mini_teste(versao: str, path_v4: Path = CAMINHO_PROPOSTA_V4) -> str:
    """Seleciona o texto das regras por parametro, SO dentro deste script."""
    from orchestrator.graph import rag_specialist

    if versao == "v1":
        v1 = rag_specialist.REGRAS_DO_MANUAL
        h = av.sha256_texto(v1)
        if h != HASH_REGRAS_V1:
            raise ValueError(f"REGRAS_DO_MANUAL (v1) mudou: {h} != pre-registrado {HASH_REGRAS_V1}")
        return v1
    if versao == "v4":
        return carregar_regras_v4(path_v4)
    raise ValueError(f"versao desconhecida no mini-teste: {versao!r} (validas: {', '.join(VERSOES)})")


@contextmanager
def _com_regras_no_synth(versao: str, texto_v4: str):
    """Injeta a v4 no `synthesize_final` so durante a chamada, sem alterar
    `REGRAS_POR_VERSAO` nem `settings.rag_regras_versao` (producao segue v1)."""
    from orchestrator.graph import rag_specialist

    if versao == "v1":
        yield
        return
    if versao != "v4":
        raise ValueError(f"versao desconhecida no mini-teste: {versao!r}")
    original = rag_specialist.regras_da_etapa1
    rag_specialist.regras_da_etapa1 = lambda v=None: texto_v4 if v in (None, "v1", "v4") else original(v)
    try:
        yield
    finally:
        rag_specialist.regras_da_etapa1 = original


# --- desenho e coleta -------------------------------------------------------


def _tipo_do_erro(r: dict) -> str:
    """So o TIPO do erro de uma resposta com falha (nunca a mensagem do provedor)."""
    erro = r.get("erro") or ""
    if erro:
        return erro.split(":", 1)[0]
    return ",".join(str(e.get("erro_tipo", "?")) for e in r.get("erros_llm") or []) or "falha_de_infra"


def _parada_por_infra(idx: int, qid: str, versao: str, amostra: int, tipo: str) -> dict:
    return {"indice_execucao": idx, "id": qid, "versao": versao, "amostra": amostra, "erro_tipo": tipo}


def _falha_inicial(qid: str, versao: str, amostra: int, tipo: str, detalhe: str) -> av.FalhaInicial:
    """FalhaInicial com `erro_tipo` (so o tipo, sem mensagem do provedor) para o registro em disco."""
    exc = av.FalhaInicial(f"a 1a chamada ({qid} {versao} a{amostra}) falhou: {detalhe}")
    exc.erro_tipo = tipo
    return exc


def filtrar_gabarito(gabarito: Sequence[dict], ids: Sequence[str] = PERGUNTAS_IDS) -> list[dict]:
    por_id = {g["id"]: g for g in gabarito}
    faltando = [qid for qid in ids if qid not in por_id]
    if faltando:
        raise ValueError(f"perguntas ausentes no gabarito: {', '.join(faltando)}")
    return [por_id[qid] for qid in ids]


def sequencia_execucao(
    perguntas_ids: Sequence[str] = PERGUNTAS_IDS,
    versoes: Sequence[str] = VERSOES,
    n_amostras: int = N_AMOSTRAS,
) -> list[dict]:
    """Ordem estritamente intercalada (v1, v4, v1, v4...), pareada por pergunta
    em cada amostra 1..n_amostras, para diluir deriva do provedor."""
    seq = []
    idx = 0
    for amostra in range(1, n_amostras + 1):
        for qid in perguntas_ids:
            for v in versoes:
                idx += 1
                seq.append({"indice_execucao": idx, "amostra": amostra, "id": qid, "versao": v})
    return seq


def _hashes_coleta(regras: dict[str, str], caminho_v4: Path) -> dict:
    from orchestrator.graph import nodes
    from orchestrator.schemas.routing import dispatch_tool

    hashes = {
        "gabarito": juiz.sha256_arquivo(av.GABARITO),
        "v1_regras_do_manual": av.sha256_texto(regras["v1"]) if "v1" in regras else HASH_REGRAS_V1,
        "v4_arquivo_proposta": juiz.sha256_arquivo(caminho_v4) if "v4" in regras else HASH_ARQUIVO_V4,
        "v4_regras_do_manual": av.sha256_texto(regras["v4"]) if "v4" in regras else HASH_REGRAS_V4,
        "prompt_supervisor": av.sha256_texto(nodes.supervisor_system_prompt(True)),
        "prompt_synthesize": av.sha256_texto(nodes._SYNTHESIZE_SYSTEM_PROMPT),
        "tool_dispatch": av.sha256_texto(json.dumps(dispatch_tool(True), sort_keys=True, ensure_ascii=False)),
    }
    return hashes


async def etapa_coleta(
    gabarito: Sequence[dict],
    *,
    orcamento: float = TETO_ORCAMENTO_USD,
    n_amostras: int = N_AMOSTRAS,
    versoes: Sequence[str] = VERSOES,
    caminho_v4: Path = CAMINHO_PROPOSTA_V4,
    graph_factory=None,
    responder: Callable = av.responder_pergunta,
    log=print,
) -> dict:
    """Roda q02 e q04 pelo grafo inteiro em ordem intercalada (v1, v4, ...),
    sem juiz pago, respeitando teto de orcamento e FalhaInicial na 1a chamada."""
    from langgraph.checkpoint.memory import MemorySaver

    from orchestrator.config import settings
    from orchestrator.graph import builder
    from orchestrator.rag.smoke import neutralizar_efeitos_externos

    if not 0 < orcamento <= TETO_ORCAMENTO_USD:
        raise ValueError(f"orcamento {orcamento} fora do pre-registrado (0 < orcamento <= {TETO_ORCAMENTO_USD})")
    if n_amostras < 1:
        raise ValueError(f"n_amostras invalido: {n_amostras}")
    regras = {v: regras_do_mini_teste(v, caminho_v4) for v in versoes}
    itens = filtrar_gabarito(gabarito, PERGUNTAS_IDS)
    por_id = {g["id"]: g for g in itens}
    plano = sequencia_execucao(PERGUNTAS_IDS, versoes, n_amostras)

    neutralizar_efeitos_externos(settings)
    rag_antes = settings.rag_enabled
    versao_antes = settings.rag_regras_versao
    limites_antes = settings.rag_limites
    settings.rag_enabled = True
    settings.rag_regras_versao = "v1"  # garante etapa 2 desligada; v4 entra so via _com_regras_no_synth
    # o mini-teste (v1 x v4) foi medido SEM a ferramenta de limites (padrao ligado desde 25/11/2026)
    settings.rag_limites = False

    try:
        graph = (graph_factory or builder.build_graph)(MemorySaver())
        saida = {
            "versao": 1,
            "experimento": "mini-teste-q02-q04",
            "data": datetime.now().astimezone().isoformat(timespec="seconds"),
            "git": av._git(),
            "config": {
                "router_model": settings.router_model,
                "general_model": settings.general_model,
                "temperatura_supervisor": 0,
                "temperatura_synthesize": None,
                "rag_search_mode": settings.rag_search_mode,
                "rag_top_k": settings.rag_top_k,
                "rag_colecao": settings.rag_colecao,
                "rag_rerank_model": settings.rag_rerank_model,
                "indice_meta": av._meta_do_indice(settings),
                "perguntas_ids": list(PERGUNTAS_IDS),
                "versoes": list(versoes),
                "n_amostras": n_amostras,
                "ordem": "intercalada (v1, v4, v1, v4...)",
                "metodo": "graph.ainvoke + callback (sem streaming); MemorySaver; n8n/gateway neutralizados; sem juiz",
            },
            "hashes": _hashes_coleta(regras, caminho_v4),
            "custo_usd": 0.0,
            "custo_por_versao_usd": {v: 0.0 for v in versoes},
            "orcamento_usd": orcamento,
            "abortado_por_orcamento": False,
            # Emenda B-03: excecao que interrompe a coleta depois da 1a chamada.
            "abortado_por_infra": None,
            "respostas": [],
        }

        total = len(plano)
        texto_v4 = regras.get("v4", "")
        for passo in plano:
            idx, amostra, qid, v = passo["indice_execucao"], passo["amostra"], passo["id"], passo["versao"]
            try:
                with _com_regras_no_synth(v, texto_v4):
                    t0 = time.monotonic()
                    r = await responder(graph, por_id[qid])
                    duracao_total = time.monotonic() - t0
            except Exception as exc:  # excecao que escapou do responder: infra (Emenda E-B03)
                if idx == 1:
                    raise _falha_inicial(qid, v, amostra, type(exc).__name__, str(exc)) from exc
                saida["abortado_por_infra"] = _parada_por_infra(idx, qid, v, amostra, type(exc).__name__)
                log(f"[{idx:02d}/{total:02d}] {qid} a{amostra:02d} {v}: COLETA PARADA por {type(exc).__name__} "
                    f"(resultado INVALIDO, Emenda E-B03)")
                break
            if idx == 1 and r.get("falha_de_infra"):
                raise _falha_inicial(qid, v, amostra, _tipo_do_erro(r),
                                     f"erro={r.get('erro')} erros_llm={r.get('erros_llm')}")
            custo = av._custo_das_chamadas(r.get("chamadas_llm", []), settings)
            registro = {
                **r,
                "indice_execucao": idx,
                "amostra": amostra,
                "versao": v,
                "regras_sha256": av.sha256_texto(regras[v]),
                "custo_usd": custo,
                "tempo_total_s": duracao_total,
            }
            saida["respostas"].append(registro)
            saida["custo_usd"] += custo
            saida["custo_por_versao_usd"][v] += custo
            # Log sem o texto da resposta, para preservar a classificacao cega.
            rota = " -> ".join(registro.get("caminho") or []) or "(sem caminho)"
            infra = ("  INFRA " + str(registro.get("erro") or registro.get("erros_llm"))
                     if registro.get("falha_de_infra") else "")
            log(f"[{idx:02d}/{total:02d}] {qid} a{amostra:02d} {v}: {rota}  US$ {custo:.4f}  {duracao_total:.2f}s{infra}")
            # Emenda E-B03 (K = 1): QUALQUER falha de infra depois da 1a chamada (o responder
            # ja converte excecao do grafo / erro do provedor / timeout em falha_de_infra)
            # PARA a coleta na hora. A amostra que falhou fica gravada; o resultado e INVALIDO.
            if registro.get("falha_de_infra"):
                saida["abortado_por_infra"] = _parada_por_infra(idx, qid, v, amostra, _tipo_do_erro(r))
                log(f"COLETA PARADA por falha de infra em {qid} a{amostra:02d} {v} (resultado INVALIDO, Emenda E-B03)")
                break
            if saida["custo_usd"] > orcamento:
                saida["abortado_por_orcamento"] = True
                log(f"ORCAMENTO estourado (US$ {saida['custo_usd']:.4f} > {orcamento:.2f}): interrompido")
                break
        return saida
    finally:
        settings.rag_regras_versao = versao_antes
        settings.rag_limites = limites_antes
        settings.rag_enabled = rag_antes


# --- classificacao cega -----------------------------------------------------


def gerar_classificacao_cega(
    respostas_dados: dict, *, semente: int | None = None, elo: str | None = None
) -> tuple[str, dict]:
    """Embaralha as respostas e devolve (yaml_cego, mapa_dict).

    Emenda M-01: `semente` e `elo` sao sorteados com `secrets` (os parametros so
    existem para teste). A semente vai SO no mapa; o YAML cego leva so `elo` +
    `itens` (codigo, pergunta_id, pergunta, resposta, classe, observacao): sem
    versao, hash, amostra, indice, custo, tempo, trechos nem semente."""
    lista = respostas_dados.get("respostas") or []
    if not lista:
        raise ValueError("respostas.json nao tem respostas para classificar")
    semente = secrets.randbits(BITS_SEMENTE) if semente is None else int(semente)
    elo = secrets.token_hex(16) if elo is None else str(elo)
    indices = list(range(len(lista)))
    random.Random(semente).shuffle(indices)
    largura = max(2, len(str(len(lista))))

    itens = []
    mapa = {}
    for pos, idx_orig in enumerate(indices, 1):
        r = lista[idx_orig]
        codigo = f"r{pos:0{largura}d}"
        texto_resp = r.get("resposta_crua")
        if texto_resp is None:
            texto_resp = r.get("resposta_final") or ""
        itens.append({
            "codigo": codigo,
            "pergunta_id": r["id"],
            "pergunta": r["pergunta"],
            "resposta": texto_resp,
            "classe": None,
            "observacao": "",
        })
        mapa[codigo] = {
            "versao": r["versao"],
            "pergunta_id": r["id"],
            "amostra": r["amostra"],
            "indice_execucao": r["indice_execucao"],
            "regras_sha256": r["regras_sha256"],
        }

    corpo = yaml.safe_dump(
        {"elo": elo, "itens": itens},
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    yaml_cego = _INSTRUCOES_CEGAS + "\n" + corpo
    mapa_dados = {
        "versao": 2,
        "semente": semente,
        "elo": elo,
        "total": len(itens),
        "respostas_sha256": av.sha256_texto(json.dumps(respostas_dados, sort_keys=True, ensure_ascii=False)),
        "mapa": mapa,
    }
    return yaml_cego, mapa_dados


# --- avaliacao dos criterios pre-registrados --------------------------------


def normalizar_classe(pergunta_id: str, valor) -> str | None:
    if not isinstance(valor, str):
        return None
    return _CLASSE_NORMALIZADA.get(pergunta_id, {}).get(av.normalizar(valor))


def trechos_trazem_regra(trechos: Sequence[dict], item_gabarito: dict) -> bool:
    """Os trechos recebidos contem todas as secoes-fonte da pergunta no gabarito?"""
    from orchestrator.graph.rag_specialist import codigo_pop

    esperadas = [
        (codigo_pop(arq).upper(), av.normalizar(sec))
        for arq, sec in zip(item_gabarito["arquivo_fonte"], item_gabarito["secao_fonte"], strict=True)
    ]
    achadas = {
        (str(t.get("pop") or "").strip().upper(), av.normalizar(t.get("secao") or ""))
        for t in trechos
    }
    return bool(esperadas) and all(par in achadas for par in esperadas)


def diz_que_manual_nao_cobre(resposta: str | None) -> bool:
    """Criterio 3: resposta diz que o manual nao cobre o assunto."""
    from orchestrator.graph.rag_specialist import FRASE_NAO_COBRE

    texto = av.normalizar(resposta or "")
    if not texto:
        return False
    return av.normalizar(FRASE_NAO_COBRE) in texto or bool(_DIZ_NAO_COBRE.search(texto))


def _validar_classificacao(classificacao_dados: dict, mapa_dados: dict) -> dict[str, str]:
    """Confere que TODOS os codigos do mapa estao presentes e marcados com classe valida."""
    mapa = mapa_dados.get("mapa") or {}
    itens = classificacao_dados.get("itens") or []
    if not mapa or not itens:
        raise ValueError("arquivo de classificacao ou mapa vazio")

    por_codigo: dict[str, dict] = {}
    duplicados = []
    for item in itens:
        cod = item.get("codigo")
        if cod in por_codigo:
            duplicados.append(str(cod))
        por_codigo[cod] = item
    if duplicados:
        raise ValueError(f"codigos duplicados na classificacao: {', '.join(duplicados)}")

    faltando = sorted(set(mapa) - set(por_codigo))
    extras = sorted(set(por_codigo) - set(mapa))
    if faltando:
        raise ValueError(f"codigos do mapa ausentes na classificacao: {', '.join(faltando)}")
    if extras:
        raise ValueError(f"codigos desconhecidos na classificacao: {', '.join(extras)}")

    pendentes = []
    invalidas = []
    classes: dict[str, str] = {}
    for cod in sorted(mapa):
        m = mapa[cod]
        item = por_codigo[cod]
        qid = m["pergunta_id"]
        if item.get("pergunta_id") != qid:
            raise ValueError(f"{cod}: pergunta_id {item.get('pergunta_id')!r} difere do mapa {qid!r}")
        raw = item.get("classe")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            pendentes.append(cod)
            continue
        norm = normalizar_classe(qid, raw)
        if norm is None:
            invalidas.append(f"{cod} ({qid}: {raw!r}, validas: {' | '.join(CLASSES_VALIDAS[qid])})")
            continue
        classes[cod] = norm

    if pendentes:
        raise ValueError(f"classificacao incompleta ({len(pendentes)} pendente(s)): {', '.join(pendentes)}")
    if invalidas:
        raise ValueError(f"classe invalida em: {'; '.join(invalidas)}")
    return classes


def _checar_integridade(
    respostas_dados: dict,
    classificacao_dados: dict,
    mapa_dados: dict,
    *,
    indice_meta_m8: dict | None,
    caminho_v4: Path,
) -> list[str]:
    from orchestrator.graph import rag_specialist

    problemas = []
    if av.sha256_texto(rag_specialist.REGRAS_DO_MANUAL) != HASH_REGRAS_V1:
        problemas.append("regras v1 mudaram depois do pre-registro")
    try:
        carregar_regras_v4(caminho_v4)
    except (FileNotFoundError, ValueError) as exc:
        problemas.append(f"regras v4 invalidas: {exc}")

    h_resp = av.sha256_texto(json.dumps(respostas_dados, sort_keys=True, ensure_ascii=False))
    if mapa_dados.get("respostas_sha256") != h_resp:
        problemas.append("o mapa cego nao corresponde a este respostas.json")
    elo_cego, elo_mapa = classificacao_dados.get("elo"), mapa_dados.get("elo")
    if not elo_cego or not elo_mapa or elo_cego != elo_mapa:
        problemas.append("elo ausente ou diferente entre o arquivo cego e o mapa")

    h = respostas_dados.get("hashes") or {}
    if h.get("v1_regras_do_manual") != HASH_REGRAS_V1:
        problemas.append("hash v1 gravado em respostas.json difere do pre-registro")
    if h.get("v4_regras_do_manual") != HASH_REGRAS_V4 or h.get("v4_arquivo_proposta") != HASH_ARQUIVO_V4:
        problemas.append("hash v4 gravado em respostas.json difere do pre-registro")

    if indice_meta_m8 is not None:
        meta = (respostas_dados.get("config") or {}).get("indice_meta")
        if meta != indice_meta_m8:
            problemas.append("indice diferente do da Missao 8 (indice_meta)")

    if respostas_dados.get("abortado_por_orcamento"):
        problemas.append("coleta abortada por orcamento")
    if respostas_dados.get("abortado_por_infra"):
        problemas.append(f"coleta abortada por falha de infra no meio: {respostas_dados['abortado_por_infra']}")

    lista = respostas_dados.get("respostas") or []
    if len(lista) != TOTAL_RESPOSTAS:
        problemas.append(f"numero de respostas {len(lista)} != esperado {TOTAL_RESPOSTAS}")

    por_idx = {}
    slots = set()
    for r in lista:
        idx = r.get("indice_execucao")
        v = r.get("versao")
        qid = r.get("id")
        if idx in por_idx:
            problemas.append(f"indice_execucao duplicado: {idx}")
        por_idx[idx] = r
        slots.add((v, qid, r.get("amostra")))
        if v not in HASH_REGRAS_PRE_REGISTRO or r.get("regras_sha256") != HASH_REGRAS_PRE_REGISTRO[v]:
            problemas.append(f"resposta idx={idx} ({v}): hash das regras difere do pre-registro")
        if r.get("etapa2_aplicada"):
            problemas.append(f"resposta idx={idx} ({v}): etapa 2 aplicada indevidamente")
        if r.get("falha_de_infra"):
            problemas.append(f"resposta idx={idx} ({v}): falha de infra (Emenda E-B03: invalida a coleta)")

    esperados = {(v, qid, a) for a in range(1, N_AMOSTRAS + 1) for qid in PERGUNTAS_IDS for v in VERSOES}
    if slots != esperados:
        problemas.append("amostras/versoes/perguntas nao formam a grade completa 2 x 2 x 10")

    ordenados = [por_idx[i] for i in sorted(por_idx) if i is not None]
    if ordenados and any(r.get("versao") != VERSOES[i % len(VERSOES)] for i, r in enumerate(ordenados)):
        problemas.append("ordem de execucao nao e intercalada (v1, v4, v1, v4...)")

    for cod, m in (mapa_dados.get("mapa") or {}).items():
        r = por_idx.get(m.get("indice_execucao"))
        if r is None or (r.get("versao"), r.get("id"), r.get("amostra"), r.get("regras_sha256")) != (
            m.get("versao"), m.get("pergunta_id"), m.get("amostra"), m.get("regras_sha256")
        ):
            problemas.append(f"mapa {cod} nao bate com a resposta de indice_execucao={m.get('indice_execucao')}")

    return problemas


def avaliar_resultado(
    respostas_dados: dict,
    classificacao_dados: dict,
    mapa_dados: dict,
    gabarito: Sequence[dict],
    *,
    indice_meta_m8: dict | None = None,
    caminho_v4: Path = CAMINHO_PROPOSTA_V4,
) -> dict:
    """Junta classificacao cega + mapa + respostas e aplica os criterios 1-3."""
    classes = _validar_classificacao(classificacao_dados, mapa_dados)
    problemas = _checar_integridade(
        respostas_dados, classificacao_dados, mapa_dados, indice_meta_m8=indice_meta_m8, caminho_v4=caminho_v4
    )
    g_id = {g["id"]: g for g in filtrar_gabarito(gabarito, PERGUNTAS_IDS)}
    por_idx = {r["indice_execucao"]: r for r in respostas_dados.get("respostas", [])}
    mapa = mapa_dados["mapa"]

    grupos = {
        v: {
            qid: {
                "n": 0,
                "acertos": 0,
                "erros": 0,
                "classes": {c: 0 for c in CLASSES_VALIDAS[qid]},
                "falhas_de_infra": [],
                "fora_do_rag": [],
                "falsos_nao_cobre": [],
                "erros_detalhe": [],
            }
            for qid in PERGUNTAS_IDS
        }
        for v in VERSOES
    }
    tempos_synth: dict[str, list[float]] = {v: [] for v in VERSOES}

    for cod in sorted(mapa):
        m = mapa[cod]
        v, qid, amostra, idx = m["versao"], m["pergunta_id"], m["amostra"], m["indice_execucao"]
        if v not in grupos or qid not in grupos[v]:
            continue
        r = por_idx.get(idx) or {}
        classe = classes[cod]
        grp = grupos[v][qid]
        grp["n"] += 1
        grp["classes"][classe] += 1

        infra = bool(r.get("falha_de_infra"))
        fora_rag = not bool(r.get("rag_acionado"))
        erro_classe = classe != CLASSE_CERTA[qid]
        motivos = []
        if erro_classe:
            motivos.append(f"classe={classe}")
        if infra:
            motivos.append("falha_de_infra")
            grp["falhas_de_infra"].append({"codigo": cod, "amostra": amostra, "erro": r.get("erro") or r.get("erros_llm")})
        if fora_rag:
            motivos.append("fora_do_rag")
            grp["fora_do_rag"].append({"codigo": cod, "amostra": amostra, "caminho": r.get("caminho") or []})

        if motivos:
            grp["erros"] += 1
            grp["erros_detalhe"].append({"codigo": cod, "amostra": amostra, "classe": classe, "motivos": motivos})
        else:
            grp["acertos"] += 1

        texto = r.get("resposta_crua")
        if texto is None:
            texto = r.get("resposta_final") or ""
        if trechos_trazem_regra(r.get("trechos") or [], g_id[qid]) and diz_que_manual_nao_cobre(texto):
            grp["falsos_nao_cobre"].append({"codigo": cod, "amostra": amostra, "pergunta_id": qid})

        if r.get("tempo_synth_s") is not None:
            tempos_synth[v].append(float(r["tempo_synth_s"]))

    erros_v1_q02 = grupos["v1"]["q02"]["erros"]
    erros_v4_q02 = grupos["v4"]["q02"]["erros"]
    erros_v4_q04 = grupos["v4"]["q04"]["erros"]

    q02_sem_conclusao = erros_v1_q02 == 0
    c1_passa = (not q02_sem_conclusao) and (erros_v4_q02 <= 1) and (erros_v4_q02 < erros_v1_q02)
    c2_passa = erros_v4_q04 == 0
    falsos_nao_cobre_v4 = [x for qid in PERGUNTAS_IDS for x in grupos["v4"][qid]["falsos_nao_cobre"]]
    c3_passa = not falsos_nao_cobre_v4

    valido = not problemas
    passa_no_sinal = valido and c1_passa and c2_passa and c3_passa

    latencia = {
        v: {"n": len(ts), "p50": m10.percentil(ts, 0.50), "p95": m10.percentil(ts, 0.95)} if ts else None
        for v, ts in tempos_synth.items()
    }
    return {
        "valido": valido,
        "problemas": problemas,
        "semente": mapa_dados.get("semente"),
        "grupos": grupos,
        "q02_sem_conclusao": q02_sem_conclusao,
        "criterios": {
            "c1_q02": {
                "passa": c1_passa,
                "sem_conclusao": q02_sem_conclusao,
                "erros_v1": erros_v1_q02,
                "erros_v4": erros_v4_q02,
            },
            "c2_q04": {
                "passa": c2_passa,
                "erros_v1": grupos["v1"]["q04"]["erros"],
                "erros_v4": erros_v4_q04,
            },
            "c3_sem_falso_nao_cobre_v4": {
                "passa": c3_passa,
                "ocorrencias": falsos_nao_cobre_v4,
            },
        },
        "falhas_de_infra": [
            {"versao": v, "pergunta_id": qid, **x}
            for v in VERSOES for qid in PERGUNTAS_IDS for x in grupos[v][qid]["falhas_de_infra"]
        ],
        "fora_do_rag": [
            {"versao": v, "pergunta_id": qid, **x}
            for v in VERSOES for qid in PERGUNTAS_IDS for x in grupos[v][qid]["fora_do_rag"]
        ],
        "passa_no_sinal": passa_no_sinal,
        "custo_total_usd": float(respostas_dados.get("custo_usd", 0.0)),
        "custo_por_versao_usd": dict(respostas_dados.get("custo_por_versao_usd") or {}),
        "latencia_synth_informativa": latencia,
    }


def relatorio(res: dict) -> str:
    g = res["grupos"]
    linhas = [
        "| Pergunta | Versão | Certo | Errado (classe) | AMBÍGUA | Infra | Fora do RAG | Erros totais | Falso \"não cobre\" |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for qid in PERGUNTAS_IDS:
        certa = CLASSE_CERTA[qid]
        errada = "ACEITA" if qid == "q02" else "TROCA"
        for v in VERSOES:
            x = g[v][qid]
            linhas.append(
                f"| {qid} | {v} | {x['classes'][certa]} ({certa}) | {x['classes'][errada]} ({errada}) "
                f"| {x['classes']['AMBÍGUA']} | {len(x['falhas_de_infra'])} | {len(x['fora_do_rag'])} "
                f"| {x['erros']}/{x['n']} | {len(x['falsos_nao_cobre'])} |"
            )

    cr = res["criterios"]
    c1, c2, c3 = cr["c1_q02"], cr["c2_q04"], cr["c3_sem_falso_nao_cobre_v4"]
    linhas.append("")
    if c1["sem_conclusao"]:
        linhas.append(
            f"- 1) q02: SEM CONCLUSÃO — v1 errou 0 de 10 na q02: o erro não apareceu nesta amostra e o "
            f"critério 1 não decide nada (sem conclusão sobre a q02). (v4: {c1['erros_v4']}/10 erros)"
        )
    else:
        linhas.append(
            f"- 1) q02 (v4 ≤ 1/10 e v4 < v1): {'sim' if c1['passa'] else 'NÃO'} "
            f"(v4={c1['erros_v4']}/10, v1={c1['erros_v1']}/10)"
        )
    linhas.append(
        f"- 2) q04 (v4 = 0/10): {'sim' if c2['passa'] else 'NÃO'} "
        f"(v4={c2['erros_v4']}/10, v1={c2['erros_v1']}/10)"
    )
    ocor = ", ".join(f"{x['codigo']} ({x['pergunta_id']} a{x['amostra']:02d})" for x in c3["ocorrencias"])
    linhas.append(
        f"- 3) nenhum falso \"não cobre\" na v4 (com regra nos trechos): {'sim' if c3['passa'] else 'NÃO'}"
        + (f" ({ocor})" if ocor else "")
    )

    if res["falhas_de_infra"]:
        itens = ", ".join(f"{x['codigo']} ({x['versao']} {x['pergunta_id']} a{x['amostra']:02d})"
                          for x in res["falhas_de_infra"])
        linhas.append(f"- Falhas de infraestrutura (invalidam a coleta, Emenda E-B03): {itens}")
    if res["fora_do_rag"]:
        itens = ", ".join(f"{x['codigo']} ({x['versao']} {x['pergunta_id']} a{x['amostra']:02d})"
                          for x in res["fora_do_rag"])
        linhas.append(f"- Perguntas que não foram ao RAG (contam como erro): {itens}")

    lat = res.get("latencia_synth_informativa") or {}
    partes = [f"{v} p50 {x['p50']:.2f} s / p95 {x['p95']:.2f} s (n={x['n']})" for v, x in lat.items() if x]
    if partes:
        linhas.append("- Latência do synth (informativo, não decide): " + "; ".join(partes))

    if res["problemas"]:
        linhas.append("\n**Resultado INVÁLIDO** (integridade): " + "; ".join(res["problemas"]))

    if not res["valido"]:
        veredito = "INVÁLIDO (não passa no sinal)"
    elif res["passa_no_sinal"]:
        veredito = "v4 PASSA NO SINAL (justifica planejar a Missão 11 completa; não adota ainda)"
    elif res["q02_sem_conclusao"]:
        veredito = "v4 NÃO passa no sinal (sem conclusão sobre a q02)"
    else:
        veredito = "v4 NÃO passa no sinal"

    linhas.append(
        f"\n**Veredito pelo pré-registro: {veredito}.** "
        f"Custo total medido: US$ {res['custo_total_usd']:.4f} (semente cega: {res['semente']})."
    )
    return "\n".join(linhas)


# --- plano e projecao de custo ----------------------------------------------


def _custo_real_m10() -> dict:
    """Custo REAL da v1 na Missao 10 (r1 e r2) para q02, q04 e media geral."""
    por_q: dict[str, list[float]] = {qid: [] for qid in PERGUNTAS_IDS}
    todas: list[float] = []
    for r in m10.RODADAS:
        pr, _ = m10.caminhos("v1", r)
        if not pr.is_file():
            return {}
        dados = json.loads(pr.read_text(encoding="utf-8"))
        for p in dados.get("perguntas", []):
            c = float(p.get("custo_usd", 0.0))
            todas.append(c)
            if p.get("id") in por_q:
                por_q[p["id"]].append(c)
    if not all(por_q.values()):
        return {}
    medias = {qid: sum(vs) / len(vs) for qid, vs in por_q.items()}
    medias["par_medio"] = sum(medias[qid] for qid in PERGUNTAS_IDS) / len(PERGUNTAS_IDS)
    medias["geral_20"] = sum(todas) / max(1, len(todas))
    return medias


def projecao_custo(settings, *, caminho_v4: Path = CAMINHO_PROPOSTA_V4) -> dict:
    """Projecao baseada no custo REAL da Missao 10 (v1), somando os tokens extras
    de entrada da Regra 6 nas 20 respostas da v4."""
    from orchestrator.graph import rag_specialist

    real = _custo_real_m10()
    if not real:
        return {}
    texto_v4 = carregar_regras_v4(caminho_v4)
    delta_chars = len(texto_v4) - len(rag_specialist.REGRAS_DO_MANUAL)
    delta_tokens = delta_chars / av.CHARS_POR_TOKEN
    pe, _ = av.PRECOS.get(settings.general_model, av.PRECO_DESCONHECIDO)
    delta_v4_por_resp = (delta_tokens * pe) / 1_000_000

    n_por_versao = len(PERGUNTAS_IDS) * N_AMOSTRAS
    custo_v1 = N_AMOSTRAS * sum(real[qid] for qid in PERGUNTAS_IDS)
    delta_v4_total = n_por_versao * delta_v4_por_resp
    custo_v4 = custo_v1 + delta_v4_total
    return {
        "m10_real": real,
        "delta_chars_v4": delta_chars,
        "delta_tokens_v4": delta_tokens,
        "delta_v4_por_resposta_usd": delta_v4_por_resp,
        "v1_total_usd": custo_v1,
        "v4_total_usd": custo_v4,
        "total_usd": custo_v1 + custo_v4,
    }


def comando_pago() -> str:
    return f".venv/bin/python -m orchestrator.rag.mini_q02 --executar --orcamento {TETO_ORCAMENTO_USD:.2f}"


def mostrar_plano(settings, gabarito: Sequence[dict], *, caminho_v4: Path = CAMINHO_PROPOSTA_V4) -> int:
    from orchestrator.graph import rag_specialist

    itens = filtrar_gabarito(gabarito, PERGUNTAS_IDS)
    v1 = regras_do_mini_teste("v1", caminho_v4)
    v4 = regras_do_mini_teste("v4", caminho_v4)
    h_v1 = av.sha256_texto(v1)
    h_v4 = av.sha256_texto(v4)
    h_arq_v4 = juiz.sha256_arquivo(caminho_v4)
    meta_m8 = m10.m9.indice_meta_m8()
    meta = av._meta_do_indice(settings) or {}

    print("Mini-teste q02 e q04 - v1 x v4 (proposta Antigravity) (NADA executado)")
    print(
        f"indice   : {settings.rag_index_path}; contextos_sha256 {meta.get('contextos_sha256')}; "
        f"indice_meta {'IGUAL' if meta and meta == meta_m8 else 'DIFERENTE'} ao da Missao 8"
    )
    print(
        f"busca    : modo {settings.rag_search_mode}, top_k {settings.rag_top_k}, rerank "
        f"{settings.rag_rerank_model or 'nao'}; supervisor {settings.router_model} (temp 0), "
        f"synth {settings.general_model} (sem temperatura fixa)"
    )
    print(
        f"producao : padrao intacto (settings.rag_regras_versao={settings.rag_regras_versao!r}; "
        f"REGRAS_POR_VERSAO={tuple(rag_specialist.REGRAS_POR_VERSAO)})"
    )
    try:
        nome_v4 = str(caminho_v4.relative_to(REPO_DIR))
    except ValueError:
        nome_v4 = str(caminho_v4)
    print(f"regras v1: sha256 {h_v1} ({'= pre-registro' if h_v1 == HASH_REGRAS_V1 else 'DIFERENTE'})")
    print(
        f"regras v4: arquivo {nome_v4} sha256 {h_arq_v4} "
        f"({'= pre-registro' if h_arq_v4 == HASH_ARQUIVO_V4 else 'DIFERENTE'})"
    )
    print(
        f"           texto injetado sha256 {h_v4} ({'= pre-registro' if h_v4 == HASH_REGRAS_V4 else 'DIFERENTE'}); "
        f"comeca exatamente pela v1: {'sim' if v4.startswith(v1) else 'NAO'} (+{len(v4) - len(v1)} chars)"
    )
    print(
        f"desenho  : perguntas {', '.join(g['id'] for g in itens)}; N={N_AMOSTRAS} por pergunta por versao "
        f"({TOTAL_RESPOSTAS} respostas); ordem intercalada v1, v4, v1, v4...; SEM juiz pago"
    )
    proj = projecao_custo(settings, caminho_v4=caminho_v4)
    if proj:
        r = proj["m10_real"]
        print(
            f"projecao : pelo custo REAL da Missao 10 (v1): q02 US$ {r['q02']:.6f}, q04 US$ {r['q04']:.6f} "
            f"(media do par US$ {r['par_medio']:.4f}/resposta)"
        )
        print(
            f"           20 v1 = US$ {proj['v1_total_usd']:.4f}; 20 v4 = US$ {proj['v4_total_usd']:.4f} "
            f"(+{proj['delta_tokens_v4']:.0f} tok entrada/resp, +US$ {proj['v4_total_usd'] - proj['v1_total_usd']:.4f}) "
            f"-> TOTAL PROJETADO = US$ {proj['total_usd']:.4f}"
        )
    else:
        print("projecao : arquivos da Missao 10 ausentes (estimativa nominal ~US$ 0.0018 x 40 = US$ 0.072)")
    print(
        f"orcamento: teto maximo US$ {TETO_ORCAMENTO_USD:.2f} (CLI recusa --orcamento > {TETO_ORCAMENTO_USD:.2f}; "
        f"corte depois da chamada que estourar; INVALIDO sem nova coleta)"
    )
    print(
        "parada   : QUALQUER falha de infra depois da 1a chamada para a coleta (INVALIDO); 1 nova coleta "
        "completa so apos a 1a INVALIDA por infra; FalhaInicial repete 1 vez (contadores separados)"
    )
    try:
        rel_dir = DIR_SAIDA.relative_to(av.ORCHESTRATOR_DIR)
    except ValueError:
        rel_dir = DIR_SAIDA
    print(f"saidas   : {rel_dir}/respostas.json, classificacao-cega.yaml, mapa-cego.json")
    print("comandos (de dentro de orchestrator/, NESTA ordem):")
    print(f"  1. (pago)   {comando_pago()}")
    print("  2. (gratis) .venv/bin/python -m orchestrator.rag.mini_q02 --classificar-arquivo")
    print(f"  3. (cego)   o Max cola SO {rel_dir}/classificacao-cega.yaml no chat; o Claude preenche `classe` nos "
          f"{TOTAL_RESPOSTAS} itens; o Max confere (mapa-cego.json fechado ate la)")
    print("  4. (gratis) .venv/bin/python -m orchestrator.rag.mini_q02 --resultado")
    if av._aviso_tracing():
        print("AVISO    : tracing do LangSmith ligado - perguntas, trechos e respostas vao para o LangSmith")
    if not settings.openrouter_api_key:
        print("AVISO    : ORCHESTRATOR_OPENROUTER_API_KEY ausente (rode de dentro de orchestrator/, com o .env)")
    return 0


# --- CLI --------------------------------------------------------------------


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--executar", action="store_true", help="coleta paga: 40 respostas intercaladas (OpenRouter)")
    p.add_argument("--classificar-arquivo", action="store_true", help="gera classificacao-cega.yaml e mapa-cego.json (gratis)")
    p.add_argument("--resultado", action="store_true", help="junta classificacao + mapa e aplica criterios 1-3 (gratis)")
    p.add_argument("--orcamento", type=float, default=None, help=f"US$ maximo no --executar (<= {TETO_ORCAMENTO_USD:.2f})")
    p.add_argument("--saida", type=Path, default=None, help="JSON de saida do --executar")
    p.add_argument("--respostas", type=Path, default=None, help="JSON de respostas (para --classificar-arquivo ou --resultado)")
    p.add_argument("--saida-cega", type=Path, default=None, help="YAML cego de saida (so --classificar-arquivo)")
    p.add_argument("--saida-mapa", type=Path, default=None, help="JSON do mapa cego (so --classificar-arquivo)")
    p.add_argument("--classificacao", type=Path, default=None, help="YAML cego preenchido (so --resultado)")
    p.add_argument("--mapa", type=Path, default=None, help="JSON do mapa cego (so --resultado)")
    a = p.parse_args(argv)

    if sum((a.executar, a.classificar_arquivo, a.resultado)) > 1:
        p.error("--executar, --classificar-arquivo e --resultado sao exclusivos")

    if a.executar:
        if any(x is not None for x in (a.respostas, a.saida_cega, a.saida_mapa, a.classificacao, a.mapa)):
            p.error("--respostas/--saida-cega/--saida-mapa/--classificacao/--mapa nao valem com --executar")
        orc = TETO_ORCAMENTO_USD if a.orcamento is None else a.orcamento
        if not 0 < orc <= TETO_ORCAMENTO_USD:
            p.error(f"--orcamento {orc} fora do pre-registrado (0 < orcamento <= {TETO_ORCAMENTO_USD:.2f})")
        a.orcamento = orc
        a.saida = a.saida or RESPOSTAS_PADRAO
        return a

    if a.classificar_arquivo:
        if any(x is not None for x in (a.orcamento, a.saida, a.classificacao, a.mapa)):
            p.error("--orcamento/--saida/--classificacao/--mapa nao valem com --classificar-arquivo")
        a.respostas = a.respostas or RESPOSTAS_PADRAO
        a.saida_cega = a.saida_cega or CLASSIFICACAO_PADRAO
        a.saida_mapa = a.saida_mapa or MAPA_PADRAO
        return a

    if a.resultado:
        if any(x is not None for x in (a.orcamento, a.saida, a.saida_cega, a.saida_mapa)):
            p.error("--orcamento/--saida/--saida-cega/--saida-mapa nao valem com --resultado")
        a.respostas = a.respostas or RESPOSTAS_PADRAO
        a.classificacao = a.classificacao or CLASSIFICACAO_PADRAO
        a.mapa = a.mapa or MAPA_PADRAO
        return a

    # Modo plano (gratis, padrao): nenhuma flag de execucao/classificacao/resultado.
    if any(x is not None for x in (a.orcamento, a.saida, a.respostas, a.saida_cega, a.saida_mapa,
                                    a.classificacao, a.mapa)):
        p.error("opcoes extras exigem --executar, --classificar-arquivo ou --resultado")
    return a


def ler_falhas_iniciais(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get("falhas_iniciais") or [])


def _registrar_falha_inicial(path: Path, anteriores: list[dict], exc: BaseException) -> list[dict]:
    falhas = [*anteriores, {
        "estado": ESTADO_FALHA_INICIAL,
        "tentativa": len(anteriores) + 1,
        "data": datetime.now().astimezone().isoformat(timespec="seconds"),
        "erro_tipo": getattr(exc, "erro_tipo", type(exc).__name__),
    }]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"falhas_iniciais": falhas}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return falhas


def _agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ler_coletas(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get("coletas") or [])


def _gravar_coletas(path: Path, coletas: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"coletas": coletas}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def decidir_nova_coleta(coletas: Sequence[dict]) -> tuple[bool, str]:
    """Emenda E-B03: libera a 1a coleta; libera UMA nova coleta so se a unica
    anterior foi INVALIDA por infra; recusa todo o resto."""
    if not coletas:
        return True, "1a coleta"
    estado = coletas[-1].get("estado")
    if len(coletas) < MAX_COLETAS and estado == ESTADO_INFRA_1A:
        return True, "nova coleta completa (unica), apos coleta INVALIDA por infra"
    motivos = {
        ESTADO_INICIADA: "uma coleta foi iniciada e interrompida sem registro (resultado INVALIDO)",
        ESTADO_CONCLUIDA: "ja houve uma coleta concluida",
        ESTADO_ORCAMENTO: "a coleta foi INVALIDA por orcamento, que nao da direito a nova coleta",
        ESTADO_INFRA_2A: "a 2a coleta tambem foi INVALIDA por infra: exploracao encerrada sem resultado",
        ESTADO_INFRA_1A: "a nova coleta por infra ja foi usada",
    }
    return False, motivos.get(estado, f"estado de coleta desconhecido {estado!r}")


def _cmd_executar(args, settings, gabarito: Sequence[dict]) -> int:
    registro_fi = DIR_SAIDA / NOME_REGISTRO_FALHA_INICIAL
    registro_col = DIR_SAIDA / NOME_REGISTRO_COLETAS
    coletas = ler_coletas(registro_col)
    pode, motivo = decidir_nova_coleta(coletas)
    if not pode:
        print(f"erro: {motivo} ({registro_col}): nao ha nova coleta nesta exploracao (Emenda E-B03)", file=sys.stderr)
        return 2
    anteriores = ler_falhas_iniciais(registro_fi)
    if len(anteriores) >= MAX_TENTATIVAS_FALHA_INICIAL:
        print(f"erro: ja houve {len(anteriores)} FalhaInicial registradas em {registro_fi}: a repeticao unica "
              "foi usada; nao ha nova coleta nesta exploracao (Emenda B-03)", file=sys.stderr)
        return 2
    if not settings.openrouter_api_key:
        print("erro: ORCHESTRATOR_OPENROUTER_API_KEY ausente (rode de dentro de orchestrator/, com o .env)", file=sys.stderr)
        return 2
    if args.saida.exists():
        print(f"erro: {args.saida} ja existe: nao sobrescrevo resultado medido", file=sys.stderr)
        return 2
    if not Path(settings.rag_index_path).is_file():
        print(f"erro: indice ausente em {settings.rag_index_path} (rode python -m orchestrator.rag.ingest)", file=sys.stderr)
        return 2
    if av._aviso_tracing():
        print("AVISO: tracing do LangSmith ligado - perguntas, trechos e respostas vao para o LangSmith")
    tentativa = len(anteriores) + 1
    n_coleta = len(coletas) + 1
    coletas.append({"coleta": n_coleta, "estado": ESTADO_INICIADA, "saida": str(args.saida), "inicio": _agora(),
                    "tentativa_falha_inicial": tentativa})
    _gravar_coletas(registro_col, coletas)  # antes de qualquer chamada paga
    try:
        dados = asyncio.run(etapa_coleta(gabarito, orcamento=args.orcamento))
    except av.FalhaInicial as exc:
        # 1a chamada falhou e nada foi gravado: sai do registro de coletas e entra no de
        # FalhaInicial (contadores SEPARADOS: nao consome a nova coleta por infra).
        _gravar_coletas(registro_col, coletas[:-1])
        falhas = _registrar_falha_inicial(registro_fi, anteriores, exc)
        resto = MAX_TENTATIVAS_FALHA_INICIAL - len(falhas)
        print(f"erro: {exc} - nada gravado; FalhaInicial {len(falhas)}/{MAX_TENTATIVAS_FALHA_INICIAL} registrada em "
              f"{registro_fi} ({'pode repetir 1 vez' if resto > 0 else 'repeticao esgotada: sem nova coleta'})",
              file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as exc:
        # So as pre-checagens de etapa_coleta levantam estes erros, antes da 1a chamada paga.
        _gravar_coletas(registro_col, coletas[:-1])
        print(f"erro: {exc} - nada gravado", file=sys.stderr)
        return 2
    dados["coleta"] = n_coleta
    dados["coletas_anteriores"] = coletas[:-1]
    dados["tentativa"] = tentativa
    dados["falhas_iniciais_anteriores"] = anteriores
    av._gravar(args.saida, dados)
    parada = dados.get("abortado_por_infra")
    if parada:
        estado = ESTADO_INFRA_1A if n_coleta < MAX_COLETAS else ESTADO_INFRA_2A
    elif dados.get("abortado_por_orcamento"):
        estado = ESTADO_ORCAMENTO
    else:
        estado = ESTADO_CONCLUIDA
    coletas[-1].update({"estado": estado, "fim": _agora(), "parou_em": parada,
                        "erro_tipo": parada.get("erro_tipo") if parada else None})
    _gravar_coletas(registro_col, coletas)
    print(f"\nUS$ {dados['custo_usd']:.4f} -> {args.saida}")
    if estado == ESTADO_CONCLUIDA:
        return 0
    if estado == ESTADO_INFRA_1A:
        print("COLETA INVALIDA por infra (1a vez): resultado INVALIDO; UMA nova coleta completa (40 do zero) e "
              "permitida, com OUTRA --saida (Emenda E-B03)")
    elif estado == ESTADO_INFRA_2A:
        print("COLETA INVALIDA por infra (2a vez): exploracao ENCERRADA sem resultado; nao ha 3a coleta (Emenda E-B03)")
    else:
        print("COLETA INVALIDA por orcamento: sem direito a nova coleta (Emenda E-B03)")
    if parada:
        print(f"REGISTRAR NO PRE-REGISTRO (§8): {coletas[-1]['fim']} - coleta {n_coleta} parou em "
              f"{parada['id']} {parada['versao']} amostra {parada['amostra']} "
              f"(indice {parada['indice_execucao']}), erro {parada['erro_tipo']}")
    return 1


def _cmd_classificar(args) -> int:
    if not args.respostas.is_file():
        print(f"erro: arquivo de respostas ausente em {args.respostas}", file=sys.stderr)
        return 2
    for destino in (args.saida_cega, args.saida_mapa):
        if destino.exists():
            print(f"erro: {destino} ja existe: nao sobrescrevo classificacao/mapa", file=sys.stderr)
            return 2
    respostas = json.loads(args.respostas.read_text(encoding="utf-8"))
    try:
        yaml_cego, mapa_dados = gerar_classificacao_cega(respostas)
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    args.saida_cega.parent.mkdir(parents=True, exist_ok=True)
    args.saida_cega.write_text(yaml_cego, encoding="utf-8")
    av._gravar(args.saida_mapa, mapa_dados)
    # Nao imprime semente nem elo: este log pode ser colado no chat.
    print(f"classificacao cega ({mapa_dados['total']} itens) -> {args.saida_cega}")
    print(f"mapa separado (NAO abrir nem colar ate as {mapa_dados['total']} classes) -> {args.saida_mapa}")
    return 0


def _cmd_resultado(args, gabarito: Sequence[dict]) -> int:
    for nome, p in (("respostas", args.respostas), ("classificacao", args.classificacao), ("mapa", args.mapa)):
        if not p.is_file():
            print(f"erro: arquivo de {nome} ausente em {p}", file=sys.stderr)
            return 2
    respostas = json.loads(args.respostas.read_text(encoding="utf-8"))
    classificacao = yaml.safe_load(args.classificacao.read_text(encoding="utf-8")) or {}
    mapa = json.loads(args.mapa.read_text(encoding="utf-8"))
    try:
        res = avaliar_resultado(respostas, classificacao, mapa, gabarito, indice_meta_m8=m10.m9.indice_meta_m8())
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    print(relatorio(res))
    return 0 if res["valido"] else 1


def main(argv=None) -> int:
    args = parse_args(argv)
    from orchestrator.config import settings

    gabarito = av.carregar_gabarito()
    if args.executar:
        return _cmd_executar(args, settings, gabarito)
    if args.classificar_arquivo:
        return _cmd_classificar(args)
    if args.resultado:
        return _cmd_resultado(args, gabarito)
    try:
        return mostrar_plano(settings, gabarito)
    except (FileNotFoundError, ValueError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
