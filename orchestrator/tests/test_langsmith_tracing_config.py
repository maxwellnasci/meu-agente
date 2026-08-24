"""`_configure_langsmith_tracing` (main.py) e a ponte entre `settings`
(prefixo ORCHESTRATOR_, config.py) e as variaveis de ambiente CRUAS que o
SDK do LangChain realmente le (`LANGCHAIN_TRACING_V2`/`LANGCHAIN_API_KEY`/
`LANGCHAIN_PROJECT`) - sem essa ponte, ligar `settings.langchain_tracing_v2`
nao tinha efeito nenhum. Estes testes confirmam a logica da ponte em si
(sem precisar de uma chave real da LangSmith)."""

import os
from unittest.mock import patch

from orchestrator.main import _configure_langsmith_tracing

_ENV_KEYS = ("LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT")


def _clear_env():
    for key in _ENV_KEYS:
        os.environ.pop(key, None)


def test_sets_raw_env_vars_when_tracing_enabled_and_key_present():
    _clear_env()
    try:
        with patch("orchestrator.main.settings") as mock_settings:
            mock_settings.langchain_tracing_v2 = True
            mock_settings.langchain_api_key = "fake-key-for-test"
            mock_settings.langchain_project = "test-project"
            _configure_langsmith_tracing()

        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert os.environ["LANGCHAIN_API_KEY"] == "fake-key-for-test"
        assert os.environ["LANGCHAIN_PROJECT"] == "test-project"
    finally:
        _clear_env()


def test_does_not_set_env_vars_when_tracing_disabled():
    _clear_env()
    try:
        with patch("orchestrator.main.settings") as mock_settings:
            mock_settings.langchain_tracing_v2 = False
            mock_settings.langchain_api_key = None
            _configure_langsmith_tracing()

        assert "LANGCHAIN_TRACING_V2" not in os.environ
    finally:
        _clear_env()


def test_does_not_set_env_vars_when_enabled_but_no_key():
    """Regressao: ligar o campo sem uma chave nao deve setar
    LANGCHAIN_TRACING_V2=true "pela metade" - isso faria o SDK do LangChain
    tentar tracing de verdade e falhar silenciosamente/logar erros de auth,
    em vez de ficar limpo e desligado."""
    _clear_env()
    try:
        with patch("orchestrator.main.settings") as mock_settings:
            mock_settings.langchain_tracing_v2 = True
            mock_settings.langchain_api_key = None
            _configure_langsmith_tracing()

        assert "LANGCHAIN_TRACING_V2" not in os.environ
    finally:
        _clear_env()
