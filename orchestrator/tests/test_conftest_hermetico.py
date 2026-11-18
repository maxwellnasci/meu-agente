"""Prova que a blindagem do conftest.py funciona.

Cada achado da revisao adversaria do commit ff259cb tem aqui um teste que
FALHAVA antes da correcao. Os que dependem do estado do processo no momento
em que o conftest roda (shell herdado, `.env` no cwd, modo live, LLM durante
a coleta) rodam um pytest FILHO com a sonda `_probe_hermetic.py`: dentro do
mesmo processo o ambiente ja foi limpo (ou nao) antes de qualquer teste, e o
resultado dependeria do shell de quem rodou.

Nada aqui importa o conftest como modulo (`from conftest import ...`): isso o
executaria de novo, fora do controle do pytest. O que e compartilhado mora em
`hermetic_support.py`, sem efeitos colaterais.
"""

import importlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
from hermetic_support import (
    FAKE_GATEWAY_URL,
    FAKE_N8N_URL,
    FAKE_SECRET,
    SDK_ENV_VARS_REMOVED,
    SDK_TRACING_VARS_FORCED_OFF,
    STDLIB_SOCKET,
    RealLLMCallBlocked,
    loopback_socket,
)
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError
from pytest_socket import SocketBlockedError

from orchestrator.config import Settings, settings

TESTS_DIR = Path(__file__).resolve().parent
PROBE = TESTS_DIR / "_probe_hermetic.py"

# Bootstrap do pytest filho: instala um audit hook ANTES do conftest para
# registrar todo `open()` de um arquivo chamado `.env` (achado 5).
_AUDIT_BOOTSTRAP = """
import json, os, sys
_opens = []
def _hook(event, args):
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        path = os.fsdecode(args[0])
        if os.path.basename(path) == ".env":
            _opens.append(os.path.abspath(path))
sys.addaudithook(_hook)
import pytest
rc = pytest.main(sys.argv[1:])
with open(os.environ["HERMETIC_DOTENV_LOG"], "w") as fh:
    json.dump(_opens, fh)
sys.exit(int(rc))
"""


def _run_probe(
    tmp_path: Path,
    extra_env: dict[str, str],
    tests=("test_probe_estado",),
    cwd: Path | None = None,
    pytest_args: tuple[str, ...] = (),
):
    """Roda a sonda num pytest filho e devolve (returncode, dump, .env abertos, saida)."""
    out = tmp_path / "probe.json"
    log = tmp_path / "dotenv_opens.json"
    env = dict(os.environ)
    env.pop("RUN_LIVE_N8N_TESTS", None)
    env.update(extra_env)
    env["HERMETIC_PROBE_OUT"] = str(out)
    env["HERMETIC_DOTENV_LOG"] = str(log)
    cmd = [sys.executable, "-c", _AUDIT_BOOTSTRAP, "-q", "-p", "no:cacheprovider", *pytest_args, *(f"{PROBE}::{t}" for t in tests)]
    proc = subprocess.run(cmd, cwd=cwd or tmp_path, env=env, capture_output=True, text=True, timeout=180, check=False)
    dump = json.loads(out.read_text()) if out.exists() else {}
    opens = json.loads(log.read_text()) if log.exists() else None
    return proc.returncode, dump, opens, proc.stdout + proc.stderr


# --- Achado 1: rede bloqueada no nivel de socket ----------------------------


def _assert_socket_blocked(exc: BaseException) -> None:
    """O anyio/httpcore pode entregar o erro dentro de um ExceptionGroup ou
    encadeado: procura o SocketBlockedError em toda a arvore."""
    vistos, pilha = set(), [exc]
    while pilha:
        atual = pilha.pop()
        if atual is None or id(atual) in vistos:
            continue
        vistos.add(id(atual))
        if isinstance(atual, SocketBlockedError):
            return
        pilha.extend(getattr(atual, "exceptions", ()))
        pilha.extend((atual.__cause__, atual.__context__))
    raise AssertionError(f"esperava SocketBlockedError, veio {exc!r}")


def test_socket_inet_bloqueado():
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_dns_bloqueado():
    with pytest.raises(SocketBlockedError):
        socket.getaddrinfo("example.com", 443)


def test_unix_socket_liberado_para_o_event_loop():
    """O self-pipe do asyncio usa socketpair AF_UNIX: precisa continuar funcionando."""
    a, b = socket.socketpair()
    a.close()
    b.close()


def test_loopback_socket_so_reserva_porta_local():
    """Excecao estreita para os testes do provision-client: porta no loopback, sem trafego."""
    with loopback_socket() as s:
        s.bind(("127.0.0.1", 0))
        assert s.getsockname()[0] == "127.0.0.1"
        with pytest.raises(RuntimeError, match="nao conecta"):
            s.connect(("127.0.0.1", 9))
    with loopback_socket() as s, pytest.raises(RuntimeError, match="so aceita bind"):
        s.bind(("0.0.0.0", 0))


