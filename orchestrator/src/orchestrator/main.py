import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse

from orchestrator.config import settings
from orchestrator.graph.builder import build_graph
from orchestrator.graph.event_mapper import map_langgraph_event
from orchestrator.graph.state import fresh_turn_input
from orchestrator.persistence.checkpointer import checkpointer_context
from orchestrator.schemas.events import ErrorEvent, TaskFailedEvent
from orchestrator.schemas.requests import TaskRequest, TurnRequest, TurnResponse

# Intervalo de heartbeat do SSE: o sse-starlette manda um "ping" nesse
# intervalo mesmo sem eventos novos do grafo, pra proxies/load balancers nao
# derrubarem a conexao por inatividade.
_SSE_HEARTBEAT_SEC = 15

# Resposta padrao quando o grafo falha ou estoura o timeout em /v1/turn - o
# usuario do WhatsApp recebe uma mensagem em vez de ficar no vacuo esperando
# uma resposta que nunca chega.
_TURN_FALLBACK_REPLY = "Desculpa, tive um problema para processar sua mensagem agora. Tenta de novo em instantes."

# Sem isto, o nivel padrao da raiz e WARNING - os logs de observabilidade
# em nivel INFO adicionados em graph/nodes.py (decisao do supervisor,
# duracao/resultado de cada chamada a especialista) ficariam invisiveis no
# `docker logs`, mesmo existindo no codigo.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
_logger = logging.getLogger(__name__)


def _configure_langsmith_tracing() -> None:
    """Ativa tracing real do LangSmith quando configurado.

    `settings.langchain_tracing_v2`/`langchain_api_key`/`langchain_project`
    (config.py) existiam sem efeito nenhum: o SDK do LangChain le as
    variaveis de ambiente CRUAS (`LANGCHAIN_TRACING_V2`,
    `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`), nao os `Settings` deste
    projeto (que usam o prefixo `ORCHESTRATOR_`) - esta funcao e a ponte
    entre os dois, chamada uma vez no import deste modulo (antes de
    qualquer chamada real ao LangChain). Precisa de uma chave real da
    LangSmith (conta gratuita em smith.langchain.com) em
    `ORCHESTRATOR_LANGCHAIN_API_KEY` para ter efeito; sem chave, o
    tracing continua desligado como sempre esteve."""
    if settings.langchain_tracing_v2 and settings.langchain_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        _logger.info("observabilidade: LangSmith tracing ativado (projeto=%s)", settings.langchain_project)
    elif settings.langchain_tracing_v2:
        _logger.warning(
            "ORCHESTRATOR_LANGCHAIN_TRACING_V2=true mas ORCHESTRATOR_LANGCHAIN_API_KEY nao "
            "configurado - tracing continua desligado"
        )


_configure_langsmith_tracing()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Abre o checkpointer (conexao sqlite assincrona) uma unica vez, monta o
    grafo sobre ele e guarda tudo em app.state - ver checkpointer.py sobre
    por que essa abertura nao pode acontecer por request."""
    async with checkpointer_context() as checkpointer:
        app.state.checkpointer = checkpointer
        app.state.graph = build_graph(checkpointer)
        yield


app = FastAPI(title="Orchestrator", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/turn", response_model=TurnResponse)
async def turn(request: TurnRequest, http_request: Request) -> TurnResponse:
    """Endpoint sincrono consumido pela porta de entrada Node.js (Meta/
    WhatsApp Cloud): recebe uma mensagem, invoca o grafo ate o resultado
    final (sem streaming) e devolve `reply_text` pronto pra resposta ao
    usuario.

    Qualquer falha (erro no grafo, timeout, chamada ao Especialista fora do
    ar) e capturada aqui e vira uma resposta de fallback com HTTP 200 -
    propositalmente nao propaga 500 pro Node.js, porque o contrato desse
    endpoint e sempre devolver algo que possa virar mensagem de WhatsApp,
    nunca deixar o chamador sem texto para repassar ao usuario.
    """
    graph = http_request.app.state.graph
    config = {"configurable": {"thread_id": request.session_key}}
    graph_input = fresh_turn_input(request.text)

    try:
        final_state = await asyncio.wait_for(
            graph.ainvoke(graph_input, config=config),
            timeout=settings.turn_timeout_sec,
        )
        reply_text = final_state.get("final_result") or _TURN_FALLBACK_REPLY
    except Exception:
        _logger.exception("turn: falha ao processar mensagem (session_key=%s)", request.session_key)
        reply_text = _TURN_FALLBACK_REPLY

    return TurnResponse(reply_text=reply_text)


@app.post("/tasks/stream")
async def stream_task(request: TaskRequest, http_request: Request) -> EventSourceResponse:
    """Endpoint de streaming (SSE) de uma tarefa: liga o astream_events do
    grafo aos eventos tipados de schemas/events.py via event_mapper."""
    graph = http_request.app.state.graph

    async def event_generator():
        config = {"configurable": {"thread_id": request.thread_id}}
        graph_input = fresh_turn_input(request.message)

        try:
            async for raw_event in graph.astream_events(graph_input, config=config, version="v2"):
                if await http_request.is_disconnected():
                    break

                try:
                    mapped = map_langgraph_event(raw_event)
                except Exception as exc:
                    error_event = ErrorEvent(message=f"falha ao mapear evento do grafo: {exc}")
                    yield {"event": error_event.type, "data": error_event.model_dump_json()}
                    continue

                if mapped is not None:
                    yield {"event": mapped.type, "data": mapped.model_dump_json()}
        except Exception as exc:
            failed_event = TaskFailedEvent(error=str(exc))
            yield {"event": failed_event.type, "data": failed_event.model_dump_json()}

    return EventSourceResponse(event_generator(), ping=_SSE_HEARTBEAT_SEC)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("orchestrator.main:app", host=settings.host, port=settings.port, reload=True)
