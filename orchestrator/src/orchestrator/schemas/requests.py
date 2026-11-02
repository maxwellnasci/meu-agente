from pydantic import BaseModel, ConfigDict, Field

# Limites de entrada (OWASP LLM10 - consumo ilimitado). Generosos de
# proposito: o WhatsApp limita texto a 4096 caracteres, entao 8000 nunca corta
# uma mensagem legitima, mas impede mandar megabytes ao LLM pago.
MAX_TEXT_CHARS = 8000
MAX_ID_CHARS = 256


class TaskRequest(BaseModel):
    """Contrato de entrada: uma nova tarefa (ou continuacao) enviada a API."""

    thread_id: str = Field(..., min_length=1, max_length=MAX_ID_CHARS, description="ID da conversa/tarefa, usado pelo checkpointer")
    message: str = Field(..., max_length=MAX_TEXT_CHARS, description="Instrucao do usuario em linguagem natural")


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

    session_key: str = Field(
        ..., min_length=1, max_length=MAX_ID_CHARS, description="Chave da sessao/conversa, usada como thread_id do checkpointer"
    )
    text: str = Field(..., max_length=MAX_TEXT_CHARS, description="Texto da mensagem recebida do usuario")
    from_: str = Field(..., alias="from", max_length=64, description="Identificador do remetente (ex.: numero de telefone)")


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
