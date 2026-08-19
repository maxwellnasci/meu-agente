from typing import Literal

from pydantic import BaseModel


class NodeStartedEvent(BaseModel):
    type: Literal["node_started"] = "node_started"
    node_name: str


class SpecialistCalledEvent(BaseModel):
    type: Literal["specialist_called"] = "specialist_called"
    task_description: str


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    content: str


class TaskCompletedEvent(BaseModel):
    type: Literal["task_completed"] = "task_completed"
    result: str


class ErrorEvent(BaseModel):
    """Erro pontual durante o stream (ex.: falha ao mapear um evento) - a
    conexao SSE pode continuar depois disso."""

    type: Literal["error"] = "error"
    message: str


class TaskFailedEvent(BaseModel):
    """A execucao do grafo falhou de forma irrecuperavel - ultimo evento do
    stream antes da conexao SSE ser encerrada."""

    type: Literal["task_failed"] = "task_failed"
    node_name: str | None = None
    error: str


StreamEvent = (
    NodeStartedEvent
    | SpecialistCalledEvent
    | TokenEvent
    | TaskCompletedEvent
    | ErrorEvent
    | TaskFailedEvent
)
