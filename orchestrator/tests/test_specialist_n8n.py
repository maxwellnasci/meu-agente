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
from orchestrator.graph.n8n_confirmation import NEEDS_CONFIRMATION_KEY
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
async def test_node_reads_are_executed_then_reports_final_summary():
    """Leitura/listagem continua rodando direto no loop ReAct, sem gate."""
    state = {
        "pending_specialists": [
            {"specialist": "n8n", "instructions": "lista os workflows e resume o que voce viu"}
        ],
        "internal_scratchpad": [],
    }
    tool_call_response = AIMessage(
        content="",
        tool_calls=[{"name": "N8nListWorkflows", "args": {}, "id": "call_1"}],
    )
    final_response = AIMessage(content="Vi 3 workflows ativos.")

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI") as mock_chat_cls,
        patch("orchestrator.graph.nodes.N8nClient") as mock_client_cls,
    ):
        mock_chat_cls.return_value = _mock_llm([tool_call_response, final_response])
        mock_client_cls.return_value.list_workflows = AsyncMock(return_value={"data": [1, 2, 3]})

        result = await specialist_n8n_node(state)

    mock_client_cls.return_value.list_workflows.assert_awaited_once()
    assert result["pending_specialists"] == []
    assert "last_error" not in result
    assert "n8n_pending_confirmation" not in result
    note = result["internal_scratchpad"][0]
    assert note.startswith("[n8n] Vi 3 workflows ativos.")


@pytest.mark.asyncio
async def test_node_create_does_not_execute_and_becomes_a_pending_confirmation():
    """Regressao do incidente 2026-09-05: 'cria um workflow' NAO cria nada
    na hora - vira uma proposta pendente de confirmacao, gravada no estado."""
    state = {
        "pending_specialists": [
            {"specialist": "n8n", "instructions": "cria um workflow chamado teste-x"}
        ],
        "internal_scratchpad": [],
    }
    tool_call_response = AIMessage(
        content="",
        tool_calls=[{"name": "N8nCreateWorkflow", "args": {"name": "teste-x", "nodes": []}, "id": "call_1"}],
    )

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI") as mock_chat_cls,
        patch("orchestrator.graph.nodes.N8nClient") as mock_client_cls,
    ):
        mock_chat_cls.return_value = _mock_llm([tool_call_response])
        mock_client_cls.return_value.create_workflow = AsyncMock()

        result = await specialist_n8n_node(state)

    mock_client_cls.return_value.create_workflow.assert_not_awaited()
    pend = result["n8n_pending_confirmation"]
    assert pend["action"] == "create"
    assert pend["tool_name"] == "N8nCreateWorkflow"
    assert pend["args"]["name"] == "teste-x"
    assert pend["token"]
    assert "PROPOSTA" in result["internal_scratchpad"][0]
    assert "last_error" not in result


@pytest.mark.asyncio
async def test_node_executes_confirmed_action_once_via_token():
    """Turno de confirmacao: o supervisor setou `n8n_confirmed_token` e
    despachou o n8n - o node executa a acao pendente EXATAMENTE uma vez,
    sem LLM, e limpa a pendencia (uso unico)."""
    pend = {
        "token": "tok-abc",
        "tool_name": "N8nCreateWorkflow",
        "action": "create",
        "workflow_id": None,
        "workflow_name": "teste-x",
        "args": {"name": "teste-x", "nodes": []},
        "expires_at": 9_999_999_999,
        "summary": "criar um novo workflow 'teste-x'.",
    }
    state = {
        "pending_specialists": [{"specialist": "n8n", "instructions": "O usuario CONFIRMOU. Execute."}],
        "internal_scratchpad": [],
        "n8n_pending_confirmation": pend,
        "n8n_confirmed_token": "tok-abc",
    }

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI") as mock_chat_cls,
        patch("orchestrator.graph.nodes.N8nClient") as mock_client_cls,
    ):
        mock_chat_cls.return_value = _mock_llm([])
        mock_client_cls.return_value.create_workflow = AsyncMock(return_value={"id": "wf123", "name": "teste-x"})

        result = await specialist_n8n_node(state)

    mock_client_cls.return_value.create_workflow.assert_awaited_once()
    assert result["n8n_pending_confirmation"] == "clear"
    note = result["internal_scratchpad"][0]
    assert "executada" in note
    assert "wf123" in note


@pytest.mark.asyncio
async def test_node_rejects_confirmed_token_that_does_not_match_pending():
    """Token de confirmacao que nao bate com a pendencia (reuso, corrida,
    adulteracao) -> nada e executado."""
    pend = {
        "token": "real-token",
        "tool_name": "N8nDeleteWorkflow",
        "action": "delete",
        "workflow_id": "wf9",
        "workflow_name": None,
        "args": {"workflow_id": "wf9"},
        "expires_at": 9_999_999_999,
        "summary": "EXCLUIR PERMANENTEMENTE o workflow id wf9.",
    }
    state = {
        "pending_specialists": [{"specialist": "n8n", "instructions": "confirmado"}],
        "internal_scratchpad": [],
        "n8n_pending_confirmation": pend,
        "n8n_confirmed_token": "outro-token",
    }

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI") as mock_chat_cls,
        patch("orchestrator.graph.nodes.N8nClient") as mock_client_cls,
    ):
        mock_chat_cls.return_value = _mock_llm([])
        mock_client_cls.return_value.delete_workflow = AsyncMock()

        result = await specialist_n8n_node(state)

    mock_client_cls.return_value.delete_workflow.assert_not_awaited()
    assert result["n8n_pending_confirmation"] == "clear"
    assert "expirou" in result["internal_scratchpad"][0] or "nao corresponde" in result["internal_scratchpad"][0]


