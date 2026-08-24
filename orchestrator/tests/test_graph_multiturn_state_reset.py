"""Regressao de producao (2026-08-24): o checkpointer persiste o `GraphState`
INTEIRO por `thread_id`, e o `thread_id` e estavel por conversa (numero de
telefone), nao por mensagem - `graph.ainvoke` chamado varias vezes com o
mesmo `config` simula exatamente isso: mensagens SEPARADAS da MESMA
conversa via `/v1/turn`, nao rodadas de um unico grafo.

Sem `fresh_turn_input` (ver graph/state.py), campos de escopo "por tarefa"
vazavam/acumulavam entre essas chamadas separadas: `iteration_count` nunca
resetava (confirmado ao vivo: 4 mensagens triviais bastaram pra travar todo
o resto da conversa num abort permanente) e `internal_scratchpad` (antes
com reducer `operator.add`) crescia sem limite, vazando notas de tarefas
antigas pro prompt do supervisor de tarefas futuras completamente
nao-relacionadas.

Estes testes chamam `graph.ainvoke` MAIS DE UMA VEZ com o mesmo `config`
(mesmo thread_id) - e o que faltava na suite antes (ver
test_graph_e2e_cybersec_guard.py, sempre uma unica chamada por teste)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from orchestrator.graph.builder import build_graph
from orchestrator.graph.state import fresh_turn_input


def _no_dispatch_chat_side_effect(synth_text: str):
    supervisor_llm = MagicMock()
    supervisor_llm.bind_tools.return_value = supervisor_llm
    supervisor_llm.ainvoke = AsyncMock(return_value=AIMessage(content="", tool_calls=[]))

    synth_llm = MagicMock()
    synth_llm.ainvoke = AsyncMock(return_value=AIMessage(content=synth_text))

    def side_effect(*args, **kwargs):
        return supervisor_llm if kwargs.get("temperature") == 0 else synth_llm

    return side_effect


@pytest.mark.asyncio
async def test_iteration_count_does_not_accumulate_across_separate_turns():
    """6 mensagens SEPARADAS na mesma conversa (mesmo thread_id), cada uma
    via `fresh_turn_input` (o que `main.py` usa de verdade) - nenhuma deve
    abortar por limite de iteracoes, mesmo o limite (4) sendo menor que o
    numero de mensagens (6). Antes do fix, a 5a mensagem em diante virava
    sempre a mensagem de abort - reproduzido ao vivo em producao."""
    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "test-multiturn-iteration-reset"}}

    with patch("orchestrator.graph.nodes.ChatOpenAI", side_effect=_no_dispatch_chat_side_effect("Ola!")):
        for i in range(6):
            final_state = await graph.ainvoke(fresh_turn_input(f"mensagem de teste numero {i}"), config=config)
            assert final_state["iteration_count"] == 1, f"turno {i}: iteration_count vazou do turno anterior"
            assert final_state["final_result"] == "Ola!"


@pytest.mark.asyncio
async def test_scratchpad_does_not_leak_into_next_turn():
    """Turno 1 despacha pro especialista openclaw (gera nota no
    scratchpad); turno 2 (mesma conversa, fresh_turn_input de novo) nao
    despacha nada - o scratchpad do turno 2 deve estar vazio, nao deve
    conter a nota do turno 1. Sem o fix, a nota do turno 1 vazaria pro
    prompt do supervisor de TODA tarefa futura da mesma conversa,
    crescendo sem limite."""
    from orchestrator.schemas.requests import SpecialistCallResult

    supervisor_llm = MagicMock()
    supervisor_llm.bind_tools.return_value = supervisor_llm
    supervisor_llm.ainvoke = AsyncMock(
        side_effect=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "DispatchSpecialist",
                        "args": {"specialist": "openclaw", "instructions": "lista os arquivos do projeto"},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="", tool_calls=[]),  # turno 1, 2a rodada: encerra
            AIMessage(content="", tool_calls=[]),  # turno 2: nao despacha nada
        ]
    )
    synth_llm = MagicMock()
    synth_llm.ainvoke = AsyncMock(
        side_effect=[AIMessage(content="Turno 1 concluido."), AIMessage(content="Turno 2 concluido.")]
    )

    def chat_side_effect(*args, **kwargs):
        return supervisor_llm if kwargs.get("temperature") == 0 else synth_llm

    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "test-multiturn-scratchpad-reset"}}
    fake_result = SpecialistCallResult(success=True, output="arquivos listados com sucesso")

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI", side_effect=chat_side_effect),
        patch("orchestrator.graph.nodes.OpenClawClient") as mock_openclaw_cls,
    ):
        mock_openclaw_cls.return_value.call = AsyncMock(return_value=fake_result)

        turn1 = await graph.ainvoke(fresh_turn_input("lista os arquivos"), config=config)
        assert turn1["internal_scratchpad"] == ["[openclaw] arquivos listados com sucesso"]

        turn2 = await graph.ainvoke(fresh_turn_input("oi, tudo bem?"), config=config)

    assert turn2["internal_scratchpad"] == [], "nota do turno 1 vazou pro turno 2"
    assert turn2["final_result"] == "Turno 2 concluido."

    # A instrucao que o supervisor recebeu no turno 2 nao deve conter a
    # instrucao/resultado do turno 1 no "progresso ja registrado".
    turn2_supervisor_prompt = supervisor_llm.ainvoke.await_args_list[2].args[0][-1].content
    assert "arquivos listados" not in turn2_supervisor_prompt
