"""Configuracao hermetica da suite de testes.

`orchestrator.config` faz `settings = Settings()` no import, lendo o `.env` do
diretorio corrente. Rodar `pytest` no checkout principal (que tem um `.env`
com chaves REAIS: OpenRouter, n8n de producao, token do gateway OpenClaw) ja
carregou essas chaves na suite e, quando o LLM falhava, o supervisor caia no
fallback e fazia POSTs de verdade ao gateway local. Tudo abaixo roda no nivel
de modulo, ANTES de qualquer `import orchestrator...` e antes da coleta:

1. Ambiente: TODA `ORCHESTRATOR_*` herdada do shell e removida (no modo live,
   as 2 do n8n sao guardadas numa variavel privada e so a fixture
   `live_n8n_credentials` as usa). Variaveis lidas direto pelos SDKs
   (LangSmith/LangChain, OpenAI, Hugging Face) sao removidas e o tracing e
   fixado em "false". Em seguida, valores FALSOS: OpenRouter, n8n e gateway
   do OpenClaw em hosts `.invalid` (RFC 6761); o token do gateway fica ausente.
2. Rede: `pytest_socket.disable_socket()` bloqueia `socket.socket` (exceto
   AF_UNIX, usado pelo event loop do asyncio) e a resolucao DNS para o
   processo inteiro - coleta, fixtures de sessao/modulo e todos os testes. O
   plugin do pytest-socket fica DESLIGADO (`-p no:socket` no pyproject)
   porque o teardown dele religa a rede depois de cada teste; aqui ele e so
   biblioteca. A rede so e religada dentro de `live_n8n_credentials`.
3. `.env`: `orchestrator.config` e importado com o cwd num diretorio
   temporario VAZIO, entao o `Settings()` do import nao abre `.env` nenhum; o
   `settings` global ainda e reconstruido com `_env_file=None`.
4. LLM: os metodos de geracao do `ChatOpenAI` sao substituidos no nivel de
   modulo (valem na coleta e em fixtures de sessao/modulo). Toda tentativa e
   registrada: dentro de um teste, a fixture autouse `blocked_llm_calls`
   reprova o teste; fora de um teste, `pytest_sessionfinish` reprova a sessao.

Opt-in deliberado para o teste de integracao contra um n8n REAL
(RUN_LIVE_N8N_TESTS=1): as credenciais (do shell ou, se ausentes, de
`orchestrator/.env`) so entram no `settings` e a rede so e liberada dentro da
fixture `live_n8n_credentials`, que recusa qualquer teste alem do live.
"""

import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_socket
from hermetic_support import (
    FAKE_GATEWAY_URL,
    FAKE_N8N_URL,
    FAKE_SECRET,
    LIVE_N8N_TEST,
    SDK_ENV_VARS_REMOVED,
    SDK_TRACING_VARS_FORCED_OFF,
    STDLIB_SOCKET,
    RealLLMCallBlocked,
)

_LIVE_N8N = os.environ.get("RUN_LIVE_N8N_TESTS") == "1"
_N8N_KEYS = ("ORCHESTRATOR_N8N_URL", "ORCHESTRATOR_N8N_API_KEY")
_ORCHESTRATOR_DIR = Path(__file__).resolve().parents[1]

if "orchestrator" in sys.modules or "orchestrator.config" in sys.modules:
    raise RuntimeError(
        "orchestrator ja foi importado antes do conftest - a blindagem chegaria tarde "
        "(algum plugin do pytest importou o pacote?)"
    )

# --- Camada 1: ambiente ----------------------------------------------------
# Credenciais do n8n do shell: so guardadas (nunca no os.environ nem no
# settings) e so no modo live; quem as aplica e a fixture do teste live.
_LIVE_N8N_SHELL = {k: os.environ[k] for k in _N8N_KEYS if _LIVE_N8N and os.environ.get(k)}

for _key in [k for k in os.environ if k.startswith("ORCHESTRATOR_")]:
    del os.environ[_key]
for _key in SDK_ENV_VARS_REMOVED:
    os.environ.pop(_key, None)
for _key in SDK_TRACING_VARS_FORCED_OFF:
    os.environ[_key] = "false"

