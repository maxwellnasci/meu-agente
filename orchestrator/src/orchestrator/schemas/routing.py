import copy
from enum import Enum

from pydantic import BaseModel, Field


class RouteDestination(str, Enum):
    """Rotulo de observabilidade gravado pelo `supervisor` no campo `route`
    do estado (ver event_mapper.py) - nao controla mais o roteamento do
    grafo (isso e feito pela fila `pending_specialists`), so descreve pra
    quem consome o stream se a rodada envolveu ou nao um especialista."""

    SPECIALIST = "specialist"
    GENERAL = "general"


class SpecialistName(str, Enum):
    """Especialistas que o `supervisor` pode despachar via a tool
    `DispatchSpecialist`. Cada valor precisa ter uma entrada correspondente
    em `nodes.SPECIALIST_ROUTES` (nome -> no do grafo) - e essa dupla
    amarracao (aqui + SPECIALIST_ROUTES) que faz o enxame ser extensivel:
    adicionar um novo especialista e adicionar um valor aqui, um no novo e
    uma entrada em SPECIALIST_ROUTES."""

    OPENCLAW = "openclaw"
    CYBERSEC = "cybersec"
    N8N = "n8n"
    RAG = "rag"


# Descricao de cada especialista no schema da tool (o que o LLM do supervisor
# le para escolher). Uma entrada por valor de SpecialistName.
_DESCRICOES: dict[SpecialistName, str] = {
    SpecialistName.OPENCLAW: (
        "openclaw: Especialista em Programacao - "
        "escrever/editar codigo, executar comandos, mexer em arquivos de um "
        "projeto, debugar, rodar testes, ou qualquer acao que precise de um "
        "sandbox de execucao real."
    ),
    SpecialistName.CYBERSEC: (
        "cybersec: Especialista em Ciberseguranca - "
        "recon/OSINT, scan de vulnerabilidades, pentest web/API/cloud/rede, "
        "analise de log, threat hunting, etc. So pode executar acoes ativas "
        "(scans, testes de exploracao) contra um alvo se a propria instrucao "
        "autorizar esse alvo explicitamente - nunca contra infraestrutura de "
        "producao ou de terceiros sem autorizacao explicita na instrucao."
    ),
    SpecialistName.N8N: (
        "n8n: Especialista de Automacao - tem tool-calling real contra a API "
        "REST de uma instancia de n8n em producao: criar, editar, deletar, "
        "ativar/desativar e disparar execucao (via webhook) de workflows, "
        "alem de listar/consultar os que ja existem."
    ),
    SpecialistName.RAG: (
        "rag: Especialista de Procedimentos - perguntas sobre procedimentos/"
        "manual do supermercado: recebimento, validade, troca, caixa, "
        "higienizacao, precos e etiquetas. So consulta o manual (leitura), "
        "nao executa nada."
    ),
}

# Especialistas que dependem de uma chave de config (desligados por padrao).
OPCIONAIS = frozenset({SpecialistName.RAG})


def especialistas_ativos(rag_enabled: bool) -> list[SpecialistName]:
    """Os que o supervisor pode oferecer/despachar neste ambiente."""
    return [e for e in SpecialistName if e not in OPCIONAIS or (e is SpecialistName.RAG and rag_enabled)]


def descricao_do_campo(ativos: list[SpecialistName]) -> str:
    return "Qual especialista acionar. " + " ".join(_DESCRICOES[e] for e in ativos)


class DispatchSpecialist(BaseModel):
    """Tool exposta ao LLM do `supervisor` via `bind_tools`: cada chamada
    desta tool enfileira um despacho concreto em `pending_specialists`. O
    LLM pode fazer varias chamadas paralelas nesta mesma rodada para
    acionar mais de um especialista.

    Esta classe e o catalogo COMPLETO (valida os argumentos). O schema que o
    LLM realmente recebe sai de `dispatch_tool(rag_enabled)`, que tira do
    enum e da descricao os especialistas desligados neste ambiente."""

    specialist: SpecialistName = Field(description=descricao_do_campo(list(SpecialistName)))
    instructions: str = Field(
        description=(
            "Instrucao especifica e autocontida para este especialista executar "
            "(nao apenas repetir a mensagem original do usuario sem contexto). "
            "Para o cybersec: se a acao for ativa (scan/teste/exploit), inclua "
            "explicitamente o alvo e a autorizacao do usuario para aquele alvo - "
            "sem isso o especialista vai recusar a acao ativa."
        )
    )


_INSTRUCOES_RAG = " Para o rag: repita a pergunta do usuario como ela foi feita."


def dispatch_tool(rag_enabled: bool) -> dict:
    """Schema OpenAI da tool DispatchSpecialist so com os especialistas
    ativos (enum E descricao). E o que vai no `bind_tools` do supervisor."""
    from langchain_core.utils.function_calling import convert_to_openai_tool

    ativos = especialistas_ativos(rag_enabled)
    tool = copy.deepcopy(convert_to_openai_tool(DispatchSpecialist))
    props = tool["function"]["parameters"]["properties"]
    props["specialist"]["enum"] = [e.value for e in ativos]
    props["specialist"]["description"] = descricao_do_campo(ativos)
    if SpecialistName.RAG in ativos:
        props["instructions"]["description"] += _INSTRUCOES_RAG
    return tool
