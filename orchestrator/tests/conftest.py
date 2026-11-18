"""Configuracao hermetica da suite de testes.

`orchestrator.config.settings` e instanciado no import e le o `.env` do
diretorio corrente. Sem este arquivo, parte da suite so passava na maquina de
quem tinha um `orchestrator/.env` local com o n8n configurado (ex.:
`specialist_n8n_node` devolve cedo "integracao n8n nao configurada" quando
URL/API key estao ausentes - ver graph/nodes.py) e FALHAVA em qualquer
checkout limpo / CI. Pior: rodar `pytest` no checkout principal carregava as
chaves REAIS do `.env` (OpenRouter, n8n de producao) - um teste que
esquecesse um mock gastaria dinheiro ou mexeria em producao.

Tres camadas, todas antes de qualquer `import orchestrator...` (por isso no
nivel de modulo do conftest, que o pytest carrega antes de coletar testes):

1. Variaveis de ambiente fixadas com valores FALSOS (tem precedencia sobre o
   `.env` no pydantic-settings): n8n e OpenRouter. Qualquer
   `ORCHESTRATOR_RAG_*` herdada do shell e removida.
2. O `settings` global e reconstruido IGNORANDO o `.env` (`_env_file=None`):
   nenhum valor do `.env` local - incluindo `ORCHESTRATOR_RAG_*` futuras,
   tokens do gateway, LangSmith - entra na suite. Resultado igual ao do CI.
3. Fixture autouse que BLOQUEIA a geracao real do `ChatOpenAI`: um teste que
   esquecer de mockar o LLM falha na hora com erro explicito, sem rede e sem
   custo (os testes que mockam substituem a classe inteira em
   `orchestrator.graph.nodes`, entao nao passam por aqui).

Opt-in deliberado para o teste de integracao contra um n8n REAL
(RUN_LIVE_N8N_TESTS=1): so as duas credenciais do n8n sao lidas (do ambiente
ou, se ausentes, do `.env`). OpenRouter e RAG continuam neutralizados mesmo
nesse modo - o teste live do n8n nao usa LLM.
"""

import os
from pathlib import Path

import pytest

FAKE_SECRET = "test-only-not-a-real-key"
_LIVE_N8N = os.environ.get("RUN_LIVE_N8N_TESTS") == "1"
_N8N_KEYS = ("ORCHESTRATOR_N8N_URL", "ORCHESTRATOR_N8N_API_KEY")

# --- Camada 1: ambiente ----------------------------------------------------
for _key in [k for k in os.environ if k.startswith("ORCHESTRATOR_RAG_")]:
    del os.environ[_key]

os.environ["ORCHESTRATOR_OPENROUTER_API_KEY"] = FAKE_SECRET

if _LIVE_N8N:
    from dotenv import dotenv_values

    _dotenv = dotenv_values(Path.cwd() / ".env")
    for _key in _N8N_KEYS:
        if not os.environ.get(_key) and _dotenv.get(_key):
            os.environ[_key] = _dotenv[_key]
else:
    os.environ["ORCHESTRATOR_N8N_URL"] = "https://n8n.test.invalid"
    os.environ["ORCHESTRATOR_N8N_API_KEY"] = FAKE_SECRET

# --- Camada 2: settings sem .env -------------------------------------------
# Os modulos fazem `from orchestrator.config import settings`; como o conftest
# roda antes deles, todos recebem esta instancia hermetica.
from orchestrator import config as _config

_config.settings = _config.Settings(_env_file=None)


# --- Camada 3: LLM real bloqueado -------------------------------------------
class RealLLMCallBlocked(RuntimeError):
    """Um teste tentou chamar um LLM de verdade sem mock."""


@pytest.fixture(autouse=True)
def blocked_llm_calls(request, monkeypatch):
    """Bloqueia o LLM real e REPROVA o teste que tentou usa-lo.

    So levantar a excecao nao basta: o `supervisor_node` envolve a chamada ao
    LLM em `except Exception` e cai no fallback do openclaw, entao o erro
    seria engolido e o teste podia passar sem ninguem perceber. Por isso cada
    tentativa fica registrada e o teardown falha se a lista nao estiver vazia.

    Um teste que QUER provar o bloqueio pede esta fixture pelo nome e da
    `.clear()` na lista depois de conferir.
    """
    from langchain_openai import ChatOpenAI

    calls: list[str] = []
    msg = (
        "chamada REAL ao ChatOpenAI bloqueada na suite de testes - mocke o LLM "
        "(ex.: patch('orchestrator.graph.nodes.ChatOpenAI'))"
    )

    def _blocked(self) -> RealLLMCallBlocked:
        calls.append(getattr(self, "model_name", "?"))
        return RealLLMCallBlocked(msg)

    def _sync(self, *args, **kwargs):
        raise _blocked(self)

    async def _async(self, *args, **kwargs):
        raise _blocked(self)

    async def _async_stream(self, *args, **kwargs):
        raise _blocked(self)
        yield  # pragma: no cover - torna a funcao um async generator

    monkeypatch.setattr(ChatOpenAI, "_generate", _sync)
    monkeypatch.setattr(ChatOpenAI, "_agenerate", _async)
    monkeypatch.setattr(ChatOpenAI, "_stream", _sync)
    monkeypatch.setattr(ChatOpenAI, "_astream", _async_stream)

    yield calls

    if calls:
        pytest.fail(
            f"{request.node.nodeid} tentou {len(calls)} chamada(s) REAL(is) ao LLM "
            f"(modelos: {calls}) - mesmo que o codigo tenha engolido o erro. {msg}",
            pytrace=False,
        )