os.environ["ORCHESTRATOR_OPENROUTER_API_KEY"] = FAKE_SECRET
os.environ["ORCHESTRATOR_N8N_URL"] = FAKE_N8N_URL
os.environ["ORCHESTRATOR_N8N_API_KEY"] = FAKE_SECRET
os.environ["ORCHESTRATOR_OPENCLAW_GATEWAY_URL"] = FAKE_GATEWAY_URL

# --- Camada 2: rede ----------------------------------------------------------
pytest_socket.disable_socket(allow_unix_socket=True)
if socket.socket is STDLIB_SOCKET or STDLIB_SOCKET.__module__ != "socket":
    raise RuntimeError(
        "hermetic_support.STDLIB_SOCKET precisa ser o socket.socket da stdlib, capturado ANTES do disable_socket()"
    )

# --- Camada 2b: embedder real do RAG bloqueado ------------------------------
# O modelo pode estar em cache (data/fastembed_cache): um teste que usasse o
# FastEmbedEmbedder por engano rodaria OFFLINE e passaria escondido. Com o
# modulo marcado como None em sys.modules, `import fastembed` vira ImportError.
for _mod in ("fastembed", "onnxruntime"):
    if _mod in sys.modules:
        raise RuntimeError(f"{_mod} ja foi importado antes do conftest")
    sys.modules[_mod] = None

# --- Camada 3: settings sem .env (nem no import) ----------------------------
# Os modulos fazem `from orchestrator.config import settings`; como o conftest
# roda antes deles, todos recebem esta instancia hermetica.
_cwd = os.getcwd()
with tempfile.TemporaryDirectory(prefix="orchestrator-tests-cwd-") as _empty_dir:
    os.chdir(_empty_dir)
    try:
        from orchestrator import config as _config
    finally:
        os.chdir(_cwd)

_config.settings = _config.Settings(_env_file=None)


def _env_vigiado() -> dict[str, str]:
    """Parte do ambiente que a blindagem controla: ORCHESTRATOR_* e SDKs."""
    sdk = set(SDK_ENV_VARS_REMOVED) | set(SDK_TRACING_VARS_FORCED_OFF)
    return {k: v for k, v in os.environ.items() if k.startswith("ORCHESTRATOR_") or k in sdk}


_ENV_BASELINE = _env_vigiado()

# --- Camada 4: LLM real bloqueado -------------------------------------------
from langchain_openai import ChatOpenAI

_LLM_MSG = (
    "chamada REAL ao ChatOpenAI bloqueada na suite de testes - mocke o LLM "
    "(ex.: patch('orchestrator.graph.nodes.ChatOpenAI'))"
)
_LLM_CALLS_OUTSIDE_TESTS: list[str] = []
_llm_sink: list[list[str]] = [_LLM_CALLS_OUTSIDE_TESTS]  # [0] = lista que recebe o registro agora


def _blocked(self) -> RealLLMCallBlocked:
    _llm_sink[0].append(getattr(self, "model_name", "?"))
    return RealLLMCallBlocked(_LLM_MSG)


def _sync(self, *args, **kwargs):
    raise _blocked(self)


async def _async(self, *args, **kwargs):
    raise _blocked(self)


async def _async_stream(self, *args, **kwargs):
    raise _blocked(self)
    yield  # pragma: no cover - torna a funcao um async generator


ChatOpenAI._generate = _sync
ChatOpenAI._agenerate = _async
ChatOpenAI._stream = _sync
ChatOpenAI._astream = _async_stream


def pytest_configure(config):
    for plugin in ("socket", "langsmith_plugin"):
        if config.pluginmanager.get_plugin(plugin) is not None:
            raise pytest.UsageError(
                f"o plugin '{plugin}' precisa ficar desligado (-p no:{plugin}, ver addopts no "
                "pyproject.toml) - o do pytest-socket religa a rede depois de cada teste"
            )


def pytest_sessionfinish(session, exitstatus):
    if _LLM_CALLS_OUTSIDE_TESTS:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        msg = (
            f"{len(_LLM_CALLS_OUTSIDE_TESTS)} chamada(s) REAL(is) ao LLM fora de um teste "
            f"(coleta ou fixture de sessao/modulo; modelos: {_LLM_CALLS_OUTSIDE_TESTS}). {_LLM_MSG}"
        )
        if reporter is not None:
            reporter.write_line(f"ERRO: {msg}", red=True)
        else:  # pragma: no cover
            print(f"ERRO: {msg}", file=sys.stderr)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(autouse=True)