@pytest.mark.parametrize(
    ("addopts", "plugin"),
    [("-p no:langsmith_plugin", "socket"), ("-p no:socket", "langsmith_plugin")],
)
def test_suite_recusa_subir_com_plugin_proibido_ligado(tmp_path, addopts, plugin):
    """O teardown do plugin do pytest-socket (`_remove_restrictions`) RELIGA a
    rede depois de cada teste, e o do LangSmith importa o SDK antes do
    conftest. Os dois ficam desligados no `addopts`; se alguem tirar o
    `-p no:...`, a guarda do `pytest_configure` precisa derrubar a sessao.
    (A versao anterior so conferia `is_blocked` DENTRO da suite - onde, com a
    guarda funcionando, ele nunca podia ser falso: o teste nunca falhava.)"""
    rc, dump, _, saida = _run_probe(tmp_path, {}, pytest_args=("-o", f"addopts={addopts}"))
    assert rc != 0, saida
    assert f"o plugin '{plugin}' precisa ficar desligado" in saida
    assert "estado" not in dump  # a sonda nem chegou a rodar


def test_stdlib_socket_guardado_antes_do_bloqueio():
    """`loopback_socket` herda deste objeto: tem de ser a classe da stdlib
    (capturada no import do hermetic_support), nao o GuardedSocket atual."""
    assert STDLIB_SOCKET is not socket.socket
    assert STDLIB_SOCKET.__module__ == "socket" and STDLIB_SOCKET.__qualname__ == "socket"


@pytest.fixture(scope="module")
def _socket_em_fixture_de_modulo():
    try:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).close()
        return "LIBERADO"
    except SocketBlockedError:
        return "BLOQUEADO"


def test_socket_bloqueado_em_fixture_de_modulo(_socket_em_fixture_de_modulo):
    assert _socket_em_fixture_de_modulo == "BLOQUEADO"


@pytest.mark.asyncio
async def test_cliente_openclaw_nao_sai_para_rede():
    """Antes: conexao recusada virava `success=False` silencioso apos 3
    tentativas - o teste passava e a rede tinha sido usada. Agora a primeira
    tentativa de socket estoura na cara."""
    from orchestrator.clients.openclaw_client import OpenClawClient
    from orchestrator.schemas.requests import SpecialistCallRequest

    with pytest.raises(BaseException) as exc_info:
        await OpenClawClient(base_url="http://127.0.0.1:9").call(SpecialistCallRequest(task_description="oi"))
    _assert_socket_blocked(exc_info.value)


@pytest.mark.asyncio
async def test_fallback_do_supervisor_nao_faz_post_ao_gateway(blocked_llm_calls, monkeypatch):
    """O caminho dos 12 POSTs: LLM falha -> supervisor cai no fallback openclaw
    -> especialista faz POST ao gateway. O URL aponta para a porta discard
    local (sem servico) para a fase vermelha nao tocar o gateway real."""
    from orchestrator.graph.nodes import specialist_openclaw_node, supervisor_node
    from orchestrator.graph.state import fresh_turn_input

    monkeypatch.setattr(settings, "openclaw_gateway_url", "http://127.0.0.1:9")
    state = fresh_turn_input("cria um script que soma dois numeros")
    routed = await supervisor_node(state)
    assert routed["pending_specialists"][0]["specialist"] == "openclaw"
    blocked_llm_calls.clear()

    with pytest.raises(BaseException) as exc_info:
        await specialist_openclaw_node({**state, **routed})
    _assert_socket_blocked(exc_info.value)


# --- Achado 2: gateway do OpenClaw em host .invalid, sem token --------------


def test_gateway_openclaw_aponta_para_host_invalido_sem_token():
    assert settings.openclaw_gateway_url == FAKE_GATEWAY_URL
    assert urlparse(settings.openclaw_gateway_url).hostname.endswith(".invalid")
    assert settings.openclaw_gateway_token is None


# --- Achado 3: nenhuma ORCHESTRATOR_* herdada, SDKs neutralizados -----------


_FAKES_DO_CONFTEST = {
    "ORCHESTRATOR_OPENROUTER_API_KEY": FAKE_SECRET,
    "ORCHESTRATOR_N8N_URL": FAKE_N8N_URL,
    "ORCHESTRATOR_N8N_API_KEY": FAKE_SECRET,
    "ORCHESTRATOR_OPENCLAW_GATEWAY_URL": FAKE_GATEWAY_URL,
}


