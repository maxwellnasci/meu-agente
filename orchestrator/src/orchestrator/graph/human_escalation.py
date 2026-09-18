"""Transbordo humano do Modo Atendente (puro, sem I/O).

Monta o destino e o texto de escalonamento a partir de configuracao
(Settings.attendant_*, ou o plugin ask-max no gateway) - nunca de valores
fixos no codigo. Usado pelo supervisor/roteador para despachar as tools
AskHuman/EscalateToHuman (schemas/human_tools.py) de forma estruturada.
"""

from dataclasses import dataclass

from orchestrator.config import settings


@dataclass(frozen=True)
class OperatorTarget:
    """Destino do transbordo: quem e o operador e por onde alcança-lo."""

    name: str
    to: str
    channel: str
    account_id: str | None = None


def resolve_operator_target() -> OperatorTarget | None:
    """Resolve o operador humano a partir da configuracao.

    Retorna None quando o destino nao esta configurado (sem `to`): o
    chamador deve entao avisar que o transbordo esta indisponivel em vez
    de fingir que escalonou - mesmo contrato do ask-max no gateway
    ("ask_max is not configured yet").
    """
    to = (settings.attendant_operator_to or "").strip()
    if not to:
        return None
    return OperatorTarget(
        name=settings.attendant_operator_name.strip() or "operador",
        to=to,
        channel=settings.attendant_channel.strip() or "whatsapp-cloud",
        account_id=settings.attendant_account_id,
    )


def build_escalation_text(question: str, context: str | None = None, *, operator_name: str) -> str:
    """Monta o texto de escalonamento dirigido ao operador."""
    lines = [f"{operator_name}, o atendente precisa de ajuda:", "", question]
    if context:
        lines.append("")
        lines.append(f"Contexto: {context}")
    lines.append("")
    lines.append("Responde aqui - tua proxima mensagem volta para o atendimento como resposta.")
    return "\n".join(lines)


def build_handoff_summary(reason: str, summary: str, urgency: str = "normal") -> str:
    """Monta o resumo de transbordo total (EscalateToHuman) para o operador."""
    return f"[transbordo - urgencia {urgency}] {reason}\n\nResumo do caso:\n{summary}"
