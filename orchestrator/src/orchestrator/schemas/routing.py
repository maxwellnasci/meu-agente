from enum import Enum

from pydantic import BaseModel, Field


class RouteDestination(str, Enum):
    """Os destinos possiveis apos o roteador (no `reason`) classificar a
    tarefa - usado tanto na saida estruturada do LLM quanto nas chaves do
    `add_conditional_edges` em graph/builder.py, entao os dois lados do
    grafo ficam amarrados a este unico Enum."""

    SPECIALIST = "specialist"
    GENERAL = "general"


class RouteDecision(BaseModel):
    """Saida estruturada do LLM roteador (bind via `with_structured_output`)."""

    destination: RouteDestination = Field(
        description=(
            "specialist: a tarefa exige o Especialista em Programacao (OpenClaw) - "
            "escrever/editar codigo, executar comandos, mexer em arquivos de um "
            "projeto, debugar, rodar testes. "
            "general: pode ser respondida diretamente, sem executar nada - duvida "
            "conceitual, conversa, explicacao geral."
        )
    )
    reasoning: str = Field(description="Justificativa curta (uma frase) da escolha.")