def test_ambiente_do_processo_so_tem_os_fakes_do_conftest():
    assert {k: v for k, v in os.environ.items() if k.startswith("ORCHESTRATOR_")} == _FAKES_DO_CONFTEST
    for var in SDK_ENV_VARS_REMOVED:
        assert var not in os.environ, var
    for var in SDK_TRACING_VARS_FORCED_OFF:
        assert os.environ.get(var) == "false", var


def test_shell_sujo_nao_vaza_para_a_suite(tmp_path):
    shell = {
        "ORCHESTRATOR_API_TOKEN": "shell-api-token",
        "ORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN": "shell-gateway-token",
        "ORCHESTRATOR_OPENCLAW_GATEWAY_URL": "http://127.0.0.1:18789",
        "ORCHESTRATOR_N8N_URL": "https://n8n.shell-canario.invalid",
        "ORCHESTRATOR_N8N_API_KEY": "shell-n8n-key",
        "ORCHESTRATOR_LANGCHAIN_TRACING_V2": "true",
        "ORCHESTRATOR_LANGCHAIN_API_KEY": "shell-ls-key",
        "ORCHESTRATOR_RAG_QUALQUER": "x",
        "ORCHESTRATOR_CAMPO_FUTURO": "x",
        **{var: "shell-sdk-value" for var in SDK_ENV_VARS_REMOVED},
        **{var: "true" for var in SDK_TRACING_VARS_FORCED_OFF},
    }
    rc, dump, _, saida = _run_probe(tmp_path, shell)
    assert rc == 0, saida
    estado = dump["estado"]
    assert estado["orchestrator_env"] == _FAKES_DO_CONFTEST
    assert estado["sdk_env"] == {var: "false" for var in SDK_TRACING_VARS_FORCED_OFF}
    assert estado["settings"]["openclaw_gateway_url"] == FAKE_GATEWAY_URL
    assert estado["settings"]["openclaw_gateway_token"] is None
    assert estado["settings"]["api_token"] is None
    assert estado["settings"]["n8n_url"] == FAKE_N8N_URL
    assert estado["settings"]["langchain_api_key"] is None
    assert estado["settings"]["langchain_tracing_v2"] is False
    assert estado["socket_inet"] == "SocketBlockedError"


def test_teste_que_suja_o_ambiente_e_reprovado_e_o_ambiente_restaurado(tmp_path):
    """A limpeza do inicio nao basta: um teste no meio da suite (ex.: o da
    ponte do LangSmith em main.py) pode reescrever `os.environ` e valer para
    todos os seguintes. A guarda do conftest compara o ambiente depois de
    cada teste, restaura e reprova quem mudou."""
    rc, dump, _, saida = _run_probe(tmp_path, {}, tests=("test_probe_suja_o_ambiente", "test_probe_ambiente_depois_da_sujeira"))
    assert rc != 0, saida
    assert "mudou o ambiente" in saida
    assert dump["depois"] == {"LANGCHAIN_TRACING_V2": "false", "ORCHESTRATOR_API_TOKEN": None}


# --- Achado 4: ChatOpenAI bloqueado no nivel de modulo ----------------------


def _llm() -> ChatOpenAI:
    # base_url .invalid + max_retries=0: se o bloqueio falhar, nada chega a um
    # provedor real (a fase vermelha deste teste nao gasta nem vaza nada).
    return ChatOpenAI(model="qualquer", api_key=FAKE_SECRET, base_url="https://llm.test.invalid/v1", max_retries=0)


@pytest.fixture(scope="module")
def _llm_em_fixture_de_modulo(llm_calls_outside_tests):
    try:
        _llm().invoke([HumanMessage(content="oi")])
        resultado = "NAO_BLOQUEADO"
    except Exception as exc:  # noqa: BLE001 - so o tipo interessa
        resultado = type(exc).__name__
    registradas = list(llm_calls_outside_tests)
    llm_calls_outside_tests.clear()  # tentativa esperada: nao reprovar a sessao
    return resultado, registradas


def test_llm_bloqueado_em_fixture_de_modulo(_llm_em_fixture_de_modulo):
    resultado, registradas = _llm_em_fixture_de_modulo
    assert resultado == RealLLMCallBlocked.__name__
    assert registradas == ["qualquer"]


def test_llm_na_coleta_e_bloqueado_e_reprova_a_sessao(tmp_path):
    rc, dump, _, saida = _run_probe(tmp_path, {"HERMETIC_PROBE_LLM_AT_IMPORT": "1"})
    assert dump.get("llm_na_coleta") == RealLLMCallBlocked.__name__, saida
    assert rc != 0, saida  # a sonda em si passa; quem reprova e o conftest
    assert "fora de um teste" in saida


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


# --- Achado 5: o .env nao e lido nem na importacao --------------------------


