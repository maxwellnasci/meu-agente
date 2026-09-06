"""Fluxo ponta a ponta (grafo real via `build_graph`, multi-turn com o mesmo
thread_id - como `/v1/turn` faz de verdade) do gate de confirmacao de acoes
n8n que mudam producao.

Cobre os requisitos da etapa P0 (ver
ANALISE_CEREBRO_AGENTE_CONTABO_2026-09-06.md, secao "Revisao independente"):
  - acao de escrita sem confirmacao e BLOQUEADA (vira proposta pendente);
  - confirmacao valida ("sim") executa a acao exatamente uma vez;
  - "nao" cancela sem executar nada;
  - confirmacao reutilizada nao re-executa;
  - confirmacao expirada nao executa;
  - criar nunca ativa no mesmo turno;
  - leitura/listagem continua passando direto.

Todos os LLMs (`ChatOpenAI` em `orchestrator.graph.nodes`) sao mockados por
um fake que escolhe o comportamento pelo system prompt (supervisor / n8n /
synthesize), sem depender de ordem de chamada.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from orchestrator.graph import n8n_confirmation
from orchestrator.graph.builder import build_graph
from orchestrator.graph.nodes import (
    _N8N_SYSTEM_PROMPT,
    _SUPERVISOR_SYSTEM_PROMPT,
    _SYNTHESIZE_SYSTEM_PROMPT,
)
from orchestrator.graph.state import fresh_turn_input


class _FakeLLM:
    """Um unico fake para os tres papeis. `bind_tools` devolve o proprio
    objeto; `ainvoke` roteia pelo system prompt (messages[0])."""

    def __init__(self, supervisor, n8n, synth):
        self._supervisor = supervisor
        self._n8n = n8n
        self._synth = synth
        self.calls = {"supervisor": 0, "n8n": 0, "synth": 0}

    def bind_tools(self, *_a, **_k):
        return self

    async def ainvoke(self, messages, *_a, **_k):
        system = messages[0].content
        human = messages[-1].content
        if system == _SUPERVISOR_SYSTEM_PROMPT:
            self.calls["supervisor"] += 1
            return self._supervisor(human)
        if system == _N8N_SYSTEM_PROMPT:
            self.calls["n8n"] += 1
            return self._n8n(human)
        if system == _SYNTHESIZE_SYSTEM_PROMPT:
            self.calls["synth"] += 1
            return self._synth(human)
        raise AssertionError(f"system prompt inesperado: {system[:40]}")


def _dispatch_n8n(instructions):
    return AIMessage(
        content="",
        tool_calls=[{"name": "DispatchSpecialist", "args": {"specialist": "n8n", "instructions": instructions}, "id": "d1"}],
    )


def _no_dispatch():
    return AIMessage(content="", tool_calls=[])


def _tool_call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "t1"}])


def _supervisor_create_once(human):
    # Despacha o n8n so no 1o turno (pedido cru de criar). Depois que ha
    # proposta pendente ou acao ja executada no scratchpad, nao despacha mais.
    if "cria" in human.lower() and "PROPOSTA" not in human and "confirmada" not in human:
        return _dispatch_n8n("cria um workflow chamado meu-teste")
    return _no_dispatch()


def _synth(_human):
    return AIMessage(content="(resposta ao usuario)")


@pytest.fixture
def graph():
    return build_graph(MemorySaver())


@pytest.mark.asyncio
async def test_write_without_confirmation_is_blocked_then_confirmation_creates_once(graph):
    fake = _FakeLLM(
        supervisor=_supervisor_create_once,
        n8n=lambda _h: _tool_call("N8nCreateWorkflow", {"name": "meu-teste", "nodes": []}),
        synth=_synth,
    )
    client = MagicMock()
    client.create_workflow = AsyncMock(return_value={"id": "wf1", "name": "meu-teste"})
    client.activate_workflow = AsyncMock()
    config = {"configurable": {"thread_id": "flow-create-confirm"}}

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI", return_value=fake),
        patch("orchestrator.graph.nodes.N8nClient", return_value=client),
    ):
        # Turno 1: "cria um workflow" -> NAO cria, vira proposta pendente.
        t1 = await graph.ainvoke(fresh_turn_input("cria um workflow chamado meu-teste"), config=config)
        assert client.create_workflow.await_count == 0
        pend = t1["n8n_pending_confirmation"]
        assert pend is not None and pend["action"] == "create"
        assert any("PROPOSTA" in n for n in t1["internal_scratchpad"])

        # Turno 2: "sim" -> executa a criacao exatamente uma vez.
        t2 = await graph.ainvoke(fresh_turn_input("sim"), config=config)
        client.create_workflow.assert_awaited_once()
        # Criar nunca ativa no mesmo turno.
        client.activate_workflow.assert_not_awaited()
        assert t2["n8n_pending_confirmation"] is None

        # Turno 3: "sim" de novo -> pendencia ja consumida, nada re-executa.
        await graph.ainvoke(fresh_turn_input("sim"), config=config)
        client.create_workflow.assert_awaited_once()


@pytest.mark.asyncio
async def test_deny_cancels_pending_without_executing(graph):
    fake = _FakeLLM(
        supervisor=_supervisor_create_once,
        n8n=lambda _h: _tool_call("N8nCreateWorkflow", {"name": "meu-teste", "nodes": []}),
        synth=_synth,
    )
    client = MagicMock()
    client.create_workflow = AsyncMock(return_value={"id": "wf1"})
    config = {"configurable": {"thread_id": "flow-deny"}}

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI", return_value=fake),
        patch("orchestrator.graph.nodes.N8nClient", return_value=client),
    ):
        await graph.ainvoke(fresh_turn_input("cria um workflow chamado meu-teste"), config=config)
        t2 = await graph.ainvoke(fresh_turn_input("nao"), config=config)

    client.create_workflow.assert_not_awaited()
    assert t2["n8n_pending_confirmation"] is None
    assert any("RECUSOU" in n for n in t2["internal_scratchpad"])


@pytest.mark.asyncio
async def test_expired_pending_is_not_executed_on_confirmation(graph, monkeypatch):
    clock = {"t": 1_000.0}
    monkeypatch.setattr(n8n_confirmation, "_now", lambda: clock["t"])

    fake = _FakeLLM(
        supervisor=_supervisor_create_once,
        n8n=lambda _h: _tool_call("N8nCreateWorkflow", {"name": "meu-teste", "nodes": []}),
        synth=_synth,
    )
    client = MagicMock()
    client.create_workflow = AsyncMock(return_value={"id": "wf1"})
    config = {"configurable": {"thread_id": "flow-expired"}}

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI", return_value=fake),
        patch("orchestrator.graph.nodes.N8nClient", return_value=client),
    ):
        await graph.ainvoke(fresh_turn_input("cria um workflow chamado meu-teste"), config=config)
        clock["t"] += 10_000  # muito depois do TTL (900s)
        t2 = await graph.ainvoke(fresh_turn_input("sim"), config=config)

    client.create_workflow.assert_not_awaited()
    assert t2["n8n_pending_confirmation"] is None
    assert any("expirou" in n.lower() for n in t2["internal_scratchpad"])


@pytest.mark.asyncio
async def test_reads_are_preserved(graph):
    def supervisor(_h):
        if "PROPOSTA" in _h or "listou" in _h.lower() or "[n8n]" in _h:
            return _no_dispatch()
        return _dispatch_n8n("lista os workflows")

    n8n_steps = {"n": 0}

    def n8n(_h):
        n8n_steps["n"] += 1
        if n8n_steps["n"] == 1:
            return _tool_call("N8nListWorkflows", {})
        return AIMessage(content="Listei 2 workflows.")

    fake = _FakeLLM(supervisor=supervisor, n8n=n8n, synth=_synth)
    client = MagicMock()
    client.list_workflows = AsyncMock(return_value={"data": [{"id": "a"}, {"id": "b"}]})
    config = {"configurable": {"thread_id": "flow-reads"}}

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI", return_value=fake),
        patch("orchestrator.graph.nodes.N8nClient", return_value=client),
    ):
        t1 = await graph.ainvoke(fresh_turn_input("lista os workflows"), config=config)

    client.list_workflows.assert_awaited_once()
    assert "n8n_pending_confirmation" not in t1 or t1["n8n_pending_confirmation"] is None
    assert any("[n8n]" in n for n in t1["internal_scratchpad"])


@pytest.mark.asyncio
async def test_activation_requires_its_own_confirmation_after_create(graph):
    """Depois de criar (confirmado), 'ativa esse' vira NOVA proposta -
    ativacao tem confirmacao propria, separada da criacao."""
    created = {"done": False}

    def supervisor(human):
        h = human.lower()
        if "ativa" in h and "PROPOSTA" not in human and "ATIVAR" not in human:
            return _dispatch_n8n("ativa o workflow meu-teste id wf1")
        if "cria" in h and "PROPOSTA" not in human and "confirmada" not in human:
            return _dispatch_n8n("cria um workflow chamado meu-teste")
        return _no_dispatch()

    def n8n(_h):
        if created["done"]:
            return _tool_call("N8nActivateWorkflow", {"workflow_id": "wf1"})
        return _tool_call("N8nCreateWorkflow", {"name": "meu-teste", "nodes": []})

    fake = _FakeLLM(supervisor=supervisor, n8n=n8n, synth=_synth)
    client = MagicMock()
    client.create_workflow = AsyncMock(return_value={"id": "wf1", "name": "meu-teste"})
    client.activate_workflow = AsyncMock(return_value={"id": "wf1", "active": True})
    config = {"configurable": {"thread_id": "flow-activate"}}

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI", return_value=fake),
        patch("orchestrator.graph.nodes.N8nClient", return_value=client),
    ):
        await graph.ainvoke(fresh_turn_input("cria um workflow chamado meu-teste"), config=config)
        await graph.ainvoke(fresh_turn_input("sim"), config=config)
        client.create_workflow.assert_awaited_once()
        created["done"] = True

        t3 = await graph.ainvoke(fresh_turn_input("agora ativa esse workflow"), config=config)
        client.activate_workflow.assert_not_awaited()
        assert t3["n8n_pending_confirmation"]["action"] == "activate"

        await graph.ainvoke(fresh_turn_input("pode ativar sim"), config=config)
        client.activate_workflow.assert_awaited_once()
