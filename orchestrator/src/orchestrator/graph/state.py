from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class PendingSpecialist(TypedDict):
    """Um item da fila `pending_specialists`: um despacho concreto que o
    `supervisor` decidiu (via tool-calling) e que ainda precisa ser
    executado por um no de especialista."""

    specialist: str
    instructions: str


def merge_pending_confirmation(old: dict | None, new: dict | None | str) -> dict | None:
    """Reducer do campo `n8n_pending_confirmation`.

    Este campo e a UNICA excecao (junto com `messages`) a regra do
    `fresh_turn_input` de zerar todo o estado "por tarefa" a cada mensagem:
    uma proposta de acao n8n e feita num turno e so pode ser confirmada num
    turno POSTERIOR, entao ela precisa sobreviver entre chamadas de `/v1/turn`
    (persistida pelo checkpointer, igual `messages`).

    Protocolo do update:
      - `None`  -> "nao mexe" (mantem o valor atual). E o que `fresh_turn_input`
        passa a cada turno, justamente para NAO resetar a pendencia.
      - `"clear"` -> apaga a pendencia (acao confirmada e executada, recusada,
        ou expirada - uso unico).
      - `dict`  -> grava/substitui a pendencia (nova proposta de acao).
    """
    if new == "clear":
        return None
    if new is not None:
        return new
    return old


class GraphState(TypedDict):
    """Contrato do estado que trafega entre os nos do grafo (padrao
    Supervisor/Enxame de Especialistas).

    Todo campo abaixo tem escopo "por tarefa" e e zerado pelo
    `fresh_turn_input` a cada mensagem - EXCETO `messages` (memoria de
    conversa, reducer `add_messages`) e `n8n_pending_confirmation` (proposta
    de acao n8n aguardando confirmacao do usuario num turno futuro, reducer
    `merge_pending_confirmation`).
    """

    messages: Annotated[list, add_messages]
    route: str | None
    final_result: str | None
    internal_scratchpad: list[str]
    pending_specialists: list[PendingSpecialist]
    current_specialist: str | None
    iteration_count: int
    last_error: str | None

    # Proposta de acao n8n que MUDA producao (create/activate/deactivate/
    # delete) descrita num turno e aguardando o usuario responder "sim" no
    # turno seguinte. Sobrevive ao `fresh_turn_input` (ver
    # `merge_pending_confirmation`). Formato: ver
    # `graph/n8n_confirmation.build_pending_confirmation`.
    n8n_pending_confirmation: Annotated[dict | None, merge_pending_confirmation]

    # Escopo POR TURNO (zerado pelo `fresh_turn_input`): quando o `supervisor`
    # detecta que a mensagem atual do usuario e uma confirmacao ("sim", "pode")
    # de uma `n8n_pending_confirmation` valida, grava aqui o token dela e
    # despacha o especialista n8n. O `specialist_n8n_node` so executa a acao
    # pendente se este token bater com o da pendencia persistida (vinculo
    # acao<->confirmacao, uso unico).
    n8n_confirmed_token: str | None


def fresh_turn_input(text: str) -> dict:
    """Estado inicial para uma NOVA chamada de nivel superior ao grafo (um
    request em `/v1/turn` ou `/tasks/stream`).

    Motivo de existir - bug real de producao (2026-08-24): o checkpointer
    persiste o `GraphState` INTEIRO por `thread_id` (estavel por conversa),
    entao todo campo sem reset explicito vaza/acumula entre mensagens
    SEPARADAS da mesma conversa (catastrofico para `iteration_count`, que
    travava a conversa num abort permanente depois de poucas mensagens).

    So `messages` e `n8n_pending_confirmation` devem persistir entre chamadas
    (ver GraphState). Todo o resto e escopo "por tarefa" e comeca do zero -
    incluindo `n8n_confirmed_token`, que so vale para o turno em que o
    supervisor detectou a confirmacao.

    `n8n_pending_confirmation` recebe `None` de proposito: o reducer
    `merge_pending_confirmation` trata `None` como "nao mexe", entao a
    pendencia sobrevive a este reset.
    """
    return {
        "messages": [{"role": "user", "content": text}],
        "route": None,
        "final_result": None,
        "internal_scratchpad": [],
        "pending_specialists": [],
        "current_specialist": None,
        "iteration_count": 0,
        "last_error": None,
        # NAO reseta - o reducer trata None como no-op (a pendencia persiste).
        "n8n_pending_confirmation": None,
        "n8n_confirmed_token": None,
    }
