from pydantic import BaseModel, Field

# Tools do Modo Atendente: resposta conversacional + transbordo humano.
#
# Contraparte das tools do Modo Executor (n8n_tools.py, com guardrails em
# graph/n8n_guard.py): aqui o efeito nao e sobre automacao, e pedir ajuda a
# um operador humano quando o atendente nao sabe ou nao pode resolver
# sozinho. A entrega real acontece no gateway via plugin ask-max
# (extensions/ask-max) - estas schemas sao o contrato de tool-calling
# (mesmo padrao de n8n_tools.py: 1 schema = 1 acao nomeada com args
# tipados) para o supervisor/roteador despachar o transbordo de forma
# estruturada em vez de texto livre.
#
# O destino (nome/numero/canal do operador) e 100% configuracao, nunca
# valor fixo no codigo - ver Settings.attendant_* em config.py e
# graph/human_escalation.py.


class AskHuman(BaseModel):
    """Pede ao operador humano uma informacao ou decisao pontual que so ele
    pode dar (ex.: politica interna, confirmacao de dado, autorizacao).
    Nao bloqueia: a resposta do operador volta num turno posterior."""

    question: str = Field(
        description="A duvida real e especifica para o operador - algo que nao ha como descobrir de outro jeito."
    )
    context: str | None = Field(
        default=None,
        description="Resumo curto de quem pergunta e por que, para o operador responder sem reler a conversa inteira.",
    )


class EscalateToHuman(BaseModel):
    """Transborda o atendimento inteiro para o operador humano (ex.: cliente
    irritado, caso fora do escopo, falha repetida). O atendente resume o caso
    e passa o turno."""

    reason: str = Field(description="Motivo do transbordo em uma frase (para registro e para o operador).")
    summary: str = Field(
        description="Resumo do caso ate aqui: quem e o cliente, o que pediu, o que ja foi tentado."
    )
    urgency: str = Field(
        default="normal",
        description="Urgencia do transbordo: 'baixa', 'normal' ou 'alta'.",
    )


# Registro canônico das tools do Modo Atendente (espelha _N8N_TOOLS em
# graph/nodes.py para o Modo Executor).
HUMAN_TOOLS = [AskHuman, EscalateToHuman]