def test_dotenv_nao_e_lido_na_importacao(tmp_path, monkeypatch):
    """`orchestrator.config` faz `settings = Settings()` no import, e o
    pydantic-settings le `.env` relativo ao cwd. Antes, o conftest importava o
    modulo (lendo o `.env`) e SO DEPOIS trocava o settings - o arquivo ja
    tinha sido aberto e um valor invalido nele derrubava a suite. Aqui o cwd
    do pytest filho tem um `.env` canario com porta invalida."""
    work = tmp_path / "cwd"
    work.mkdir()
    (work / ".env").write_text(
        "ORCHESTRATOR_PORT=canario-nao-numerico\nORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN=vazou-do-dotenv\n"
    )
    # Controle positivo: o canario DERRUBA o Settings de producao quando ele
    # le o `.env` do cwd. Sem isto, se o config deixasse de ler `.env` (ou o
    # canario parasse de ser invalido), o teste abaixo passaria sem provar nada.
    monkeypatch.chdir(work)
    with pytest.raises(ValidationError, match="port"):
        Settings()
    monkeypatch.undo()

    rc, dump, opens, saida = _run_probe(tmp_path, {}, cwd=work)
    assert rc == 0, saida
    assert opens == [], f".env aberto durante a suite: {opens}"
    assert dump["estado"]["settings"]["openclaw_gateway_token"] is None
    assert dump["estado"]["settings"]["port"] == 8000


def test_nenhum_teste_importa_o_conftest_como_modulo():
    for arquivo in TESTS_DIR.glob("*.py"):
        texto = arquivo.read_text(encoding="utf-8")
        for proibido in ("from conftest import", "import conftest"):
            linhas = [linha for linha in texto.splitlines() if linha.lstrip().startswith(proibido)]
            assert not linhas, f"{arquivo.name} importa o conftest: {linhas}"


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
    conftest, ficaria com outro settings - aqui provamos que nao."""
    from orchestrator import config

    assert importlib.import_module(modulo).settings is config.settings


def test_openrouter_key_e_falsa():
    assert settings.openrouter_api_key == FAKE_SECRET


# --- Achado 6: credenciais reais do n8n so na fixture do teste live ---------


def test_n8n_aponta_para_host_invalido():
    """Vale inclusive com RUN_LIVE_N8N_TESTS=1: no modo live as credenciais
    reais so entram no settings dentro da fixture `live_n8n_credentials`."""
    assert settings.n8n_url == FAKE_N8N_URL
    assert settings.n8n_api_key == FAKE_SECRET


def test_modo_live_credenciais_so_na_fixture(tmp_path):
    canario = {
        "RUN_LIVE_N8N_TESTS": "1",
        "ORCHESTRATOR_N8N_URL": "https://n8n.canario-live.invalid",
        "ORCHESTRATOR_N8N_API_KEY": "canario-live-key",
    }
    rc, dump, _, saida = _run_probe(
        tmp_path, canario, tests=("test_probe_estado", "test_probe_live", "test_probe_depois_do_live")
    )
    assert rc == 0, saida
    estado = dump["estado"]
    assert estado["orchestrator_env"] == _FAKES_DO_CONFTEST  # nem no ambiente do processo
    assert estado["settings"]["n8n_url"] == FAKE_N8N_URL
    assert estado["settings"]["n8n_api_key"] == FAKE_SECRET
    # DURANTE a fixture: credenciais canario e rede liberada (sem isto, o
    # "depois" abaixo passaria trivialmente mesmo se a fixture nao fizesse nada).
    assert dump["live"]["settings"]["n8n_url"] == "https://n8n.canario-live.invalid"
    assert dump["live"]["settings"]["n8n_api_key"] == "canario-live-key"
    assert dump["live"]["socket_inet"] == "LIBERADO"
    # DEPOIS da fixture: rede bloqueada de novo e credenciais falsas de volta.
    depois = dump["depois_do_live"]
    assert depois["socket_inet"] == "SocketBlockedError"
    assert depois["settings"]["n8n_url"] == FAKE_N8N_URL
    assert depois["settings"]["n8n_api_key"] == FAKE_SECRET
    assert depois["orchestrator_env"] == _FAKES_DO_CONFTEST


def test_fixture_live_sem_opt_in_pula(tmp_path):
    rc, dump, _, saida = _run_probe(tmp_path, {}, tests=("test_probe_live",))
    assert rc == 0, saida
    assert "1 skipped" in saida
    assert "live" not in dump


def test_so_o_teste_live_usa_a_fixture_de_credenciais():
    """A fixture `live_n8n_credentials` libera rede e credenciais reais. Alem
    da checagem em runtime (no conftest), nenhum outro teste pode pedi-la."""
    usos = {
        arquivo.name
        for arquivo in TESTS_DIR.glob("test_*.py")
        if "live_n8n_credentials" in arquivo.read_text(encoding="utf-8")
    }
    assert usos <= {"test_specialist_n8n.py", Path(__file__).name}
