"""Reproduz o bug de loop do guard: o supervisor as vezes gera, para o
`specialist_cybersec`, uma instrucao que ecoa (para NEGAR/excluir) uma das
keywords de infra de producao propria do proprio `_SUPERVISOR_SYSTEM_PROMPT`
(ex.: "...nunca contra Contabo/Amigao/..., isso e proibido" - o supervisor
tentando deixar claro que o alvo NAO e a infra propria). O guard antigo
(`check_production_infra_block`), por so fazer substring match ingenuo,
recusava mesmo essa mencao negada. A recusa nao seta `last_error` e o
controle sempre volta para o `supervisor` (ver `route_after_specialist`),
que via de regra tenta de novo com uma instrucao parecida (ainda citando a
mesma keyword para reforcar a negacao) - reproduzindo a mesma recusa a cada
rodada ate estourar `settings.max_supervisor_iterations` e abortar com a
mensagem generica de seguranca, mesmo o pedido do usuario nunca tendo
mirado infra de producao de verdade.

Este teste mocka o LLM do supervisor com uma decisao condicionada ao
progresso real do grafo (le a mesma string de prompt que `supervisor_node`
monta a partir do `internal_scratchpad`): se o progresso mostra uma recusa
do guard ("RECUSADO"), o mock redespacha cybersec com a mesma instrucao
(simulando o supervisor insistindo); se mostra um resultado real do
especialista ("[cybersec]" sem "RECUSADO"), o mock encerra a rodada. Isso
faz o mock se comportar identico nas duas versoes do codigo - a diferenca
de resultado (loop ate abortar vs. uma unica rodada bem sucedida) vem
inteiramente do guard, nao de logica hardcoded no teste.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from orchestrator.config import settings
from orchestrator.graph.builder import build_graph
from orchestrator.graph.nodes import _ABORT_MESSAGE

# Instrucao plausivel que um roteador real geraria: pede para escanear um
# alvo diferente da infra propria, mas ecoa a keyword "Contabo"/"Amigao"
# citando-a para EXCLUI-LA explicitamente (o mesmo padrao sugerido pelo
# proprio _SUPERVISOR_SYSTEM_PROMPT: "Nunca peca para ele testar a
# infraestrutura de producao... (Contabo, Amigao, ...)").
_ECHO_INSTRUCTIONS = (
    "Verifica a seguranca do site meusite.com.br (o usuario controla e "
    "autoriza este alvo). Importante: nunca contra Contabo, Amigao, n8n, "
    "chatwoot, evolution-api ou WhatsApp Cloud, isso e proibido."
)


def _make_conditional_supervisor_llm():
    """Mock do LLM do supervisor cuja decisao depende do progresso real
    registrado no grafo (via texto do prompt), nao de uma sequencia fixa de
    respostas - assim o mesmo mock reproduz o loop no codigo com bug e o
    fluxo de uma rodada so no codigo corrigido, sem logica condicional
    hardcoded para cada versao."""

    llm = MagicMock()
    llm.bind_tools.return_value = llm

    def _dispatch_cybersec_again(_call_id: str) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "DispatchSpecialist",
                    "args": {"specialist": "cybersec", "instructions": _ECHO_INSTRUCTIONS},
                    "id": _call_id,
                }
            ],
        )

    call_counter = {"n": 0}

    async def ainvoke(messages, *_args, **_kwargs):
        call_counter["n"] += 1
        prompt_text = messages[-1].content if messages else ""
        if "RECUSADO" in prompt_text:
            # Guard recusou na rodada anterior: supervisor insiste,
            # reforcando a mesma negacao da keyword de producao.
            return _dispatch_cybersec_again(f"call_retry_{call_counter['n']}")
        if "[cybersec]" in prompt_text:
            # Especialista ja produziu um resultado real (guard deixou
            # passar): tarefa concluida, nao despacha mais nada.
            return AIMessage(content="", tool_calls=[])
        # Primeira rodada.
        return _dispatch_cybersec_again("call_dispatch_1")

    llm.ainvoke = AsyncMock(side_effect=ainvoke)
    return llm


@pytest.mark.asyncio
async def test_supervisor_self_echo_does_not_loop_to_abort():
    supervisor_llm = _make_conditional_supervisor_llm()
    synth_llm = MagicMock()
    synth_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Rodei o scan no site autorizado, sem achados criticos."))

    def chat_side_effect(*args, **kwargs):
        return supervisor_llm if kwargs.get("temperature") == 0 else synth_llm

    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": "test-self-echo-loop"}}

    from orchestrator.schemas.requests import SpecialistCallResult

    fake_result = SpecialistCallResult(success=True, output="achados: nenhuma CVE critica no site")

    with (
        patch("orchestrator.graph.nodes.ChatOpenAI", side_effect=chat_side_effect),
        patch("orchestrator.graph.nodes.OpenClawClient") as mock_openclaw_cls,
    ):
        mock_openclaw_cls.return_value.call = AsyncMock(return_value=fake_result)
        final_state = await graph.ainvoke(
            {"messages": [HumanMessage(content="verifica a seguranca do meu site meusite.com.br")]},
            config=config,
        )

    # O guard nao deve recusar uma mencao negada/excludente da keyword de
    # producao - o especialista real chega a ser chamado.
    mock_openclaw_cls.return_value.call.assert_awaited_once()

    # Sem loop: uma rodada de despacho + uma rodada de encerramento, bem
    # abaixo do limite de seguranca (prova de que nao precisou do
    # mecanismo de aborto para parar).
    assert supervisor_llm.ainvoke.await_count == 2
    assert supervisor_llm.ainvoke.await_count <= settings.max_supervisor_iterations

    assert final_state["final_result"] != _ABORT_MESSAGE
    assert final_state.get("iteration_count", 0) <= settings.max_supervisor_iterations

    scratchpad = final_state["internal_scratchpad"]
    assert any("RECUSADO" not in note and "[cybersec]" in note for note in scratchpad)