@pytest.mark.asyncio
async def test_node_rejects_confirmed_token_when_pending_expired():
    """Pendencia expirada no momento da confirmacao -> nada executado."""
    pend = {
        "token": "tok-abc",
        "tool_name": "N8nActivateWorkflow",
        "action": "activate",
        "workflow_id": "wf1",
        "workflow_name": None,
        "args": {"workflow_id": "wf1"},
        "expires_at": 1,  # muito no passado
        "summary": "ATIVAR o workflow id wf1.",
    }
    state = {
        "pending_specialists": [{"specialist": "n8n", "instructions": "sim"}],
        "internal_scratchpad": [],
        "n8n_pending_confirmation": pend,
        "n8n_confirmed_token": "tok-abc",
    }

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI") as mock_chat_cls,
        patch("orchestrator.graph.nodes.N8nClient") as mock_client_cls,
    ):
        mock_chat_cls.return_value = _mock_llm([])
        mock_client_cls.return_value.activate_workflow = AsyncMock()

        result = await specialist_n8n_node(state)

    mock_client_cls.return_value.activate_workflow.assert_not_awaited()
    assert result["n8n_pending_confirmation"] == "clear"


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
    request = httpx.Request("GET", "http://n8n.local/api/v1/workflows/x")
    response = httpx.Response(status_code=404, request=request)
    client.get_workflow = AsyncMock(side_effect=httpx.HTTPStatusError("not found", request=request, response=response))

    result = await _run_n8n_tool(client, "N8nGetWorkflow", {"workflow_id": "x"}, "consulta o workflow x")

    assert "404" in result["error"]


@pytest.mark.asyncio
async def test_run_n8n_tool_executes_write_action_on_bypass_confirmation():
    """Com bypass_confirmation=True (caminho de acao ja confirmada pelo
    usuario) a tool de escrita executa de verdade."""
    client = MagicMock()
    client.delete_workflow = AsyncMock(return_value={})

    result = await _run_n8n_tool(
        client, "N8nDeleteWorkflow", {"workflow_id": "x"}, "EXCLUIR o workflow x", bypass_confirmation=True
    )

    client.delete_workflow.assert_awaited_once_with("x")
    assert "error" not in result


@pytest.mark.asyncio
async def test_run_n8n_tool_rejects_unknown_tool_name():
    client = MagicMock()
    result = await _run_n8n_tool(client, "SomeUnknownTool", {}, "")
    assert result == {"error": "tool desconhecida: SomeUnknownTool"}


@pytest.mark.asyncio
async def test_run_n8n_tool_blocks_write_action_without_confirmation():
    """Regressao do incidente 2026-09-05: qualquer tool de escrita
    (create/activate/deactivate/delete) chamada pelo LLM sem confirmacao
    NAO executa - vira uma pendencia de confirmacao."""
    client = MagicMock()
    client.delete_workflow = AsyncMock()

    result = await _run_n8n_tool(client, "N8nDeleteWorkflow", {"workflow_id": "x"}, "organiza os workflows")

    assert NEEDS_CONFIRMATION_KEY in result
    assert result[NEEDS_CONFIRMATION_KEY]["action"] == "delete"
    client.delete_workflow.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_n8n_tool_preserves_read_operations():
    """Leitura/listagem nunca passa pelo gate de confirmacao."""
    client = MagicMock()
    client.list_workflows = AsyncMock(return_value={"data": []})
    client.get_workflow = AsyncMock(return_value={"id": "a"})

    assert NEEDS_CONFIRMATION_KEY not in await _run_n8n_tool(client, "N8nListWorkflows", {}, "lista tudo")
    assert NEEDS_CONFIRMATION_KEY not in await _run_n8n_tool(client, "N8nGetWorkflow", {"workflow_id": "a"}, "consulta a")
    client.list_workflows.assert_awaited_once()
    client.get_workflow.assert_awaited_once()


@pytest.mark.asyncio
async def test_node_blocks_llm_initiated_deactivate_without_confirmation():
    """Regressao end-to-end: mesmo que o LLM do especialista n8n chame
    N8nDeactivateWorkflow por conta propria, o node nao executa a tool - a
    acao vira uma proposta pendente de confirmacao, sem side effect real."""
    state = {
        "pending_specialists": [{"specialist": "n8n", "instructions": "lista os workflows ativos"}],
        "internal_scratchpad": [],
    }
    tool_call_response = AIMessage(
        content="",
        tool_calls=[{"name": "N8nDeactivateWorkflow", "args": {"workflow_id": "wf1"}, "id": "call_1"}],
    )

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI") as mock_chat_cls,
        patch("orchestrator.graph.nodes.N8nClient") as mock_client_cls,
    ):
        mock_chat_cls.return_value = _mock_llm([tool_call_response])
        mock_client_cls.return_value.deactivate_workflow = AsyncMock()

        result = await specialist_n8n_node(state)

    mock_client_cls.return_value.deactivate_workflow.assert_not_awaited()
    assert result["n8n_pending_confirmation"]["action"] == "deactivate"
    assert result["n8n_pending_confirmation"]["workflow_id"] == "wf1"
    assert "PROPOSTA" in result["internal_scratchpad"][0]


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
