from typing import Any

from orchestrator.graph.nodes import extract_task_description
from orchestrator.schemas.events import (
    NodeStartedEvent,
    SpecialistCalledEvent,
    StreamEvent,
    TaskCompletedEvent,
    TokenEvent,
)

# Nome que o LangGraph da ao evento de inicio/fim do grafo como um todo
# (distinto dos nos individuais "reason"/"specialist_call").
_GRAPH_ROOT_NAME = "LangGraph"


def map_langgraph_event(raw_event: dict[str, Any]) -> StreamEvent | None:
    """Traduz um evento bruto de `graph.astream_events` (LangGraph) para o
    contrato tipado de StreamEvent consumido pela API (schemas/events.py).

    Retorna None para eventos internos do LangGraph sem equivalente no
    contrato publico (ex.: on_chain_stream de nos intermediarios, eventos de
    retriever/tool nao usados por este grafo) - o chamador (main.py) apenas
    nao emite nada nesse caso, sem quebrar o stream.
    """
    event_type = raw_event.get("event")
    name = raw_event.get("name", "")
    data = raw_event.get("data", {})

    if event_type == "on_chain_start" and name == "specialist_call":
        graph_input = data.get("input") or {}
        messages = graph_input.get("messages", []) if isinstance(graph_input, dict) else []
        return SpecialistCalledEvent(task_description=extract_task_description(messages))

    if event_type == "on_chain_start" and name in ("reason", "general_answer"):
        return NodeStartedEvent(node_name=name)

    if event_type == "on_chat_model_stream":
        chunk = data.get("chunk")
        content = getattr(chunk, "content", "") if chunk is not None else ""
        if content:
            return TokenEvent(content=content)

    if event_type == "on_chain_end" and name == _GRAPH_ROOT_NAME:
        output = data.get("output") or {}
        result = output.get("final_result", "") if isinstance(output, dict) else ""
        return TaskCompletedEvent(result=result or "")

    return None
