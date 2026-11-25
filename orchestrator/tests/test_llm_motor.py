"""O motor do agente (llm_motor.py; emenda de 24/11/2026 da Parte 3), com rede bloqueada.

1. a escolha do provedor: padrao openrouter (nada muda); deepseek troca base_url, modelo
   e chave (e desliga o pensamento) no supervisor, no extrator da ficha e no redator;
2. o custo pelos tokens (cache hit, cache miss, saida) com o preco oficial, na tarifa de pico;
3. o corte por orcamento com esse custo (A/C pela `coletar`, B pela `etapa_respostas`);
4. nenhum log, JSON de medicao ou saida de terminal contem o valor da chave (chave falsa).

Cada regra tem o seu mutante, numa COPIA do modulo (`_modulo_mutante`), e o mutante e pego.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import SecretStr
from test_rag_limites_agente import _modulo_mutante

from orchestrator import config, llm_motor
from orchestrator.config import settings
from orchestrator.rag import avaliar_respostas as av
from orchestrator.rag import medir_extracao as me
from orchestrator.rag import parte3 as p3

# Marcador unico: se aparecer em qualquer saida, a chave vazou.
CHAVE_FALSA = "sk-deepseek-FALSA-3c9e1b7a-nunca-imprimir"
USO_1 = {"prompt_tokens": 1000, "completion_tokens": 200, "prompt_cache_hit_tokens": 600,
         "prompt_cache_miss_tokens": 400}
CUSTO_USO_1_PICO = (600 * 0.006 + 400 * 0.30 + 200 * 1.20) / 1e6  # US$ 0,0003636


def _cfg(provedor="deepseek", chave=CHAVE_FALSA, **extra):
    upd = {"llm_provedor": provedor, "deepseek_api_key": SecretStr(chave) if chave else None, **extra}
    return settings.model_copy(update=upd)


@pytest.fixture
def motor_deepseek(monkeypatch):
    monkeypatch.setattr(settings, "llm_provedor", "deepseek")
    monkeypatch.setattr(settings, "deepseek_api_key", SecretStr(CHAVE_FALSA))


# =============================================================================
# 1. escolha do provedor
# =============================================================================


def problemas_escolha(m) -> list[str]:
    p = []
    o = m.conexao(_cfg("openrouter"), "deepseek/deepseek-chat")
    if (o.get("base_url"), o.get("model"), "extra_body" in o) != (m.OPENROUTER_BASE_URL, "deepseek/deepseek-chat", False):
        p.append(f"openrouter mudou: {o.get('base_url')} {o.get('model')}")
    if o.get("api_key") != settings.openrouter_api_key:
        p.append("openrouter sem a chave do OpenRouter")
    d = m.conexao(_cfg("deepseek"), "deepseek/deepseek-chat")
    if d.get("base_url") != "https://api.deepseek.com":
        p.append(f"deepseek com base_url {d.get('base_url')}")
    if d.get("model") != "deepseek-flash":
        p.append(f"deepseek com modelo {d.get('model')}")
    chave = d.get("api_key")
    if not isinstance(chave, SecretStr) or chave.get_secret_value() != CHAVE_FALSA:
        p.append("deepseek sem a DEEPSEEK_API_KEY (ou fora de SecretStr)")
    if d.get("extra_body") != {"thinking": {"type": "disabled"}}:
        p.append(f"pensamento nao desligado: {d.get('extra_body')}")
    for cfg, modelo, motivo in ((_cfg("deepseek"), "google/gemini-3.8-flash", "outro modelo"),
                                (_cfg("deepseek", chave=None), "deepseek/deepseek-chat", "sem chave")):
        try:
            m.conexao(cfg, modelo)
            p.append(f"deepseek {motivo} nao foi recusado")
        except m.MotorIndisponivel:
            pass
    return p


def test_escolha_do_provedor():
    assert problemas_escolha(llm_motor) == []


def test_padrao_e_openrouter_e_deepseek_vem_do_ambiente(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # sem .env nenhum
    assert config.Settings(_env_file=None).llm_provedor == "openrouter"
    assert config.Settings(_env_file=None).deepseek_api_key is None
    monkeypatch.setenv("ORCHESTRATOR_LLM_PROVEDOR", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", f"  {CHAVE_FALSA}  ")
    s = config.Settings(_env_file=None)
    assert s.llm_provedor == "deepseek" and s.deepseek_api_key.get_secret_value() == CHAVE_FALSA
    assert CHAVE_FALSA not in repr(s) and CHAVE_FALSA not in str(s.model_dump())
    monkeypatch.setenv("DEEPSEEK_API_KEY", "   ")
    assert config.Settings(_env_file=None).deepseek_api_key is None  # vazia vira ausente


def test_dotenv_com_deepseek_api_key_carrega(tmp_path, monkeypatch):
    """Regressao (24/11): a DEEPSEEK_API_KEY sem prefixo no .env derrubava o Settings
    (extra_forbidden) antes do campo existir. O typo continua derrubando."""
    (tmp_path / ".env").write_text(f"ORCHESTRATOR_LLM_PROVEDOR=deepseek\nDEEPSEEK_API_KEY={CHAVE_FALSA}\n")
    monkeypatch.chdir(tmp_path)
    s = config.Settings()
    assert s.llm_provedor == "deepseek" and s.deepseek_api_key.get_secret_value() == CHAVE_FALSA
    (tmp_path / ".env").write_text("ORCHESTRATOR_LLM_PROVEDR=deepseek\n")
    with pytest.raises(Exception, match="llm_provedr"):
        config.Settings()


def test_mutante_do_padrao_e_pego(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # o `settings = Settings()` da copia nao le o .env real
    mod = _modulo_mutante(monkeypatch, config, 'llm_provedor: Literal["openrouter", "deepseek"] = "openrouter"',
                          'llm_provedor: Literal["openrouter", "deepseek"] = "deepseek"')
    assert mod.Settings(_env_file=None).llm_provedor != "openrouter"


MUTANTES_ESCOLHA = {
    "base_url do openrouter no deepseek": ('"base_url": DEEPSEEK_BASE_URL,\n        "extra_body"',
                                            '"base_url": OPENROUTER_BASE_URL,\n        "extra_body"'),
    "modelo nao traduzido": ("    return DEEPSEEK_MODELO\n", "    return modelo\n"),
    "chave do openrouter no deepseek": ('"api_key": chave,', '"api_key": settings.openrouter_api_key,'),
    "pensamento ligado": ('DEEPSEEK_SEM_PENSAMENTO = {"thinking": {"type": "disabled"}}',
                          'DEEPSEEK_SEM_PENSAMENTO = {"thinking": {"type": "enabled"}}'),
    "outro modelo aceito": ("    if modelo != MODELO_DO_AGENTE:\n        raise", "    if False:\n        raise"),
}


@pytest.mark.parametrize("mutante", MUTANTES_ESCOLHA)
def test_mutante_da_escolha_e_pego(monkeypatch, mutante):
    mod = _modulo_mutante(monkeypatch, llm_motor, *MUTANTES_ESCOLHA[mutante])
    assert problemas_escolha(mod), f"mutante {mutante!r} passou"


def _graph_capturando(provedor, monkeypatch):
    """Roda o grafo inteiro (sem despacho) e devolve os kwargs de cada ChatOpenAI do no."""
    from langgraph.checkpoint.memory import MemorySaver

    from orchestrator.graph.builder import build_graph
    from orchestrator.graph.state import fresh_turn_input

    monkeypatch.setattr(settings, "llm_provedor", provedor)
    monkeypatch.setattr(settings, "deepseek_api_key", SecretStr(CHAVE_FALSA))
    criados = []
    sup = MagicMock()
    sup.bind_tools.return_value = sup
    sup.ainvoke = AsyncMock(return_value=AIMessage(content="", tool_calls=[]))
    synth = MagicMock()
    synth.ainvoke = AsyncMock(return_value=AIMessage(content="Ola!"))

    def fabrica(*args, **kwargs):
        criados.append(kwargs)
        return sup if kwargs.get("temperature") == 0 else synth

    with patch("orchestrator.graph.nodes.ChatOpenAI", side_effect=fabrica):
        final = asyncio.run(build_graph(MemorySaver()).ainvoke(
            fresh_turn_input("oi"), config={"configurable": {"thread_id": f"motor-{provedor}"}}))
    assert final["final_result"] == "Ola!"
    return criados


def test_supervisor_e_redator_seguem_o_motor(monkeypatch):
    antes = _graph_capturando("openrouter", monkeypatch)
    assert len(antes) == 2  # supervisor (temperatura 0) + redator
    assert all(k["base_url"] == llm_motor.OPENROUTER_BASE_URL and k["model"] == "deepseek/deepseek-chat"
               and "extra_body" not in k for k in antes)
    assert all(k["api_key"] == settings.openrouter_api_key for k in antes)
    novo = _graph_capturando("deepseek", monkeypatch)
    assert len(novo) == 2
    for k in novo:
        assert k["base_url"] == "https://api.deepseek.com" and k["model"] == "deepseek-flash"
        assert k["api_key"].get_secret_value() == CHAVE_FALSA
        assert k["extra_body"] == {"thinking": {"type": "disabled"}}
    assert [k.get("temperature") for k in novo] == [0, None]  # como antes: o redator sem temperatura fixa


def _payload_da_ficha(chamar) -> dict:
    binding = chamar.__self__
    return binding.bound._get_request_payload([HumanMessage(content="x")], **binding.kwargs), binding.bound


@pytest.mark.parametrize("provedor", ["openrouter", "deepseek"])
def test_extrator_da_ficha_segue_o_motor_sem_mudar_a_chamada(monkeypatch, provedor):
    """O `_chamar_padrao` do rag_limites: mesmo prompt/schema/temperatura 0/tool_choice; so
    o motor muda. Monta o ChatOpenAI REAL (sem chamar: a geracao esta bloqueada)."""
    from orchestrator.graph import rag_limites

    monkeypatch.setattr(settings, "llm_provedor", provedor)
    monkeypatch.setattr(settings, "deepseek_api_key", SecretStr(CHAVE_FALSA))
    payload, llm = _payload_da_ficha(rag_limites._chamar_padrao())
    assert payload["temperature"] == 0
    assert payload["tool_choice"] == {"type": "function", "function": {"name": "preencher_ficha"}}
    if provedor == "openrouter":
        assert (payload["model"], llm.openai_api_base) == ("deepseek/deepseek-chat", llm_motor.OPENROUTER_BASE_URL)
        assert "extra_body" not in payload
    else:
        assert (payload["model"], llm.openai_api_base) == ("deepseek-flash", "https://api.deepseek.com")
        assert payload["extra_body"] == {"thinking": {"type": "disabled"}}
        assert llm.openai_api_key.get_secret_value() == CHAVE_FALSA
    assert CHAVE_FALSA not in repr(llm)


def test_n8n_e_juiz_nao_mudam(monkeypatch, motor_deepseek):
    """Fora do pedido: o especialista n8n e o juiz continuam no OpenRouter."""
    from pathlib import Path

    from orchestrator.graph import nodes
    from orchestrator.rag import juiz

    fonte = Path(nodes.__file__).read_text(encoding="utf-8")
    assert fonte.count("llm_motor.conexao(") == 2  # supervisor e redator; o n8n nao
    assert fonte.count('base_url="https://openrouter.ai/api/v1"') == 1  # o do n8n
    fonte_juiz = Path(juiz.__file__).read_text(encoding="utf-8")
    assert 'base_url="https://openrouter.ai/api/v1"' in fonte_juiz and "llm_motor" not in fonte_juiz
    assert juiz.JUIZ_MODELO == "google/gemini-3.8-flash"  # o pre-registrado


# =============================================================================
# 2. custo pelos tokens
# =============================================================================


def problemas_custo(m) -> list[str]:
    p = []
    casos = {
        "hit/miss/saida (pico)": (m.custo_deepseek(USO_1), CUSTO_USO_1_PICO),
        "fora de pico = metade": (m.custo_deepseek(USO_1, tarifa="fora_de_pico"), CUSTO_USO_1_PICO / 2),
        "sem divisao: tudo miss": (m.custo_deepseek({"prompt_tokens": 1000, "completion_tokens": 200}),
                                   (1000 * 0.30 + 200 * 1.20) / 1e6),
        "so o usage_metadata": (m.custo_deepseek(None, {"input_tokens": 1000, "output_tokens": 200,
                                                        "input_token_details": {"cache_read": 600}}),
                                CUSTO_USO_1_PICO),
        "sem uso nenhum": (m.custo_deepseek(None, None), 0.01),
        "usage so com cost": (m.custo_deepseek({"cost": 0.5}), 0.01),
    }
    for nome, (obtido, esperado) in casos.items():
        if abs(obtido - esperado) > 1e-12:
            p.append(f"{nome}: {obtido} != {esperado}")
    return p


def test_custo_pelos_tokens():
    assert problemas_custo(llm_motor) == []


def test_preco_registrado():
    """O preco oficial lido em 24/11/2026 (docs/RAG.md); mudou -> mudar os dois juntos."""
    assert llm_motor.PRECO_DEEPSEEK_FLASH == {
        "pico": {"entrada_cache_hit": 0.006, "entrada_cache_miss": 0.30, "saida": 1.20},
        "fora_de_pico": {"entrada_cache_hit": 0.003, "entrada_cache_miss": 0.15, "saida": 0.60},
    }
    assert (llm_motor.TARIFA_DO_ORCAMENTO, llm_motor.DATA_PRECO) == ("pico", "2026-11-24")
    assert llm_motor.FONTE_PRECO == "https://api-docs.deepseek.com/quick_start/pricing"


MUTANTES_CUSTO = {
    "hit cobrado como miss": ('"pico": {"entrada_cache_hit": 0.006,', '"pico": {"entrada_cache_hit": 0.30,'),
    "orcamento na tarifa fora de pico": ('TARIFA_DO_ORCAMENTO = "pico"', 'TARIFA_DO_ORCAMENTO = "fora_de_pico"'),
    "sem uso vira zero": ("        return CUSTO_SEM_USO_USD\n", "        return 0.0\n"),
    "sem divisao vira tudo hit": ("        miss = max(entrada - hit, 0)\n    elif hit is None:",
                                  "        hit, miss = entrada, 0\n    elif hit is None:"),
}


@pytest.mark.parametrize("mutante", MUTANTES_CUSTO)
def test_mutante_do_custo_e_pego(monkeypatch, mutante):
    mod = _modulo_mutante(monkeypatch, llm_motor, *MUTANTES_CUSTO[mutante])
    assert problemas_custo(mod), f"mutante {mutante!r} passou"


def problemas_custo_agregado(avm) -> list[str]:
    chamadas = [{"no": "supervisor", "token_usage": USO_1}, {"no": "specialist_rag", "token_usage": USO_1},
                {"no": "synthesize_final", "token_usage": USO_1}]
    p = []
    obtido = avm._custo_das_chamadas(chamadas, _cfg("deepseek"))
    if abs(obtido - 3 * CUSTO_USO_1_PICO) > 1e-12:
        p.append(f"deepseek: {obtido} != {3 * CUSTO_USO_1_PICO}")
    com_cost = [{"no": "supervisor", "token_usage": {"cost": 0.002, **USO_1}}]
    if avm._custo_das_chamadas(com_cost, _cfg("openrouter")) != 0.002:
        p.append("openrouter deixou de usar o `cost`")
    return p


def test_custo_agregado_das_chamadas_do_agente():
    assert problemas_custo_agregado(av) == []


def test_mutante_do_custo_agregado_e_pego(monkeypatch):
    mod = _modulo_mutante(monkeypatch, av, '    if llm_motor.provedor(settings) == "deepseek":\n        return sum(',
                          "    if False:\n        return sum(")
    assert problemas_custo_agregado(mod)


# =============================================================================
# 3. corte por orcamento com o custo calculado
# =============================================================================


def _responder(uso: dict | None):
    async def responder(graph, item):
        texto = "Recuse (POP-01)."
        return {"id": item["id"], "tipo": "direta", "pergunta": item["pergunta"],
                "caminho": ["supervisor", "specialist_rag", "supervisor", "synthesize_final"],
                "rag_acionado": True, "trechos": [], "notas_de_outros_especialistas": [],
                "resposta_crua": texto, "resposta_final": texto, "erro": None, "erros_llm": [],
                "falha_de_infra": False,
                "chamadas_llm": [{"no": "synthesize_final", "token_usage": uso}] if uso is not None else
                [{"no": "synthesize_final", "token_usage": None, "usage_metadata": None}]}
    return responder


USO_MIL = {"prompt_tokens": 2000, "completion_tokens": 333, "prompt_cache_hit_tokens": 0,
           "prompt_cache_miss_tokens": 2000}
CUSTO_MIL = (2000 * 0.30 + 333 * 1.20) / 1e6  # US$ 0,0009996


def problemas_corte(pm, monkeypatch) -> list[str]:
    monkeypatch.setattr(av, "_meta_do_indice", lambda s: None)
    itens = {"q02": {"id": "q02", "tipo": "direta", "pergunta": "frango a -10 graus?"}}
    p = []
    with p3.com_motor():
        d = asyncio.run(pm.coletar(pm.passos_a(), itens, orcamento=0.0035, experimento="t",
                                   graph_factory=lambda cp: None, responder=_responder(USO_MIL), log=lambda _: None))
        sem = asyncio.run(pm.coletar(pm.passos_a(), itens, orcamento=0.015, experimento="t",
                                     graph_factory=lambda cp: None, responder=_responder(None), log=lambda _: None))
    if not d["abortado_por_orcamento"] or len(d["respostas"]) != 4:
        p.append(f"corte: abortado={d['abortado_por_orcamento']} com {len(d['respostas'])} respostas (esperado 4)")
    if abs(d["custo_usd"] - len(d["respostas"]) * CUSTO_MIL) > 1e-12:
        p.append(f"custo da coleta {d['custo_usd']} != tokens x preco")
    if pm.estado_da_coleta(d) != me.ESTADO_ORCAMENTO:
        p.append(f"estado {pm.estado_da_coleta(d)}")
    if not sem["abortado_por_orcamento"] or len(sem["respostas"]) != 2:
        p.append(f"sem uso: {len(sem['respostas'])} respostas antes do corte (esperado 2: US$ 0,01 cada)")
    if any(r.get("provedor") != "deepseek" or r.get("modelo_efetivo") != "deepseek-flash" for r in d["respostas"]):
        p.append("resposta sem o provedor/modelo efetivo")
    if (d["config"].get("motor") or {}).get("provedor") != "deepseek":
        p.append("config da coleta sem o motor")
    return p


def test_corte_por_orcamento_com_custo_calculado(monkeypatch, motor_deepseek):
    assert problemas_corte(p3, monkeypatch) == []


def test_mutante_sem_corte_e_pego(monkeypatch, motor_deepseek):
    mod = _modulo_mutante(monkeypatch, p3, '            if saida["custo_usd"] > orcamento:\n                saida["abortado_por_orcamento"] = True\n                log(f"ORCAMENTO estourado (US$ {saida[\'custo_usd\']:.4f} > {orcamento:.2f}): interrompido")\n                break\n        return saida',
                          "        return saida")
    assert problemas_corte(mod, monkeypatch)


def test_corte_por_orcamento_na_b(monkeypatch, motor_deepseek):
    """A B passa pela `av.etapa_respostas` (o mesmo `_custo_das_chamadas`). Ela foi feita
    para o processo do CLI: neutraliza n8n/gateway e liga o rag no settings global SEM
    restaurar; o monkeypatch de todos os campos devolve o settings ao fim do teste."""
    for campo in type(settings).model_fields:
        monkeypatch.setattr(settings, campo, getattr(settings, campo))
    monkeypatch.setattr(av, "_meta_do_indice", lambda s: None)
    perguntas = [{"id": f"q{i:02d}", "tipo": "direta", "pergunta": f"pergunta {i}"} for i in range(1, 21)]
    with p3.com_motor(), p3.com_versao("v1"):
        d = asyncio.run(av.etapa_respostas(perguntas, orcamento=0.0035, graph_factory=lambda cp: None,
                                           responder=_responder(USO_MIL), log=lambda _: None, regras="v1",
                                           aceitas=p3.VERSOES))
    assert d["abortado_por_orcamento"] and len(d["perguntas"]) == 4
    assert abs(d["custo_usd"] - 4 * CUSTO_MIL) < 1e-12


# =============================================================================
# 4. a chave nunca aparece (log, JSON, terminal)
# =============================================================================


class _ErroComChave(Exception):
    status_code = 401


def _fabrica_que_falha(**kwargs):
    raise _ErroComChave(f"Incorrect API key provided: {kwargs['api_key'].get_secret_value()} (headers: "
                        f"Authorization: Bearer {kwargs['api_key'].get_secret_value()})")


class _ChatFalso:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def bind_tools(self, tools, tool_choice=None):
        return self

    def invoke(self, mensagens):
        uso = dict(USO_1)
        return AIMessage(content="ok", response_metadata={"model_name": "deepseek-flash", "token_usage": uso},
                         tool_calls=[{"name": "preencher_ficha", "args": {}, "id": "c1"}])


def problemas_vazamento(m, pm, monkeypatch) -> list[str]:
    monkeypatch.setattr(av, "_meta_do_indice", lambda s: None)
    monkeypatch.setattr(pm, "llm_motor", m)
    cfg = _cfg("deepseek")
    saidas = {
        "descrever": json.dumps(m.descrever(cfg)),
        "teste_conexao falha": json.dumps(m.teste_conexao(cfg, fabrica=_fabrica_que_falha)),
        "teste_ficha falha": json.dumps(m.teste_ficha(cfg, fabrica=_fabrica_que_falha)),
        "teste_conexao ok": json.dumps(m.teste_conexao(cfg, fabrica=_ChatFalso)),
        "repr do settings": repr(cfg) + str(cfg.model_dump()),
    }
    logs = []
    itens = {"q02": {"id": "q02", "tipo": "direta", "pergunta": "frango a -10 graus?"}}
    with p3.com_motor():
        d = asyncio.run(pm.coletar(pm.passos_a()[:2], itens, orcamento=0.06, experimento="t",
                                   graph_factory=lambda cp: None, responder=_responder(USO_1), log=logs.append))
    saidas["JSON da coleta"] = json.dumps(d, default=str)
    saidas["log da coleta"] = "\n".join(logs)
    return [nome for nome, texto in saidas.items() if CHAVE_FALSA in texto]


def test_chave_nunca_aparece(monkeypatch, motor_deepseek):
    assert problemas_vazamento(llm_motor, p3, monkeypatch) == []


MUTANTES_VAZAMENTO = {
    "erro com a mensagem": ('    return {"ok": False, "erro_tipo": type(exc).__name__,',
                            '    return {"ok": False, "erro_tipo": f"{type(exc).__name__}: {exc}",'),
    "descrever com a chave": ('        "provedor": p,\n',
                              ('        "provedor": p, "chave": settings.deepseek_api_key.get_secret_value()\n'
                               '        if settings.deepseek_api_key else None,\n')),
}


@pytest.mark.parametrize("mutante", MUTANTES_VAZAMENTO)
def test_mutante_que_vaza_a_chave_e_pego(monkeypatch, motor_deepseek, mutante):
    mod = _modulo_mutante(monkeypatch, llm_motor, *MUTANTES_VAZAMENTO[mutante])
    assert problemas_vazamento(mod, p3, monkeypatch), f"mutante {mutante!r} passou"


def test_cli_teste_conexao_so_mostra_ok_modelo_e_custo(monkeypatch, capsys, motor_deepseek):
    import langchain_openai

    monkeypatch.setattr(settings, "llm_provedor", "openrouter")  # o teste forca o deepseek sozinho
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _ChatFalso)
    assert p3.main(["--teste-conexao"]) == 0
    out = capsys.readouterr().out
    assert "conexao     : OK" in out and "modelo      : deepseek-flash" in out
    assert f"custo       : US$ {CUSTO_USO_1_PICO:.6f}" in out and "comecou com ok" in out
    assert p3.main(["--teste-ficha"]) == 0
    assert "tool_choice nomeado funciona" in capsys.readouterr().out
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _fabrica_que_falha)
    assert p3.main(["--teste-conexao"]) == 1
    out = capsys.readouterr().out
    assert "FALHOU (_ErroComChave, HTTP 401)" in out and CHAVE_FALSA not in out
    assert settings.llm_provedor == "openrouter"  # o settings global nao foi trocado


def test_cli_teste_conexao_sem_chave_nao_chama(monkeypatch, capsys):
    import langchain_openai

    monkeypatch.setattr(settings, "deepseek_api_key", None)
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **k: pytest.fail("chamou sem chave"))
    assert p3.main(["--teste-conexao"]) == 1
    assert "FALHOU (MotorIndisponivel)" in capsys.readouterr().out


def test_teste_conexao_nao_aceita_orcamento():
    with pytest.raises(SystemExit):
        p3.parse_args(["--teste-conexao", "--orcamento", "0.01"])


# =============================================================================
# a emenda na Parte 3: motor forcado, hash, integridade e tentativas por motor
# =============================================================================


def test_executar_sem_chave_do_motor_e_recusado_antes_de_gastar(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(p3, "DIR_A", tmp_path / "a")
    monkeypatch.setattr(me, "veredito_v3_flash", lambda: (True, "Parte 2.3 PASSA (falso)"))
    monkeypatch.setattr(settings, "deepseek_api_key", None)
    monkeypatch.setattr(p3, "conferir_sistema", lambda s: pytest.fail("passou da conferencia da chave"))
    assert p3.main(["--executar", "a", "--orcamento", "0.06"]) == 2
    err = capsys.readouterr().err
    assert "DEEPSEEK_API_KEY ausente" in err
    assert not (tmp_path / "a").exists()
    assert settings.llm_provedor == "openrouter"  # com_motor restaurou


def test_conferir_sistema_pega_motor_alterado(monkeypatch):
    assert not [x for x in p3.conferir_sistema(settings) if "llm_motor" in x or "motor " in x]
    monkeypatch.setattr(p3, "HASH_CODIGO_MOTOR", "0" * 64)
    assert any("llm_motor.py" in x for x in p3.conferir_sistema(settings))


def test_integridade_exige_o_motor_em_toda_resposta():
    h = {"codigo_motor": p3.HASH_CODIGO_MOTOR}
    assert p3.problemas_do_motor(h, [{"id": "q02", "provedor": "deepseek"}], "x") == []
    assert p3.problemas_do_motor(h, [{"id": "q02", "provedor": "openrouter"}], "x")
    assert p3.problemas_do_motor(h, [{"id": "q02"}], "x")  # sem o campo (coleta antiga)
    assert p3.problemas_do_motor({"codigo_motor": "0" * 64}, [{"id": "q02", "provedor": "deepseek"}], "x")


# O registro REAL da A em 24/11 (2 tentativas invalidas por 429 + 1 falha inicial, OpenRouter).
REGISTRO_A_ANTES = [
    {"unidade": "a", "n": 1, "estado": me.ESTADO_FALHA_INICIAL, "custo_usd": 0.0, "orcamento_usd": 0.06},
    {"unidade": "a", "n": 1, "estado": me.ESTADO_INFRA, "custo_usd": 0.022612498, "orcamento_usd": 0.06},
    {"unidade": "a", "n": 2, "estado": me.ESTADO_INFRA, "custo_usd": 0.0071548452, "orcamento_usd": 0.06},
]


def test_a_ganha_de_novo_uma_repeticao_com_o_motor_novo():
    antes = [dict(t) for t in REGISTRO_A_ANTES]
    assert not p3.pode_executar(antes, "a", "a")[0]  # sem a emenda: encerrada
    assert p3.do_motor(antes, "deepseek") == [] and len(p3.do_motor(antes, "openrouter")) == 3
    assert p3.pode_executar(p3.do_motor(antes), "a", "a")[0]
    p3.validar_orcamento(0.06, "a", "a", p3.do_motor(antes))  # o teto do motor novo esta inteiro
    nova = {"unidade": "a", "n": 3, "estado": me.ESTADO_INFRA, "custo_usd": 0.03, "orcamento_usd": 0.06,
            "motor_do_agente": "deepseek"}
    assert p3.pode_executar(p3.do_motor([*antes, nova]), "a", "a")[0]  # UMA repeticao
    p3.validar_orcamento(0.06, "a", "a", p3.do_motor([*antes, nova]))
    outra = {**nova, "n": 4}
    assert not p3.pode_executar(p3.do_motor([*antes, nova, outra]), "a", "a")[0]  # 2a invalida encerra


def test_iniciar_grava_o_motor(tmp_path):
    _, t = p3._iniciar(tmp_path, "a", 0.06, "deepseek")
    assert t["motor_do_agente"] == "deepseek"
    assert me.ler_registro(tmp_path)[0]["motor_do_agente"] == "deepseek"


def test_plano_mostra_o_motor_o_preco_e_a_a_antiga(tmp_path, monkeypatch, capsys, motor_deepseek):
    monkeypatch.setattr(settings, "llm_provedor", "openrouter")
    (tmp_path / "a").mkdir()
    me.gravar_registro([dict(t) for t in REGISTRO_A_ANTES], tmp_path / "a")
    monkeypatch.setattr(p3, "DIR_A", tmp_path / "a")
    monkeypatch.setattr(av, "_meta_do_indice", lambda s: None)
    assert p3.main([]) == 0
    out = capsys.readouterr().out
    assert "motor       : deepseek (https://api.deepseek.com), modelo efetivo deepseek-flash" in out
    assert "cache hit 0.006 / cache miss 0.3 / saida 1.2 no pico" in out
    assert "DEEPSEEK_API_KEY existe" in out and CHAVE_FALSA not in out
    assert "A antes     : 3 tentativas no openrouter" in out and "US$ 0.0298" in out
    assert "--teste-conexao" in out
    assert settings.llm_provedor == "openrouter"


# =============================================================================
# decisao do Max (24/11): as falhas iniciais NAO recomecam no motor novo
# =============================================================================


def problemas_falhas_iniciais(pm) -> list[str]:
    antes = [dict(x) for x in REGISTRO_A_ANTES]  # 1 falha inicial no OpenRouter
    nova = {"unidade": "a", "n": 3, "estado": me.ESTADO_FALHA_INICIAL, "custo_usd": 0.0,
            "orcamento_usd": 0.06, "motor_do_agente": "deepseek"}
    p = []
    if pm.falhas_iniciais_esgotadas(antes, "a"):
        p.append("a 1a falha inicial no motor novo foi negada")
    if not pm.falhas_iniciais_esgotadas([*antes, nova], "a"):
        p.append("2a falha inicial (1 OpenRouter + 1 DeepSeek) nao encerrou a A")
    if pm.falhas_iniciais_esgotadas([{**nova, "unidade": "v1-r1"}], "v1-r1"):
        p.append("uma unidade nova (sem falha antiga) nao tem as 2 de sempre")
    return p


def test_falhas_iniciais_contam_todos_os_motores():
    assert problemas_falhas_iniciais(p3) == []
    assert me.MAX_FALHAS_INICIAIS == 2  # o mesmo limite de todas as medicoes (1 repeticao)


def test_mutante_falhas_iniciais_por_motor_e_pego(monkeypatch):
    mod = _modulo_mutante(monkeypatch, p3, "for t in tentativas)\n    return n >= me.MAX_FALHAS_INICIAIS",
                          "for t in do_motor(tentativas))\n    return n >= me.MAX_FALHAS_INICIAIS")
    assert problemas_falhas_iniciais(mod)


def test_executar_a_recusa_com_as_falhas_iniciais_esgotadas(tmp_path, monkeypatch, capsys):
    (tmp_path / "a").mkdir()
    nova = {"unidade": "a", "n": 3, "estado": me.ESTADO_FALHA_INICIAL, "custo_usd": 0.0,
            "orcamento_usd": 0.06, "motor_do_agente": "deepseek"}
    me.gravar_registro([*(dict(x) for x in REGISTRO_A_ANTES), nova], tmp_path / "a")
    monkeypatch.setattr(p3, "DIR_A", tmp_path / "a")
    monkeypatch.setattr(me, "veredito_v3_flash", lambda: (True, "Parte 2.3 PASSA (falso)"))
    monkeypatch.setattr(settings, "deepseek_api_key", SecretStr(CHAVE_FALSA))
    monkeypatch.setattr(p3, "conferir_sistema", lambda s: [])
    indice = tmp_path / "indice.sqlite"
    indice.write_bytes(b"x")
    monkeypatch.setattr(settings, "rag_index_path", str(indice))
    monkeypatch.setattr(av, "_aviso_tracing", lambda: False)
    monkeypatch.setattr(av, "responder_pergunta", lambda *a: pytest.fail("rodou com as falhas esgotadas"))
    assert p3.main(["--executar", "a", "--orcamento", "0.06"]) == 2
    assert "ja teve 2 falhas iniciais (contando todos os motores)" in capsys.readouterr().out


def test_executar_a_sem_a_parte_2_3_e_recusado_antes_de_tudo(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(p3, "DIR_A", tmp_path / "a")
    monkeypatch.setattr(me, "DIR_MEDICAO_V3_FLASH", tmp_path / "v3-flash")
    monkeypatch.setattr(p3, "conferir_sistema", lambda s: pytest.fail("passou da trava da 2.3"))
    assert p3.main(["--executar", "a", "--orcamento", "0.06"]) == 2
    out = capsys.readouterr().out
    assert "RECUSADO: a A so roda depois da Parte 2.3" in out and "falta o --resultado da Parte 2.3" in out
    assert not (tmp_path / "a").exists()