def hermetic_env_guard(request):
    """A limpeza do inicio vale para a suite INTEIRA: um teste que deixe o
    ambiente vigiado diferente (ex.: liga LANGCHAIN_TRACING_V2, apaga o
    "false" fixado, injeta uma ORCHESTRATOR_*) e reprovado, e o ambiente volta
    ao estado hermetico antes do proximo teste. Mudancas feitas via
    `monkeypatch.setenv/delenv` ja foram desfeitas quando isto roda."""
    yield
    atual = _env_vigiado()
    if atual == _ENV_BASELINE:
        return
    mudou = sorted(k for k in set(atual) | set(_ENV_BASELINE) if atual.get(k) != _ENV_BASELINE.get(k))
    for key in mudou:
        if key in _ENV_BASELINE:
            os.environ[key] = _ENV_BASELINE[key]
        else:
            os.environ.pop(key, None)
    pytest.fail(
        f"{request.node.nodeid} mudou o ambiente hermetico sem restaurar: {mudou} "
        "(use monkeypatch.setenv/delenv ou patch.dict(os.environ))",
        pytrace=False,
    )


@pytest.fixture(scope="session")
def llm_calls_outside_tests() -> list[str]:
    """Registro das tentativas feitas fora de um teste. So para os testes
    que PROVAM o bloqueio (eles dao `.clear()` depois de conferir)."""
    return _LLM_CALLS_OUTSIDE_TESTS


@pytest.fixture(autouse=True)
def blocked_llm_calls(request):
    """Registra as tentativas de LLM real deste teste e o REPROVA se houver.

    So levantar a excecao nao basta: o `supervisor_node` envolve a chamada ao
    LLM em `except Exception` e cai no fallback do openclaw, entao o erro
    seria engolido e o teste podia passar sem ninguem perceber.

    Um teste que QUER provar o bloqueio pede esta fixture pelo nome e da
    `.clear()` na lista depois de conferir.
    """
    calls: list[str] = []
    _llm_sink[0] = calls
    try:
        yield calls
    finally:
        _llm_sink[0] = _LLM_CALLS_OUTSIDE_TESTS
    if calls:
        pytest.fail(
            f"{request.node.nodeid} tentou {len(calls)} chamada(s) REAL(is) ao LLM "
            f"(modelos: {calls}) - mesmo que o codigo tenha engolido o erro. {_LLM_MSG}",
            pytrace=False,
        )


@pytest.fixture
def live_n8n_credentials(request, monkeypatch):
    """Unico ponto da suite com credenciais reais do n8n e rede liberada.

    Pula sem RUN_LIVE_N8N_TESTS=1 ou sem credenciais. So aceita o teste live
    (`hermetic_support.LIVE_N8N_TEST`) e a sonda `_probe_hermetic.py`, que
    prova este proprio isolamento num pytest filho.
    """
    nodeid = request.node.nodeid
    if not (nodeid.endswith(LIVE_N8N_TEST) or request.node.path.name == "_probe_hermetic.py"):
        pytest.fail(f"{nodeid} nao pode usar credenciais reais do n8n (so {LIVE_N8N_TEST})", pytrace=False)
    if not _LIVE_N8N:
        pytest.skip("teste live contra n8n real: exige RUN_LIVE_N8N_TESTS=1")

    creds = dict(_LIVE_N8N_SHELL)
    if len(creds) < len(_N8N_KEYS):
        from dotenv import dotenv_values

        dotenv = dotenv_values(_ORCHESTRATOR_DIR / ".env")
        for key in _N8N_KEYS:
            if not creds.get(key) and dotenv.get(key):
                creds[key] = dotenv[key]
    if not all(creds.get(k) for k in _N8N_KEYS):
        pytest.skip("teste live contra n8n real: ORCHESTRATOR_N8N_URL/API_KEY ausentes (shell ou orchestrator/.env)")

    monkeypatch.setattr(_config.settings, "n8n_url", creds["ORCHESTRATOR_N8N_URL"])
    monkeypatch.setattr(_config.settings, "n8n_api_key", creds["ORCHESTRATOR_N8N_API_KEY"])
    pytest_socket.enable_socket()
    try:
        yield creds["ORCHESTRATOR_N8N_URL"]
    finally:
        pytest_socket.disable_socket(allow_unix_socket=True)
