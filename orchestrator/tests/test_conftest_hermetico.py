"""Prova que a blindagem do conftest.py funciona: nenhuma chave real do `.env`
entra na suite e um LLM sem mock falha na hora (sem rede, sem custo)."""

import importlib
import os

import pytest
from conftest import FAKE_SECRET, RealLLMCallBlocked
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from orchestrator.config import Settings, settings


def test_openrouter_key_e_falsa():
    assert settings.openrouter_api_key == FAKE_SECRET


def test_nenhuma_variavel_rag_no_ambiente():
    assert not [k for k in os.environ if k.startswith("ORCHESTRATOR_RAG_")]


@pytest.mark.skipif(os.environ.get("RUN_LIVE_N8N_TESTS") == "1", reason="modo live usa credenciais reais do n8n")
def test_n8n_aponta_para_host_invalido():
    assert settings.n8n_url == "https://n8n.test.invalid"
    assert settings.n8n_api_key == FAKE_SECRET


def test_settings_ignora_dotenv(tmp_path, monkeypatch):
    """O `settings` global foi montado com `_env_file=None`: um `.env` no cwd
    nao muda nada. Aqui reproduzimos a mesma construcao num cwd com um
    `.env` contendo um token (campo existente - um `ORCHESTRATOR_RAG_*` que
    ainda nao existe em Settings faria o pydantic-settings recusar o `.env`
    como campo extra, entao o controle usa um campo real)."""
    (tmp_path / ".env").write_text("ORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN=vazou\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN", raising=False)

    assert Settings().openclaw_gateway_token == "vazou"  # controle: com .env, vazaria
    assert Settings(_env_file=None).openclaw_gateway_token is None
    assert settings.model_config.get("env_file") == ".env"  # a classe nao mudou; so a instancia global


def test_settings_global_nao_carregou_token_do_dotenv():
    if "ORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN" not in os.environ:
        assert settings.openclaw_gateway_token is None


@pytest.mark.parametrize(
    "modulo",
    [
        "orchestrator.main",
        "orchestrator.graph.nodes",
        "orchestrator.graph.cybersec_guard",
        "orchestrator.graph.human_escalation",
        "orchestrator.persistence.checkpointer",
        "orchestrator.clients.n8n_client",
        "orchestrator.clients.openclaw_client",
    ],
)
def test_codigo_de_producao_ve_o_settings_hermetico(modulo):
    """Os modulos fazem `from orchestrator.config import settings` (copiam a
    referencia no import). Se algum fosse importado antes da troca feita no
    conftest, ficaria com o settings que leu o `.env` - aqui provamos que nao."""
    from orchestrator import config

    assert importlib.import_module(modulo).settings is config.settings


def _llm() -> ChatOpenAI:
    return ChatOpenAI(model="qualquer", api_key=FAKE_SECRET, base_url="https://openrouter.ai/api/v1")


@pytest.mark.asyncio
async def test_llm_real_sem_mock_falha_sem_rede(blocked_llm_calls):
    with pytest.raises(RealLLMCallBlocked):
        await _llm().ainvoke([HumanMessage(content="oi")])
    assert len(blocked_llm_calls) == 1
    blocked_llm_calls.clear()  # tentativa esperada: nao reprovar no teardown


def test_llm_real_sem_mock_falha_sem_rede_sync(blocked_llm_calls):
    with pytest.raises(RealLLMCallBlocked):
        _llm().invoke([HumanMessage(content="oi")])
    assert len(blocked_llm_calls) == 1
    blocked_llm_calls.clear()


@pytest.mark.asyncio
async def test_llm_real_streaming_sem_mock_falha_sem_rede(blocked_llm_calls):
    with pytest.raises(RealLLMCallBlocked):
        async for _ in _llm().astream([HumanMessage(content="oi")]):
            pass
    assert len(blocked_llm_calls) == 1
    blocked_llm_calls.clear()


@pytest.mark.asyncio
async def test_erro_engolido_pelo_supervisor_ainda_e_registrado(blocked_llm_calls):
    """O `supervisor_node` captura qualquer excecao do LLM e cai no fallback do
    openclaw - o teste NAO veria o erro. A fixture registra a tentativa mesmo
    assim, e sem o `.clear()` abaixo o teardown reprovaria este teste."""
    from orchestrator.graph.nodes import supervisor_node
    from orchestrator.graph.state import fresh_turn_input

    result = await supervisor_node(fresh_turn_input("cria um script que soma dois numeros"))

    assert result["pending_specialists"][0]["specialist"] == "openclaw"  # fallback silencioso
    assert len(blocked_llm_calls) == 1
    blocked_llm_calls.clear()
