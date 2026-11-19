"""Invariantes do registro de especialistas (valem para o rag e para os proximos).

Registrar um especialista exige 6 pontos. Esquecer qualquer um destes NAO da
erro nenhum em runtime - o especialista so nunca e escolhido, nunca emite
evento ou nunca devolve o controle ao supervisor:

- `SpecialistName` (schemas/routing.py) <-> `SPECIALIST_ROUTES` (nodes.py);
- descricao no prompt do supervisor e no schema da tool `DispatchSpecialist`;
- `_SPECIALIST_NODE_NAMES` do event_mapper (sem ele, nada de SpecialistCalledEvent);
- no + aresta de saida no builder.

Especialistas OPCIONAIS (hoje so o rag, `ORCHESTRATOR_RAG_ENABLED`) mudam o
que o supervisor oferece: as invariantes rodam nos DOIS estados da chave.
"""

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from orchestrator.config import Settings, settings
from orchestrator.graph import event_mapper
from orchestrator.graph.builder import build_graph
from orchestrator.graph.nodes import (
    SPECIALIST_ROUTES,
    supervisor_node,
    supervisor_system_prompt,
)
from orchestrator.graph.state import fresh_turn_input
from orchestrator.schemas.routing import (
    OPCIONAIS,
    SpecialistName,
    dispatch_tool,
    especialistas_ativos,
)

TODOS = [e.value for e in SpecialistName]


@pytest.fixture(params=[False, True], ids=["rag-desligado", "rag-ligado"])
def rag_enabled(request, monkeypatch):
    monkeypatch.setattr(settings, "rag_enabled", request.param)
    return request.param


def _ativos(rag_enabled: bool) -> list[str]:
    return [e.value for e in especialistas_ativos(rag_enabled)]


def _campo(rag_enabled: bool, nome: str) -> dict:
    return dispatch_tool(rag_enabled)["function"]["parameters"]["properties"][nome]


# --- estaticas (independem da chave) --------------------------------------------


def test_enum_e_rotas_tem_os_mesmos_especialistas():
    assert set(TODOS) == set(SPECIALIST_ROUTES)


def test_event_mapper_conhece_todo_no_de_especialista():
    assert set(SPECIALIST_ROUTES.values()) == event_mapper._SPECIALIST_NODE_NAMES


@pytest.mark.parametrize("no", sorted(SPECIALIST_ROUTES.values()))
def test_grafo_compilado_tem_o_no_e_as_arestas(no):
    grafo = build_graph(MemorySaver()).get_graph()
    assert no in grafo.nodes
    arestas = {(e.source, e.target) for e in grafo.edges}
    assert ("supervisor", no) in arestas, f"supervisor nao despacha para {no}"
    assert (no, "supervisor") in arestas, f"{no} nao devolve o controle ao supervisor"


def test_rag_desligado_por_padrao():
    assert Settings(_env_file=None).rag_enabled is False
    assert OPCIONAIS == {SpecialistName.RAG}


# --- nos dois estados da chave ------------------------------------------------------


def test_supervisor_descreve_exatamente_os_ativos(rag_enabled):
    prompt = supervisor_system_prompt()
    assert "{" not in prompt  # marcador substituido
    for nome in TODOS:
        assert (f"\n- {nome}: " in prompt) is (nome in _ativos(rag_enabled)), nome


def test_tool_do_supervisor_oferece_exatamente_os_ativos(rag_enabled):
    campo = _campo(rag_enabled, "specialist")
    assert campo["enum"] == _ativos(rag_enabled)
    for nome in TODOS:
        assert (f" {nome}: " in f" {campo['description']}") is (nome in _ativos(rag_enabled)), nome
    assert ("Para o rag" in _campo(rag_enabled, "instructions")["description"]) is rag_enabled


def test_rag_ligado_tem_descricao_do_manual():
    assert "manual do supermercado" in _campo(True, "specialist")["description"]
    assert "manual" not in _campo(False, "specialist")["description"]
    assert "manual do supermercado" not in supervisor_system_prompt(False)


@pytest.mark.asyncio
async def test_despacho_para_especialista_inativo_nunca_e_roteado(rag_enabled):
    """Mesmo que o LLM alucine "rag" com a chave desligada."""
    llm = type("L", (), {})()
    vistos = {}
    llm.bind_tools = lambda tools: (vistos.update(tools=tools), llm)[1]

    async def ainvoke(msgs):
        vistos["system"] = msgs[0].content
        return AIMessage(
            content="",
            tool_calls=[
                {"name": "DispatchSpecialist", "args": {"specialist": "rag", "instructions": "q"}, "id": "1"},
                {"name": "DispatchSpecialist", "args": {"specialist": "openclaw", "instructions": "q"}, "id": "2"},
            ],
        )

    llm.ainvoke = ainvoke
    from unittest.mock import patch

    with patch("orchestrator.graph.nodes.ChatOpenAI", return_value=llm):
        out = await supervisor_node(fresh_turn_input("q"))
    assert [p["specialist"] for p in out["pending_specialists"]] == (["rag", "openclaw"] if rag_enabled else ["openclaw"])
    # o que o supervisor de fato entregou ao LLM: tool e prompt do ambiente
    (tool,) = vistos["tools"]
    assert tool["function"]["parameters"]["properties"]["specialist"]["enum"] == _ativos(rag_enabled)
    assert ("\n- rag: " in vistos["system"]) is rag_enabled


@pytest.mark.asyncio
async def test_no_do_rag_desligado_nao_consulta_nada(monkeypatch):
    from orchestrator.graph import rag_specialist
    from orchestrator.graph.nodes import specialist_rag_node

    monkeypatch.setattr(settings, "rag_enabled", False)
    monkeypatch.setattr(rag_specialist, "buscar_trechos", lambda p: pytest.fail("consultou com o rag desligado"))
    out = await specialist_rag_node({"messages": [], "pending_specialists": [{"specialist": "rag", "instructions": "q"}]})
    assert out["last_error"] == "especialista rag desligado neste ambiente"
