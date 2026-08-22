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


class DispatchSpecialist(BaseModel):
    """Tool exposta ao LLM do `supervisor` via `bind_tools`: cada chamada
    desta tool enfileira um despacho concreto em `pending_specialists`. O
    LLM pode fazer varias chamadas paralelas nesta mesma rodada para
    acionar mais de um especialista."""

    specialist: SpecialistName = Field(
        description=(
            "Qual especialista acionar. openclaw: Especialista em Programacao - "
            "escrever/editar codigo, executar comandos, mexer em arquivos de um "
            "projeto, debugar, rodar testes, ou qualquer acao que precise de um "
            "sandbox de execucao real. cybersec: Especialista em Ciberseguranca - "
            "recon/OSINT, scan de vulnerabilidades, pentest web/API/cloud/rede, "
            "analise de log, threat hunting, etc. So pode executar acoes ativas "
            "(scans, testes de exploracao) contra um alvo se a propria instrucao "
            "autorizar esse alvo explicitamente - nunca contra infraestrutura de "
            "producao ou de terceiros sem autorizacao explicita na instrucao. "
            "n8n: Especialista de Automacao - tem tool-calling real contra a API "
            "REST de uma instancia de n8n em producao: criar, editar, deletar, "
            "ativar/desativar e disparar execucao (via webhook) de workflows, "
            "alem de listar/consultar os que ja existem."
        )
    )
    instructions: str = Field(
        description=(
            "Instrucao especifica e autocontida para este especialista executar "
            "(nao apenas repetir a mensagem original do usuario sem contexto). "
            "Para o cybersec: se a acao for ativa (scan/teste/exploit), inclua "
            "explicitamente o alvo e a autorizacao do usuario para aquele alvo - "
            "sem isso o especialista vai recusar a acao ativa."
        )
    )
