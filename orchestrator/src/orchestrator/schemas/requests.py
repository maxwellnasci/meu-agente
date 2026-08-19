from pydantic import BaseModel, ConfigDict, Field


class TaskRequest(BaseModel):
    """Contrato de entrada: uma nova tarefa (ou continuacao) enviada a API."""

    thread_id: str = Field(..., description="ID da conversa/tarefa, usado pelo checkpointer")
    message: str = Field(..., description="Instrucao do usuario em linguagem natural")


class TaskResponse(BaseModel):
    """Contrato de saida: resultado final de uma execucao do grafo (modo nao-streaming)."""

    thread_id: str
    result: str
    finished: bool = True


class TurnRequest(BaseModel):
    """Contrato de entrada do endpoint sincrono `/v1/turn`, consumido pela
    porta de entrada Node.js (Meta/WhatsApp Cloud).

    Nomes de campo espelham o vocabulario dessa integracao (sessao,
    remetente, texto) em vez do contrato interno thread_id/message usado por
    `/tasks/stream` - sao fronteiras de API distintas (Node->Python aqui,
    UI/portfolio la), mesmo alimentando o mesmo grafo por baixo.
    """

    model_config = ConfigDict(populate_by_name=True)

    session_key: str = Field(..., description="Chave da sessao/conversa, usada como thread_id do checkpointer")
    text: str = Field(..., description="Texto da mensagem recebida do usuario")
    from_: str = Field(..., alias="from", description="Identificador do remetente (ex.: numero de telefone)")


class TurnResponse(BaseModel):
    """Contrato de saida do endpoint sincrono `/v1/turn`: resposta final ja
    pronta para o Node.js repassar ao usuario, sem streaming."""

    reply_text: str


class SpecialistCallRequest(BaseModel):
    """Contrato enviado ao Especialista (OpenClaw) a partir de um no do grafo."""

    task_description: str
    workdir: str | None = None


class SpecialistCallResult(BaseModel):
    """Contrato de resposta do Especialista (OpenClaw), validado antes de voltar ao grafo."""

    success: bool
    output: str
    error: str | None = None
