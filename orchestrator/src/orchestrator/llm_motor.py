"""O "motor" das chamadas do agente: OpenRouter (padrao) ou a API direta da DeepSeek.

Vale para as chamadas que usam `settings.router_model` / `settings.general_model`
no caminho da Parte 3: o supervisor, o extrator da ficha (graph/rag_limites.py) e o
redator (synthesize_final, inclusive a etapa 2 da v3, que recebe o mesmo LLM). O
especialista n8n e o juiz das medicoes NAO passam por aqui: continuam no OpenRouter.

- `ORCHESTRATOR_LLM_PROVEDOR=openrouter` (padrao): exatamente o de antes
  (base_url do OpenRouter, o modelo do settings, ORCHESTRATOR_OPENROUTER_API_KEY).
- `ORCHESTRATOR_LLM_PROVEDOR=deepseek`: base_url https://api.deepseek.com, modelo
  `deepseek-flash` (DeepSeek-V4.1-Flash-1017) com o pensamento DESLIGADO, chave
  DEEPSEEK_API_KEY. So o slug do agente (`deepseek/deepseek-chat`) e traduzido: outro
  modelo no settings com o provedor deepseek e RECUSADO (nunca troca de modelo calado).

Por que `deepseek-flash` e nao `deepseek-chat` (decisao do Max, 24/11/2026): o changelog
oficial marcou `deepseek-chat` para desligar em 24/07/2026 (apontava para o modo sem
pensamento do V4 Flash, que foi aposentado em 10/09/2026); a pagina de precos so lista
`deepseek-flash` e `deepseek-v4-pro`. E um MODELO novo, nao outra versao do V3 que o
OpenRouter serve como `deepseek/deepseek-chat` (docs/RAG.md, emenda de 24/11 da Parte 3).

Pensamento desligado de proposito: no modo de pensamento (o padrao da DeepSeek) a
`temperature` e ignorada (o extrator depende da temperatura 0) e as chamadas de
ferramenta em varios turnos exigem devolver o `reasoning_content`.

Custo: a API direta nao devolve o custo (o OpenRouter devolvia `cost`). Ele e
calculado pelos tokens do `usage` (`prompt_cache_hit_tokens`,
`prompt_cache_miss_tokens`, `completion_tokens`) com o preco oficial abaixo, SEMPRE na
tarifa de PICO (a fora de pico e a metade): o orcamento nunca subestima.

A chave nunca e impressa nem gravada: e um SecretStr do settings, entregue so ao
cliente HTTP. Nenhuma funcao daqui devolve, loga ou poe em mensagem de erro o valor.
"""

from __future__ import annotations

from collections.abc import Callable

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
PROVEDORES = ("openrouter", "deepseek")

# O slug que o settings carrega (router_model e general_model). Com o provedor deepseek,
# SO ele e traduzido para o modelo da API direta.
MODELO_DO_AGENTE = "deepseek/deepseek-chat"
DEEPSEEK_MODELO = "deepseek-flash"
DEEPSEEK_VERSAO_DOCUMENTADA = "DeepSeek-V4.1-Flash-1017"
# Corpo extra da requisicao (formato OpenAI da DeepSeek, guia "Thinking Mode").
DEEPSEEK_SEM_PENSAMENTO = {"thinking": {"type": "disabled"}}

# --- preco oficial (https://api-docs.deepseek.com/quick_start/pricing, lido em 24/11/2026) ---
FONTE_PRECO = "https://api-docs.deepseek.com/quick_start/pricing"
DATA_PRECO = "2026-11-24"
# US$ por 1M tokens, deepseek-flash. Pico: 01:00-04:00 e 06:00-10:00 UTC, seg-sex (fora
# feriados chineses); fora de pico e a metade.
PRECO_DEEPSEEK_FLASH = {
    "pico": {"entrada_cache_hit": 0.006, "entrada_cache_miss": 0.30, "saida": 1.20},
    "fora_de_pico": {"entrada_cache_hit": 0.003, "entrada_cache_miss": 0.15, "saida": 0.60},
}
TARIFA_DO_ORCAMENTO = "pico"  # conservador: a conta nunca fica abaixo da fatura
# Chamada sem NENHUM dado de uso (nem token_usage nem usage_metadata): em vez de custo
# zero (o corte por orcamento nunca dispararia), conta este valor fixo, bem acima do
# custo real de uma chamada do agente (~US$ 0,001).
CUSTO_SEM_USO_USD = 0.01
# Preco do OpenRouter usado nas medicoes antigas (avaliar_respostas.PRECOS, 19/11/2026),
# so para escalar a projecao feita com os custos reais antigos.
PRECO_OPENROUTER_ANTIGO = (0.2574, 1.0287)


