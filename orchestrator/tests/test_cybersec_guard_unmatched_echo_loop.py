from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from orchestrator.config import settings
from orchestrator.graph.builder import build_graph
from orchestrator.graph.nodes import _ABORT_MESSAGE

_ECHO_INSTRUCTIONS = (
    "Verifica a seguranca do site meusite.com.br. Lembre-se que o alvo "
    "Contabo deve ser ignorado totalmente."
)

def _make_conditional_supervisor_llm():
    llm = MagicMock()
    llm.bind_tools.return_value = llm
    
    call_counter = {"n": 0}

    async def ainvoke(messages, *_args, **_kwargs):
        call_counter["n"] += 1
        prompt_text = messages[-1].content if messages else ""
        if "RECUSADO" in prompt_text:
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "DispatchSpecialist",
                    "args": {"specialist": "cybersec", "instructions": _ECHO_INSTRUCTIONS},
                    "id": f"call_retry_{call_counter['n']}"
                }]
            )
        if "[cybersec]" in prompt_text:
            return AIMessage(content="", tool_calls=[])
        return AIMessage(
            content="",
            tool_calls=[{
                "name": "DispatchSpecialist",
                "args": {"specialist": "cybersec", "instructions": _ECHO_INSTRUCTIONS},
                "id": "call_dispatch_1"
            }]
        )

    llm.ainvoke = AsyncMock(side_effect=ainvoke)
    return llm

@pytest.mark.asyncio
async def test_supervisor_loop_on_unmatched_echo():
    supervisor_llm = _make_conditional_supervisor_llm()
    synth_llm = MagicMock()
    synth_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Rodei o scan no site autorizado."))

    def chat_side_effect(*args, **kwargs):
        return supervisor_llm if kwargs.get("temperature") == 0 else synth_llm

    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "test-unmatched-echo-loop"}}

    from orchestrator.schemas.requests import SpecialistCallResult
    fake_result = SpecialistCallResult(success=True, output="achados: nenhuma CVE critica")

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI", side_effect=chat_side_effect),
        patch("orchestrator.graph.nodes.OpenClawClient") as mock_openclaw_cls,
    ):
        mock_openclaw_cls.return_value.call = AsyncMock(return_value=fake_result)
        final_state = await graph.ainvoke(
            {"messages": [HumanMessage(content="verifica a seguranca do meu site meusite.com.br")]},
            config=config,
        )

    # After the fix (checking user message, which is "verifica a seguranca do meu site meusite.com.br"), 
    # it should NOT be blocked. It should call openclaw.
    # So this test checks that it does NOT loop to abort.
    assert final_state["final_result"] != _ABORT_MESSAGE
    assert supervisor_llm.ainvoke.await_count <= settings.max_supervisor_iterations
    mock_openclaw_cls.return_value.call.assert_awaited_once()

