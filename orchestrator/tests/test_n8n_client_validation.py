"""Entradas vindas do LLM (workflow_id, path de webhook, metodo HTTP) NAO podem
alterar o destino da requisicao ao n8n.

Achado da auditoria de 2026-11-02: `workflow_id` e `path` eram interpolados
direto na URL. O httpx normaliza segmentos `..`, entao
`get_workflow("../executions/1")` virava `GET /api/v1/executions/1` COM o
header X-N8N-API-KEY anexado - uma prompt injection (OWASP LLM01) conseguia
redirecionar a chave de API para qualquer endpoint da API publica do n8n
(execucoes, credenciais...). Estes testes provam, com transporte simulado
(sem rede), que a requisicao nem chega a ser feita.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from orchestrator.clients.n8n_client import InvalidN8nInput, N8nClient
from orchestrator.graph.n8n_confirmation import NEEDS_CONFIRMATION_KEY
from orchestrator.graph.nodes import _run_n8n_tool

BAD_IDS = [
    "../executions/1",
    "x/../../credentials",
    "..",
    ".",
    "a/b",
    "a\\b",
    "a b",
    "a?x=1",
    "a#frag",
    "%2e%2e/credentials",
    "wf1\n",
    "",
    "x" * 65,
]

GOOD_IDS = ["wf1", "AbC123xyz", "XyZ1abc2DEF3ghi4", "123", "my_wf-2"]

BAD_WEBHOOK_PATHS = [
    "../api/v1/workflows",
    "ok/../../rest/login",
    "ok/./x",
    "/../x",
    "a b",
    "a?x=1",
    "a#f",
    "a\\b",
    "%2e%2e/x",
    "",
    "//evil.example/x",
]

GOOD_WEBHOOK_PATHS = ["meu-hook", "abc_123/deploy", "/leading-slash-ok", "v1.2/evento"]


@pytest.fixture
def sent(monkeypatch):
    """Intercepta o AsyncClient do httpx e registra toda requisicao."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    real = httpx.AsyncClient

    class Patched(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr("orchestrator.clients.n8n_client.httpx.AsyncClient", Patched)
    return requests


def _client() -> N8nClient:
    return N8nClient(base_url="https://n8n.test.invalid", api_key="K")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", BAD_IDS)
@pytest.mark.parametrize(
    "method", ["get_workflow", "delete_workflow", "activate_workflow", "deactivate_workflow"]
)
async def test_workflow_id_invalido_nunca_gera_requisicao(sent, method, bad):
    with pytest.raises(InvalidN8nInput):
        await getattr(_client(), method)(bad)
    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", BAD_IDS)
async def test_update_workflow_id_invalido_nunca_gera_requisicao(sent, bad):
    with pytest.raises(InvalidN8nInput):
        await _client().update_workflow(bad, "n", [], {})
    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("good", GOOD_IDS)
async def test_workflow_id_valido_vai_para_o_path_esperado(sent, good):
    await _client().get_workflow(good)
    assert [r.url.path for r in sent] == [f"/api/v1/workflows/{good}"]
    assert sent[0].headers["x-n8n-api-key"] == "K"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", BAD_WEBHOOK_PATHS)
async def test_webhook_path_invalido_nunca_gera_requisicao(sent, bad):
    with pytest.raises(InvalidN8nInput):
        await _client().trigger_webhook(bad)
    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("good", GOOD_WEBHOOK_PATHS)
async def test_webhook_path_valido_fica_sob_prefixo_webhook(sent, good):
    await _client().trigger_webhook(good)
    assert sent[0].url.path.startswith("/webhook/")
    assert ".." not in sent[0].url.path


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["TRACE", "CONNECT", "FOO", "", "GET /x"])
async def test_webhook_metodo_fora_da_allowlist_e_recusado(sent, bad):
    with pytest.raises(InvalidN8nInput):
        await _client().trigger_webhook("ok", method=bad)
    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ok", ["get", "POST", "put", "Patch", "DELETE"])
async def test_webhook_metodos_permitidos(sent, ok):
    await _client().trigger_webhook("ok", method=ok)
    assert sent[0].method == ok.upper()


# ---- camada do no do grafo: nem propor confirmacao para id malicioso ----


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["N8nDeleteWorkflow", "N8nActivateWorkflow", "N8nDeactivateWorkflow"])
async def test_no_nao_propoe_confirmacao_para_workflow_id_malicioso(tool):
    client = MagicMock()
    for m in ("delete_workflow", "activate_workflow", "deactivate_workflow"):
        setattr(client, m, AsyncMock())
    out = await _run_n8n_tool(client, tool, {"workflow_id": "../credentials/9"}, "apague o workflow")
    assert NEEDS_CONFIRMATION_KEY not in out
    assert "error" in out
    client.delete_workflow.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_devolve_erro_em_vez_de_estourar_para_get_malicioso():
    with patch("orchestrator.graph.nodes.N8nClient"):
        real = _client()
    out = await _run_n8n_tool(real, "N8nGetWorkflow", {"workflow_id": "../executions/1"}, "mostra o workflow")
    assert "error" in out