class MotorIndisponivel(RuntimeError):
    """O motor pedido nao pode ser montado (chave ausente, modelo nao traduzivel)."""


def provedor(settings) -> str:
    p = getattr(settings, "llm_provedor", "openrouter")
    if p not in PROVEDORES:
        raise MotorIndisponivel(f"provedor desconhecido: {p!r} (validos: {', '.join(PROVEDORES)})")
    return p


def modelo_efetivo(settings, modelo: str) -> str:
    """O modelo que vai na requisicao. No openrouter, o do settings; no deepseek, so o
    slug do agente vira `deepseek-flash` (qualquer outro e recusado)."""
    if provedor(settings) == "openrouter":
        return modelo
    if modelo != MODELO_DO_AGENTE:
        raise MotorIndisponivel(
            f"provedor deepseek so traduz {MODELO_DO_AGENTE!r}; o settings pede {modelo!r}"
        )
    return DEEPSEEK_MODELO


def conexao(settings, modelo: str) -> dict:
    """Argumentos do ChatOpenAI (model, api_key, base_url e, no deepseek, extra_body).
    No openrouter, identico ao de antes (inclusive sem conferir a chave aqui)."""
    if provedor(settings) == "openrouter":
        return {"model": modelo, "api_key": settings.openrouter_api_key, "base_url": OPENROUTER_BASE_URL}
    chave = getattr(settings, "deepseek_api_key", None)
    if chave is None:
        raise MotorIndisponivel("DEEPSEEK_API_KEY ausente (rode de dentro de orchestrator/, com o .env)")
    return {
        "model": modelo_efetivo(settings, modelo),
        "api_key": chave,  # SecretStr: o ChatOpenAI so le o valor na hora da requisicao
        "base_url": DEEPSEEK_BASE_URL,
        "extra_body": {k: dict(v) for k, v in DEEPSEEK_SEM_PENSAMENTO.items()},
    }


def descrever(settings) -> dict:
    """O que gravar em cada medicao (nunca a chave)."""
    p = provedor(settings)
    d = {
        "provedor": p,
        "base_url": OPENROUTER_BASE_URL if p == "openrouter" else DEEPSEEK_BASE_URL,
        "modelo_efetivo_router": modelo_efetivo(settings, settings.router_model),
        "modelo_efetivo_general": modelo_efetivo(settings, settings.general_model),
    }
    if p == "deepseek":
        d.update({
            "versao_documentada": DEEPSEEK_VERSAO_DOCUMENTADA,
            "pensamento": "desligado",
            "extra_body": DEEPSEEK_SEM_PENSAMENTO,
            "custo": "calculado pelos tokens do usage",
            "tarifa_do_orcamento": TARIFA_DO_ORCAMENTO,
            "preco_usd_por_1m": PRECO_DEEPSEEK_FLASH,
            "fonte_preco": FONTE_PRECO,
            "data_preco": DATA_PRECO,
        })
    else:
        d["custo"] = "campo cost do OpenRouter (ou tokens x avaliar_respostas.PRECOS)"
    return d


# --- custo -------------------------------------------------------------------------------


def _int(x) -> int | None:
    return x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else None


def tokens_deepseek(token_usage: dict | None, usage_metadata: dict | None = None) -> dict | None:
    """(cache hit, cache miss, saida) do uso de UMA chamada; None quando nao ha NENHUMA
    contagem de tokens (nem no token_usage nem no usage_metadata): um `usage` vazio ou so
    com `cost` nao vira custo zero. Sem a divisao hit/miss, tudo conta como miss (o mais caro)."""
    uso, meta = token_usage or {}, usage_metadata or {}
    contagens = [uso.get(k) for k in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens",
                                      "prompt_cache_miss_tokens")] + [meta.get("input_tokens"), meta.get("output_tokens")]
    if all(_int(x) is None for x in contagens):
        return None
    entrada = _int(uso.get("prompt_tokens"))
    if entrada is None:
        entrada = _int(meta.get("input_tokens")) or 0
    hit, miss = _int(uso.get("prompt_cache_hit_tokens")), _int(uso.get("prompt_cache_miss_tokens"))
    if hit is None and miss is None:
        hit = _int((meta.get("input_token_details") or {}).get("cache_read")) or 0
        miss = max(entrada - hit, 0)
    elif hit is None:
        hit = max(entrada - miss, 0)
    elif miss is None:
        miss = max(entrada - hit, 0)
    saida = _int(uso.get("completion_tokens"))
    if saida is None:
        saida = _int(meta.get("output_tokens")) or 0
    return {"entrada_cache_hit": hit, "entrada_cache_miss": miss, "saida": saida}


