"""Teste local do especialista de automacao (n8n): contrato de estado/
scratchpad do loop ReAct manual do node com o LLM e o N8nClient mockados
(isola a logica sem depender de tool-calling real), e um teste de
integracao real (create+delete isolado, nao mexe nos workflows existentes)
contra a API da instancia de producao quando ha credenciais em .env."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from langchain_core.messages import AIMessage

from orchestrator.clients.n8n_client import N8nClient
from orchestrator.config import settings
from orchestrator.graph.nodes import _run_n8n_tool, specialist_n8n_node

requires_n8n_credentials = pytest.mark.skipif(
    not settings.n8n_url or not settings.n8n_api_key,
    reason="ORCHESTRATOR_N8N_URL/ORCHESTRATOR_N8N_API_KEY nao configurados (.env)",
)


def _mock_llm(responses):
    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.ainvoke = AsyncMock(side_effect=responses)
    return llm


@pytest.mark.asyncio
async def test_node_returns_early_when_queue_empty():
    state = {"pending_specialists": [], "internal_scratchpad": []}
    result = await specialist_n8n_node(state)
    assert result == {"current_specialist": None}


@pytest.mark.asyncio
async def test_node_executes_tool_then_reports_final_summary():
    state = {
        "pending_specialists": [
            {"specialist": "n8n", "instructions": "cria um workflow chamado teste-x e resume o que foi feito"}
        ],
        "internal_scratchpad": [],
    }
    tool_call_response = AIMessage(
        content="",
        tool_calls=[{"name": "N8nCreateWorkflow", "args": {"name": "teste-x", "nodes": []}, "id": "call_1"}],
    )
    final_response = AIMessage(content="Criei e ja resumi o workflow teste-x.")

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI") as mock_chat_cls,
        patch("orchestrator.graph.nodes.N8nClient") as mock_client_cls,
    ):
        mock_chat_cls.return_value = _mock_llm([tool_call_response, final_response])
        mock_client_cls.return_value.create_workflow = AsyncMock(return_value={"id": "wf123", "name": "teste-x"})

        result = await specialist_n8n_node(state)

    mock_client_cls.return_value.create_workflow.assert_awaited_once()
    assert result["pending_specialists"] == []
    assert result["current_specialist"] is None
    assert "last_error" not in result
    note = result["internal_scratchpad"][0]
    assert note.startswith("[n8n] Criei e ja resumi o workflow teste-x.")
    assert "N8nCreateWorkflow" in note
    assert "wf123" in note


@pytest.mark.asyncio
async def test_node_reports_error_after_max_steps_without_final_answer():
    state = {
        "pending_specialists": [{"specialist": "n8n", "instructions": "lista todos os workflows"}],
        "internal_scratchpad": [],
    }
    always_tool_call = AIMessage(content="", tool_calls=[{"name": "N8nListWorkflows", "args": {}, "id": "call_loop"}])

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI") as mock_chat_cls,
        patch("orchestrator.graph.nodes.N8nClient") as mock_client_cls,
    ):
        mock_chat_cls.return_value = _mock_llm([always_tool_call] * 6)
        mock_client_cls.return_value.list_workflows = AsyncMock(return_value={"data": []})

        result = await specialist_n8n_node(state)

    assert result["pending_specialists"] == []
    assert "limite de passos" in result["last_error"]
    assert "ERRO" in result["internal_scratchpad"][0]


@pytest.mark.asyncio
async def test_run_n8n_tool_translates_http_error_into_error_dict():
    client = MagicMock()
    request = httpx.Request("DELETE", "http://n8n.local/api/v1/workflows/x")
    response = httpx.Response(status_code=404, request=request)
    client.delete_workflow = AsyncMock(side_effect=httpx.HTTPStatusError("not found", request=request, response=response))

    result = await _run_n8n_tool(client, "N8nDeleteWorkflow", {"workflow_id": "x"})

    assert "404" in result["error"]


@pytest.mark.asyncio
async def test_run_n8n_tool_rejects_unknown_tool_name():
    client = MagicMock()
    result = await _run_n8n_tool(client, "SomeUnknownTool", {})
    assert result == {"error": "tool desconhecida: SomeUnknownTool"}


@requires_n8n_credentials
@pytest.mark.asyncio
async def test_create_and_delete_workflow_against_real_n8n_instance():
    """Integracao real (sem mock): cria um workflow trivial isolado (nome
    unico via uuid4, nao colide com nenhum workflow existente) direto contra
    a instancia de producao configurada em .env via N8nClient (sem passar
    pelo LLM), confirma que existe, deleta, e confirma de forma independente
    (nova chamada GET) que sumiu de verdade."""
    client = N8nClient()
    workflow_name = f"pytest-teste-orchestrator-{uuid.uuid4().hex[:8]}"
    node = {
        "id": "1",
        "name": "NoOp",
        "type": "n8n-nodes-base.noOp",
        "typeVersion": 1,
        "position": [0, 0],
        "parameters": {},
    }

    created = await client.create_workflow(workflow_name, [node], {})
    workflow_id = created["id"]
    try:
        assert created["name"] == workflow_name
        fetched = await client.get_workflow(workflow_id)
        assert fetched["id"] == workflow_id
    finally:
        await client.delete_workflow(workflow_id)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.get_workflow(workflow_id)
    assert exc_info.value.response.status_code == 404
