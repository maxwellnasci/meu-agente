from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class GraphState(TypedDict):
    """Contrato do estado que trafega entre os nos do grafo.

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

    # Decisao gravada pelo no `reason` (RouteDestination.value) - a borda
    # condicional `route_after_reason` so le este campo, nao rechama o LLM.
    route: str | None

    final_result: str | None
