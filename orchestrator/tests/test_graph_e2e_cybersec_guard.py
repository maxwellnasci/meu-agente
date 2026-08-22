"""Teste ponta a ponta (grafo completo via `build_graph()`, nao node
isolado): prova que quem bloqueia uma instrucao de scan contra infra de
producao propria e o guard deterministico (`cybersec_guard.
check_production_infra_block`), e nao o bom senso do LLM do supervisor.

O teste anterior (mensagens de usuario em linguagem natural pedindo pra
escanear a producao) sempre foi recusado pelo proprio Supervisor em texto
livre (rota `general`), sem nunca despachar pro `specialist_cybersec` - ou
seja, o guard nunca era exercitado de verdade. Para isolar o guard como a
causa do bloqueio, aqui mockamos so o LLM do supervisor (ChatOpenAI, dentro
de `orchestrator.graph.nodes`) para forcar um `DispatchSpecialist` cujo
`instructions` ainda contem uma keyword de producao - simulando o cenario em
que o roteamento do supervisor falha em aplicar sua propria regra (prompt
injection, ambiguidade, degradacao do modelo) e despacha um payload que
nunca deveria ter saido do supervisor. Dai em diante o grafo real roda sem
mock nenhum: `route_after_supervisor`, `SPECIALIST_ROUTES` e o
`specialist_cybersec_node` de verdade (com o guard real) decidem o
resultado. `OpenClawClient` e mockado so para confirmar, por
`assert_not_called`, que o guard intercepta ANTES de qualquer chamada ao
gateway - se o guard nao existisse, essa chamada aconteceria.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from orchestrator.graph.builder import build_graph


def _mock_chat_openai_factory(dispatch_instructions, synth_text):
    """Devolve o `side_effect` para o `ChatOpenAI` mockado em
    `orchestrator.graph.nodes`: distingue a instancia do supervisor da
    instancia do synthesize_final pela kwarg `temperature` (so o supervisor
    passa `temperature=0` - ver nodes.py), pra cada uma poder ter um
    comportamento de `ainvoke` diferente sem depender de ordem de chamada."""

    supervisor_llm = MagicMock()
    supervisor_llm.bind_tools.return_value = supervisor_llm
    supervisor_llm.ainvoke = AsyncMock(
        side_effect=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "DispatchSpecialist",
                        "args": {"specialist": "cybersec", "instructions": dispatch_instructions},
                        "id": "call_dispatch_1",
                    }
                ],
            ),
            # Segunda rodada do supervisor (apos o especialista devolver o
            # controle): nao despacha mais nada, fila fica vazia e o grafo
            # segue para synthesize_final.
            AIMessage(content="", tool_calls=[]),
        ]
    )

    synth_llm = MagicMock()
    synth_llm.ainvoke = AsyncMock(return_value=AIMessage(content=synth_text))

    def side_effect(*args, **kwargs):
        return supervisor_llm if kwargs.get("temperature") == 0 else synth_llm

    return side_effect, supervisor_llm, synth_llm


@pytest.mark.asyncio
async def test_e2e_guard_blocks_after_real_supervisor_routing_to_cybersec():
    dispatch_instructions = "escaneia a infra Contabo (Amigao/n8n) em busca de vulnerabilidades"
    chat_side_effect, supervisor_llm, _synth_llm = _mock_chat_openai_factory(
        dispatch_instructions, synth_text="Recusei a acao, a infra e de producao propria."
    )

    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "test-e2e-guard-block"}}

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI", side_effect=chat_side_effect),
        patch("orchestrator.graph.nodes.OpenClawClient") as mock_openclaw_cls,
    ):
        final_state = await graph.ainvoke(
            {"messages": [HumanMessage(content="quero testar a seguranca da infra Contabo")]},
            config=config,
        )

    # O supervisor de fato despachou pro especialista de cybersec (prova de
    # que o roteamento passou por ele, nao foi interceptado antes) ...
    assert supervisor_llm.ainvoke.await_count == 2

    # ... e o especialista real (com o guard real) rodou, recusando sem
    # jamais chamar o gateway/OpenClaw - se o guard nao existisse ou fosse
    # burlado, essa chamada teria acontecido.
    mock_openclaw_cls.assert_not_called()

    scratchpad = final_state["internal_scratchpad"]
    assert any("[cybersec]" in note and "RECUSADO" in note for note in scratchpad)
    assert final_state["final_result"] == "Recusei a acao, a infra e de producao propria."


@pytest.mark.asyncio
async def test_e2e_guard_does_not_block_authorized_local_target():
    """Controle negativo: a mesma via ponta a ponta, mas com uma instrucao
    despachada que NAO contem nenhuma keyword de producao - o guard deixa
    passar e o especialista chega a chamar o gateway (aqui mockado com
    sucesso), confirmando que o bloqueio do teste acima e especifico da
    keyword de producao, nao um efeito colateral do mock do supervisor."""
    from orchestrator.schemas.requests import SpecialistCallResult

    dispatch_instructions = (
        "roda a skill 02-vulnerability-scanner contra o projeto local orchestrator/ "
        "(eu controlo e autorizo este alvo)"
    )
    chat_side_effect, supervisor_llm, _synth_llm = _mock_chat_openai_factory(
        dispatch_instructions, synth_text="Rodei o scan local, sem CVEs criticas."
    )

    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "test-e2e-guard-allow"}}

    fake_result = SpecialistCallResult(success=True, output="achados: nenhuma CVE critica")

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI", side_effect=chat_side_effect),
        patch("orchestrator.graph.nodes.OpenClawClient") as mock_openclaw_cls,
    ):
        mock_openclaw_cls.return_value.call = AsyncMock(return_value=fake_result)
        final_state = await graph.ainvoke(
            {"messages": [HumanMessage(content="analisa a seguranca do meu projeto local")]},
            config=config,
        )

    assert supervisor_llm.ainvoke.await_count == 2
    mock_openclaw_cls.return_value.call.assert_awaited_once()

    scratchpad = final_state["internal_scratchpad"]
    assert scratchpad == ["[cybersec] achados: nenhuma CVE critica"]
    assert final_state["final_result"] == "Rodei o scan local, sem CVEs criticas."


@pytest.mark.asyncio
async def test_e2e_guard_does_not_loop_on_supervisor_echoed_caution():
    """Regressao do bug de loop real (relatado em producao): o
    `_SUPERVISOR_SYSTEM_PROMPT` instrui o proprio supervisor a lembrar o
    especialista, na instrucao que ele gera, de nunca tocar em infra de
    producao propria (Contabo/Amigao/n8n/...). Um LLM real as vezes ecoa
    essa advertencia dentro do `instructions` do `DispatchSpecialist` -
    antes do fix, o guard (substring ingenuo) bloqueava essa mencao como se
    fosse um pedido de acao, a recusa (que repete as mesmas keywords) ia
    pro scratchpad, e o supervisor via aquilo na proxima rodada e tentava
    de novo (o mock aqui simula esse "de novo" olhando o proprio prompt:
    so para de despachar quando ve uma nota de sucesso real do cybersec no
    scratchpad) - travando ate `max_supervisor_iterations` e abortando.

    Aqui o supervisor mockado SEMPRE despacha a mesma instrucao com
    linguagem de proibicao (cautela ecoada), a nao ser que o scratchpad ja
    mostre um resultado real (nao-recusado) do cybersec. Com o guard
    corrigido, a 1a rodada ja passa pelo guard, o especialista roda de
    verdade (mock de sucesso) e o supervisor para na 2a rodada - sem
    aproximar do limite de iteracoes e sem abortar."""
    caution_instruction = (
        "Realize um pentest completo no dominio exemplo.com, que o usuario "
        "controla e autorizou explicitamente. Nunca inclua nessa analise "
        "infraestrutura de producao propria como Contabo, Amigao, n8n, "
        "chatwoot ou evolution-api."
    )

    supervisor_llm = MagicMock()
    supervisor_llm.bind_tools.return_value = supervisor_llm

    call_counter = {"n": 0}

    async def supervisor_ainvoke(messages, *args, **kwargs):
        call_counter["n"] += 1
        prompt_text = messages[-1].content if messages else ""
        cybersec_succeeded = "[cybersec]" in prompt_text and "RECUSADO" not in prompt_text
        if cybersec_succeeded:
            return AIMessage(content="", tool_calls=[])
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "DispatchSpecialist",
                    "args": {"specialist": "cybersec", "instructions": caution_instruction},
                    "id": f"call_dispatch_{call_counter['n']}",
                }
            ],
        )

    supervisor_llm.ainvoke = AsyncMock(side_effect=supervisor_ainvoke)

    synth_llm = MagicMock()
    synth_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Pentest concluido em exemplo.com."))

    def chat_side_effect(*args, **kwargs):
        return supervisor_llm if kwargs.get("temperature") == 0 else synth_llm

    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "test-e2e-guard-no-loop"}}

    from orchestrator.schemas.requests import SpecialistCallResult

    fake_result = SpecialistCallResult(success=True, output="achados: nenhuma CVE critica em exemplo.com")

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI", side_effect=chat_side_effect),
        patch("orchestrator.graph.nodes.OpenClawClient") as mock_openclaw_cls,
    ):
        mock_openclaw_cls.return_value.call = AsyncMock(return_value=fake_result)
        final_state = await graph.ainvoke(
            {"messages": [HumanMessage(content="testa a seguranca do meu dominio exemplo.com")]},
            config=config,
        )

    # O especialista rodou de verdade ja na 1a rodada - a advertencia
    # ecoada nao bloqueou a instrucao.
    mock_openclaw_cls.return_value.call.assert_awaited_once()

    # Nao abortou por limite de iteracoes: o supervisor so precisou de 2
    # rodadas (despacha, ve sucesso, para), bem abaixo do limite (4).
    assert final_state.get("iteration_count", 0) <= 2
    assert supervisor_llm.ainvoke.await_count == 2

    scratchpad = final_state["internal_scratchpad"]
    assert all("RECUSADO" not in note for note in scratchpad)
    assert final_state["final_result"] == "Pentest concluido em exemplo.com."
