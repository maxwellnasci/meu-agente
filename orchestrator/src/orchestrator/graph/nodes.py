import logging

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from orchestrator.clients.openclaw_client import OpenClawClient
from orchestrator.config import settings
from orchestrator.graph.state import GraphState
from orchestrator.schemas.requests import SpecialistCallRequest
from orchestrator.schemas.routing import RouteDecision, RouteDestination

_ROUTER_SYSTEM_PROMPT = (
    "Voce e o roteador do Cerebro de um orquestrador de agentes. Leia a "
    "ultima instrucao do usuario e escolha exatamente um destino:\n\n"
    "- specialist: a tarefa exige o Especialista em Programacao (OpenClaw) - "
    "escrever ou editar codigo, executar comandos, mexer em arquivos de um "
    "projeto, debugar, rodar testes, ou qualquer acao que precise de um "
    "sandbox de execucao real.\n"
    "- general: pode ser respondida diretamente, sem executar nada - duvida "
    "conceitual, conversa, explicacao geral, brainstorm."
)

_GENERAL_SYSTEM_PROMPT = (
    "Voce e o Cerebro de um orquestrador de agentes de IA, respondendo "
    "diretamente ao usuario numa conversa. Seja natural e util. Nao "
    "mencione que existe um roteador ou um Especialista por tras - do ponto "
    "de vista do usuario, voce e quem esta respondendo."
)

_logger = logging.getLogger(__name__)


def extract_task_description(messages: list[BaseMessage]) -> str:
    """Extrai a instrucao mais recente do usuario para preencher o
    SpecialistCallRequest.

    `add_messages` (reducer do campo `messages` em GraphState) normaliza
    entradas em objetos BaseMessage, entao aqui assumimos HumanMessage - nao
    dict solto. Usado tanto pelo no quanto pelo event_mapper (que le o mesmo
    formato a partir do `input` bruto do astream_events).
    """
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


async def reason_node(state: GraphState) -> dict:
    """No roteador do Cerebro: classifica a ultima instrucao do usuario via
    LLM com saida estruturada (RouteDecision) e grava o destino em `route`
    para a borda condicional `route_after_reason` decidir o proximo no.

    Se o roteador falhar (timeout, JSON invalido etc.), o erro nao deve
    abortar o grafo - cai para SPECIALIST (OpenClaw), destino mais seguro."""
    task_description = extract_task_description(state["messages"])
    router = ChatOpenAI(
        model=settings.router_model,
        temperature=0,
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    ).with_structured_output(RouteDecision)
    try:
        decision: RouteDecision = await router.ainvoke(
            [
                SystemMessage(content=_ROUTER_SYSTEM_PROMPT),
                HumanMessage(content=task_description),
            ]
        )
        route = decision.destination.value
    except Exception:
        _logger.exception("reason_node: falha ao invocar o router LLM, usando fallback SPECIALIST")
        route = RouteDestination.SPECIALIST.value
    return {"route": route}


def route_after_reason(state: GraphState) -> str:
    """Borda condicional apos `reason`: funcao pura que so le a decisao ja
    gravada em `route` - nao rechama o LLM. Sem rota gravada, prioriza o
    Especialista (OpenClaw) em vez de GENERAL."""
    return state["route"] or RouteDestination.SPECIALIST.value


async def specialist_call_node(state: GraphState) -> dict:
    """No que delega uma tarefa concreta ao Especialista (OpenClaw) via API."""
    client = OpenClawClient()
    task_description = extract_task_description(state["messages"])
    request = SpecialistCallRequest(task_description=task_description)
    result = await client.call(request)
    return {"final_result": result.output if result.success else result.error}


async def general_answer_node(state: GraphState) -> dict:
    """No de resposta direta do Orquestrador, sem o Especialista: chama o LLM
    generalista com o historico completo da conversa e devolve a resposta
    final. Erro aqui nao tem fallback (diferente do roteador) - se o LLM
    falhar, a excecao sobe e vira a resposta de fallback do endpoint /v1/turn
    (ver main.py)."""
    llm = ChatOpenAI(
        model=settings.general_model,
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )
    response = await llm.ainvoke([SystemMessage(content=_GENERAL_SYSTEM_PROMPT), *state["messages"]])
    text = response.content if isinstance(response.content, str) else str(response.content)
    return {"messages": [response], "final_result": text}
