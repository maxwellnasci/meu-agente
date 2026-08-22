from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from orchestrator.graph.nodes import (
    SPECIALIST_ROUTES,
    route_after_specialist,
    route_after_supervisor,
    specialist_cybersec_node,
    specialist_n8n_node,
    specialist_openclaw_node,
    supervisor_node,
    synthesize_final_node,
)
from orchestrator.graph.state import GraphState


def build_graph(checkpointer: BaseCheckpointSaver):
    """Monta o StateGraph do orquestrador no padrao Supervisor/Enxame de
    Especialistas:

        START -> supervisor -[condicional: fila de despachos]-> especialista
        especialista -[condicional: fila/loop]-> proximo especialista | supervisor
        supervisor -[condicional: fila vazia]-> synthesize_final -> END

    O `supervisor` decide via tool-calling quais especialistas acionar
    (SPECIALIST_ROUTES mapeia cada nome de especialista a seu no); os
    especialistas disponiveis sao o OpenClaw (`specialist_openclaw`,
    Programacao), o Ciberseguranca (`specialist_cybersec`) e a Automacao/n8n
    (`specialist_n8n`). Novos especialistas entram adicionando um no aqui e
    uma entrada em SPECIALIST_ROUTES/SpecialistName, sem mexer no resto do
    grafo.

    O checkpointer e injetado (nao criado aqui): seu ciclo de vida - abrir a
    conexao antes de aceitar requests, fecha-la no shutdown - e
    responsabilidade do lifespan da app FastAPI (main.py), nao do builder.
    """
    graph = StateGraph(GraphState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("specialist_openclaw", specialist_openclaw_node)
    graph.add_node("specialist_cybersec", specialist_cybersec_node)
    graph.add_node("specialist_n8n", specialist_n8n_node)
    graph.add_node("synthesize_final", synthesize_final_node)

    graph.add_edge(START, "supervisor")

    # route_after_supervisor/route_after_specialist ja devolvem o NOME DO NO
    # de destino (nao a chave do especialista) - o path_map aqui e so o mapa
    # identidade sobre os nos possiveis, exigido pelo LangGraph para montar o
    # desenho do grafo. Construido a partir de SPECIALIST_ROUTES.values()
    # para builder e nodes nunca desalinharem sobre quais nos existem.
    specialist_node_names = set(SPECIALIST_ROUTES.values())
    supervisor_destinations = {name: name for name in specialist_node_names}
    supervisor_destinations["synthesize_final"] = "synthesize_final"
    graph.add_conditional_edges("supervisor", route_after_supervisor, supervisor_destinations)

    specialist_destinations = {name: name for name in specialist_node_names}
    specialist_destinations["supervisor"] = "supervisor"
    graph.add_conditional_edges("specialist_openclaw", route_after_specialist, specialist_destinations)
    graph.add_conditional_edges("specialist_cybersec", route_after_specialist, specialist_destinations)
    graph.add_conditional_edges("specialist_n8n", route_after_specialist, specialist_destinations)

    graph.add_edge("synthesize_final", END)

    return graph.compile(checkpointer=checkpointer)