def custo_deepseek(token_usage: dict | None, usage_metadata: dict | None = None,
                   tarifa: str = TARIFA_DO_ORCAMENTO) -> float:
    """US$ de UMA chamada pelo preco oficial (tarifa de pico por padrao)."""
    t = tokens_deepseek(token_usage, usage_metadata)
    if t is None:
        return CUSTO_SEM_USO_USD
    preco = PRECO_DEEPSEEK_FLASH[tarifa]
    return sum(t[k] * preco[k] for k in preco) / 1_000_000


def fator_vs_openrouter_antigo() -> float:
    """Quanto o deepseek-flash (pico, sem cache) custa a mais por token que o preco do
    OpenRouter das medicoes antigas: o maior dos dois (entrada, saida). So para projecao."""
    p = PRECO_DEEPSEEK_FLASH["pico"]
    pe, ps = PRECO_OPENROUTER_ANTIGO
    return max(p["entrada_cache_miss"] / pe, p["saida"] / ps)


# --- chamadas ----------------------------------------------------------------------------


def chamar_ficha(settings, fabrica: Callable | None = None):
    """A chamada do extrator da ficha (a da v1/v3: mesmo prompt, schema, temperatura 0 e
    tool_choice). No openrouter, e literalmente `limites_extracao.chamar_openrouter`."""
    from orchestrator.rag import limites_extracao as lx1

    if provedor(settings) == "openrouter" and fabrica is None:
        return lx1.chamar_openrouter(settings)
    if fabrica is None:
        from langchain_openai import ChatOpenAI as fabrica
    llm = fabrica(**conexao(settings, settings.general_model), temperature=lx1.TEMPERATURA)
    return llm.bind_tools([lx1.schema_ferramenta()], tool_choice=lx1.TOOL_CHOICE).invoke


PERGUNTA_DO_TESTE = "responda só: ok"
PERGUNTA_DO_TESTE_FICHA = "O frango congelado chegou a -15 graus, posso receber?"


def _com_deepseek(settings):
    return settings.model_copy(update={"llm_provedor": "deepseek"})


def _falha(exc: BaseException) -> dict:
    """So o TIPO do erro e o status HTTP: a mensagem pode ecoar parte da chave."""
    status = getattr(exc, "status_code", None)
    return {"ok": False, "erro_tipo": type(exc).__name__, "status_http": status if isinstance(status, int) else None}


def _resumo(resposta, modelo_pedido: str) -> dict:
    meta = getattr(resposta, "response_metadata", None) or {}
    uso, um = meta.get("token_usage"), getattr(resposta, "usage_metadata", None)
    return {
        "ok": True,
        "modelo_pedido": modelo_pedido,
        "modelo_devolvido": meta.get("model_name"),
        "tokens": tokens_deepseek(uso, um),
        "custo_usd": custo_deepseek(uso, um),
    }


def teste_conexao(settings, fabrica: Callable | None = None) -> dict:
    """PAGO (minimo): UMA chamada curtissima com o motor deepseek (mesmo que o settings
    esteja em openrouter). Devolve so: ok, modelo e custo calculado (nunca a chave, os
    cabecalhos nem o texto da resposta; so se ela comecou com "ok")."""
    from langchain_core.messages import HumanMessage

    cfg = _com_deepseek(settings)
    try:
        kw = conexao(cfg, cfg.general_model)
        if fabrica is None:
            from langchain_openai import ChatOpenAI as fabrica
        resposta = fabrica(**kw, temperature=0, max_tokens=5).invoke([HumanMessage(content=PERGUNTA_DO_TESTE)])
    except Exception as exc:  # noqa: BLE001 - so o tipo sai daqui
        return _falha(exc)
    r = _resumo(resposta, kw["model"])
    texto = resposta.content if isinstance(resposta.content, str) else ""
    r["respondeu_ok"] = texto.strip().lower().startswith("ok")
    return r


def teste_ficha(settings, fabrica: Callable | None = None) -> dict:
    """PAGO (minimo, opcional): UMA chamada do extrator da ficha com o motor deepseek,
    para saber ANTES da medicao se o tool_choice com a ferramenta nomeada funciona
    (a documentacao da DeepSeek nao diz). Devolve ok, modelo, se a ferramenta veio e o custo."""
    from orchestrator.rag import limites_extracao as lx1

    cfg = _com_deepseek(settings)
    try:
        chamar = chamar_ficha(cfg, fabrica)
        resposta = chamar(lx1.mensagens(PERGUNTA_DO_TESTE_FICHA))
    except Exception as exc:  # noqa: BLE001
        return _falha(exc)
    r = _resumo(resposta, DEEPSEEK_MODELO)
    chamadas = getattr(resposta, "tool_calls", None) or []
    r["chamou_a_ferramenta"] = any(c.get("name") == lx1.NOME_FERRAMENTA for c in chamadas)
    return r
