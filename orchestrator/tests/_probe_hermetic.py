"""Sonda executada num pytest FILHO por test_conftest_hermetico.py.

Nao casa com `test_*.py`, entao a suite normal nunca a coleta; so roda quando
passada explicitamente na linha de comando. O processo pai monta um ambiente
"sujo" (variaveis herdadas do shell, `.env` canario no cwd, modo live) e le o
JSON que esta sonda grava em $HERMETIC_PROBE_OUT para conferir o que o
conftest deixou chegar ate os testes.
"""

import json
import os
import socket
from pathlib import Path

from hermetic_support import SDK_ENV_VARS_REMOVED, SDK_TRACING_VARS_FORCED_OFF

_OUT = Path(os.environ["HERMETIC_PROBE_OUT"])


def _dump(key: str, value) -> None:
    data = json.loads(_OUT.read_text()) if _OUT.exists() else {}
    data[key] = value
    _OUT.write_text(json.dumps(data))


if os.environ.get("HERMETIC_PROBE_LLM_AT_IMPORT") == "1":
    # Chamada REAL ao LLM durante a COLETA (fora de qualquer teste/fixture
    # function-scoped): precisa ser bloqueada e reprovar a sessao.
    from langchain_openai import ChatOpenAI

    try:
        ChatOpenAI(model="sonda", api_key="sonda", base_url="https://llm.test.invalid/v1", max_retries=0).invoke(
            "oi"
        )
        _dump("llm_na_coleta", "NAO_BLOQUEADO")
    except Exception as exc:  # noqa: BLE001 - a sonda so registra o tipo
        _dump("llm_na_coleta", type(exc).__name__)


def _settings_snapshot() -> dict:
    from orchestrator.config import settings

    campos = (
        "n8n_url",
        "n8n_api_key",
        "openclaw_gateway_url",
        "openclaw_gateway_token",
        "api_token",
        "openrouter_api_key",
        "langchain_api_key",
        "langchain_tracing_v2",
        "port",
    )
    return {c: getattr(settings, c) for c in campos}


def test_probe_estado():
    sdk = set(SDK_ENV_VARS_REMOVED) | set(SDK_TRACING_VARS_FORCED_OFF)
    try:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).close()
        sock = "LIBERADO"
    except Exception as exc:  # noqa: BLE001
        sock = type(exc).__name__
    _dump(
        "estado",
        {
            "orchestrator_env": {k: v for k, v in os.environ.items() if k.startswith("ORCHESTRATOR_")},
            "sdk_env": {k: v for k, v in os.environ.items() if k in sdk},
            "settings": _settings_snapshot(),
            "socket_inet": sock,
        },
    )


def test_probe_live(live_n8n_credentials):
    _dump("live", {"settings": _settings_snapshot()})


def test_probe_suja_o_ambiente():
    """Teste "mal-comportado": liga tracing e injeta uma ORCHESTRATOR_* sem
    restaurar. A guarda do conftest precisa reprova-lo e limpar a sujeira."""
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["ORCHESTRATOR_API_TOKEN"] = "sujeira"


def test_probe_ambiente_depois_da_sujeira():
    _dump(
        "depois",
        {
            "LANGCHAIN_TRACING_V2": os.environ.get("LANGCHAIN_TRACING_V2"),
            "ORCHESTRATOR_API_TOKEN": os.environ.get("ORCHESTRATOR_API_TOKEN"),
        },
    )
