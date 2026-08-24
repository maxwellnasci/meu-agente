from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class PendingSpecialist(TypedDict):
    """Um item da fila `pending_specialists`: um despacho concreto que o
    `supervisor` decidiu (via tool-calling) e que ainda precisa ser
    executado por um no de especialista."""

    specialist: str
    instructions: str


class GraphState(TypedDict):
    """Contrato do estado que trafega entre os nos do grafo (padrao
    Supervisor/Enxame de Especialistas).

    Cada no so pode ler/escrever os campos declarados aqui - e a fronteira
    de contrato rigido descrita em docs/ARQUITETURA_ORQUESTRADOR.md.

    Trade-off TypedDict vs BaseModel (Pydantic) aqui: o LangGraph exige que
    o estado seja um TypedDict (ou dataclass) porque ele faz merge parcial
    de dicts a cada transicao de no (reducers como `add_messages` operam
    sobre update dicts, nao sobre instancias validadas). Isso significa que
    NAO ha validacao em runtime deste estado - um no que devolva um valor de
    tipo errado num campo so quebra quando outro no tentar usa-lo, nao no
    momento da escrita. Mitigamos isso mantendo os nos finos (essencialmente
    I/O) e delegando toda validacao de verdade para as fronteiras que sao
    BaseModel de fato: entrada da API (schemas/requests.py) e a chamada ao
    Especialista (SpecialistCallRequest/SpecialistCallResult) - o estado do
    grafo em si e o unico lugar do sistema sem esse cinto de seguranca.
    """

    messages: Annotated[list, add_messages]

    # Decisao gravada pelo `supervisor` (RouteDestination.value) - metadado
    # de observabilidade/streaming (ver event_mapper.py), nao controla mais
    # o roteamento em si (isso e feito por `pending_specialists`).
    route: str | None

    final_result: str | None

    # Notas acumuladas de cada especialista que rodou nesta TAREFA (ex.:
    # "[openclaw] <resultado>"). Sem reducer (LastValue, como os demais
    # campos de escopo "por tarefa" abaixo): cada no de especialista le o
    # valor atual e devolve `existente + [nota nova]` (ver nodes.py) - o
    # efeito e o mesmo de um accumulator (`operator.add`) DENTRO de uma
    # execucao, mas sem o problema de um reducer aditivo: o
    # `fresh_turn_input` (abaixo) precisa poder RESETAR este campo pra
    # lista vazia a cada nova chamada de nivel superior ao grafo, e
    # `operator.add` nao permite reset via input (so soma) - ver
    # `fresh_turn_input` para o motivo disso importar. Lido pelo
    # `synthesize_final` para montar a resposta final ao usuario.
    internal_scratchpad: list[str]

    # Fila de despachos decididos pelo `supervisor` (via bind_tools) e ainda
    # nao executados. O `supervisor` pode enfileirar mais de um especialista
    # numa unica rodada (tool calls paralelas do LLM); cada no de
    # especialista consome o primeiro item e devolve a fila sem ele - por
    # isso este campo e sobrescrito a cada no, sem reducer.
    pending_specialists: list[PendingSpecialist]

    # Especialista em execucao no momento (populado pelo no de especialista
    # ao consumir o topo de `pending_specialists`, limpo ao terminar) - usado
    # para observabilidade/streaming, nao para controle de fluxo.
    current_specialist: str | None

    # Quantas vezes o `supervisor` ja rodou nesta execucao - trava de loop
    # infinito: `route_after_supervisor`/`synthesize_final` abortam com
    # seguranca se isto passar de settings.max_supervisor_iterations.
    iteration_count: int

    # Ultimo erro reportado por um especialista (ou pelo proprio supervisor
    # ao estourar o limite de iteracoes) - lido pelo `synthesize_final` para
    # informar a falha na resposta final, quando aplicavel.
    last_error: str | None


def fresh_turn_input(text: str) -> dict:
    """Estado inicial para uma NOVA chamada de nivel superior ao grafo (um
    request em `/v1/turn` ou `/tasks/stream`), usado como `input` de
    `graph.ainvoke`/`astream_events` em vez de so `{"messages": [...]}`.

    Motivo de existir - bug real observado em producao (2026-08-24): como o
    checkpointer persiste o estado INTEIRO por `thread_id`, e o `thread_id`
    e estavel por conversa (numero de telefone do WhatsApp, nao por
    mensagem), todo campo do `GraphState` sem reset explicito vaza/acumula
    entre mensagens SEPARADAS da MESMA conversa - nao so dentro de uma
    unica tarefa. Isso e catastrofico especificamente para
    `iteration_count`: sem reset, ele nunca volta a 0, entao depois de
    poucas mensagens NO TOTAL (nao por tarefa) a trava de seguranca do
    supervisor dispara e o orquestrador passa a abortar TODA mensagem
    futura daquela conversa, permanentemente - confirmado ao vivo: 4
    mensagens triviais ("responda ola") bastaram para a 5a em diante
    virar sempre a mensagem de abort.

    So `messages` deve mesmo persistir entre chamadas (e o que da memoria
    de conversa de verdade, via o reducer `add_messages`) - todo o resto
    aqui e escopo "por tarefa" e precisa comecar do zero a cada chamada."""
    return {
        "messages": [{"role": "user", "content": text}],
        "route": None,
        "final_result": None,
        "internal_scratchpad": [],
        "pending_specialists": [],
        "current_specialist": None,
        "iteration_count": 0,
        "last_error": None,
    }
