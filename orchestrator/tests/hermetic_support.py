"""Constantes e tipos compartilhados entre o conftest.py e os testes.

Modulo SEM efeitos colaterais (nao mexe em ambiente, rede nem settings): os
testes importam daqui em vez de `from conftest import ...` - importar o
conftest como modulo comum o executa de novo (outra copia, fora do controle do
pytest), o que reaplicaria a blindagem num momento arbitrario.
"""

import socket as _socket

# `socket.socket` da STDLIB, guardado no import deste modulo. O conftest
# importa este modulo ANTES do `disable_socket()` e confere logo depois que
# isto nao e o socket bloqueado do pytest-socket. Substitui o
# `pytest_socket._true_socket` (API privada) no `loopback_socket` abaixo.
STDLIB_SOCKET = _socket.socket

FAKE_SECRET = "test-only-not-a-real-key"

# Hosts sob o TLD reservado `.invalid` (RFC 6761): nunca resolvem. Mesmo que o
# bloqueio de socket falhasse, nenhuma requisicao chegaria a um servico real.
FAKE_N8N_URL = "https://n8n.test.invalid"
FAKE_GATEWAY_URL = "http://openclaw-gateway.test.invalid:18789"

# Unico teste da suite autorizado a usar rede/credenciais reais (n8n de
# producao), e so com RUN_LIVE_N8N_TESTS=1. Ver `live_n8n_credentials` no conftest.
LIVE_N8N_TEST = "test_specialist_n8n.py::test_create_and_delete_workflow_against_real_n8n_instance"

# Variaveis lidas DIRETO pelos SDKs (sem o prefixo ORCHESTRATOR_), que o
# conftest remove do ambiente. As de tracing sao fixadas em "false" alem de
# removidas, para o LangSmith nunca ligar sozinho.
SDK_ENV_VARS_REMOVED = (
    "LANGCHAIN_API_KEY",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_ENDPOINT",
    "LANGSMITH_ENDPOINT",
    "LANGCHAIN_PROJECT",
    "LANGSMITH_PROJECT",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION",
    "OPENROUTER_API_KEY",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
)
SDK_TRACING_VARS_FORCED_OFF = ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING", "LANGCHAIN_TRACING", "LANGSMITH_TRACING_V2")


class RealLLMCallBlocked(RuntimeError):
    """Um teste (ou a coleta, ou uma fixture) tentou chamar um LLM de verdade sem mock."""


_LOOPBACK_HOSTS = ("127.0.0.1", "localhost")


def loopback_socket():
    """Socket TCP REAL, para testes que so precisam reservar/ocupar uma porta
    local (ex.: tests/test_provision_client.py). Fora daqui a suite bloqueia
    `socket.socket` (conftest). Este socket so aceita `bind` em 127.0.0.1 e
    recusa qualquer conexao/envio: ocupa porta no loopback, nunca fala com
    rede nenhuma."""
    class _LoopbackOnlySocket(STDLIB_SOCKET):
        def bind(self, address):
            if address[0] not in _LOOPBACK_HOSTS:
                raise RuntimeError(f"loopback_socket so aceita bind em 127.0.0.1, nao em {address!r}")
            super().bind(("127.0.0.1", address[1]))

        def _no_traffic(self, *args, **kwargs):
            raise RuntimeError("loopback_socket nao conecta nem envia nada (so reserva porta)")

        connect = connect_ex = sendto = sendmsg = _no_traffic

    return _LoopbackOnlySocket(_socket.AF_INET, _socket.SOCK_STREAM)
