from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from orchestrator.graph.nodes import (
    general_answer_node,
    reason_node,
    route_after_reason,
    specialist_call_node,
)
from orchestrator.graph.state import GraphState
from orchestrator.schemas.routing import RouteDestination


def build_graph(checkpointer: BaseCheckpointSaver):
    """Monta o StateGraph do orquestrador.

    O checkpointer e injetado (nao criado aqui): seu ciclo de vida - abrir a
    conexao antes de aceitar requests, fecha-la no shutdown - e
    responsabilidade do lifespan da app FastAPI (main.py), nao do builder.
    """
    graph = StateGraph(GraphState)

    graph.add_node("reason", reason_node)
    graph.add_node("specialist_call", specialist_call_node)
    graph.add_node("general_answer", general_answer_node)

    graph.add_edge(START, "reason")
    graph.add_conditional_edges(
        "reason",
        route_after_reason,
        {
            RouteDestination.SPECIALIST.value: "specialist_call",
            RouteDestination.GENERAL.value: "general_answer",
        },
    )
    graph.add_edge("specialist_call", END)
    graph.add_edge("general_answer", END)

    return graph.compile(checkpointer=checkpointer)
