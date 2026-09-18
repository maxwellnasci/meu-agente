"""Modo Atendente: tools de transbordo humano + configuracao do operador.

Cobre schemas/human_tools.py (contrato de tool-calling), config.py (novos
campos attendant_*) e graph/human_escalation.py (helpers puros, sem I/O).
"""

import pytest
from pydantic import ValidationError

from orchestrator.config import settings
from orchestrator.graph.human_escalation import (
    build_escalation_text,
    build_handoff_summary,
    resolve_operator_target,
)
from orchestrator.schemas.human_tools import (
    HUMAN_TOOLS,
    AskHuman,
    EscalateToHuman,
)


def test_human_tools_registry_has_both_modes():
    names = {tool.__name__ for tool in HUMAN_TOOLS}
    assert names == {"AskHuman", "EscalateToHuman"}


def test_ask_human_requires_question():
    tool = AskHuman(question="Pode confirmar o horario?", context="paciente X")
    assert tool.question.startswith("Pode confirmar")
    assert tool.context == "paciente X"
    with pytest.raises(ValidationError):
        AskHuman()


def test_escalate_to_human_defaults_urgency_normal():
    tool = EscalateToHuman(reason="fora do escopo", summary="cliente pediu Y, tentei Z")
    assert tool.urgency == "normal"
    custom = EscalateToHuman(reason="r", summary="s", urgency="alta")
    assert custom.urgency == "alta"


def test_attendant_config_defaults():
    assert settings.attendant_mode == "atendente"
    assert settings.attendant_channel == "whatsapp-cloud"
    assert settings.attendant_operator_name == "Max"


def test_resolve_operator_target_none_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "attendant_operator_to", None)
    assert resolve_operator_target() is None
    monkeypatch.setattr(settings, "attendant_operator_to", "   ")
    assert resolve_operator_target() is None


def test_resolve_operator_target_from_config(monkeypatch):
    monkeypatch.setattr(settings, "attendant_operator_to", "5541999999999")
    monkeypatch.setattr(settings, "attendant_operator_name", "Dra. Ana")
    monkeypatch.setattr(settings, "attendant_channel", "whatsapp-cloud")
    target = resolve_operator_target()
    assert target is not None
    assert target.to == "5541999999999"
    assert target.name == "Dra. Ana"
    assert target.channel == "whatsapp-cloud"


def test_build_escalation_text_names_operator():
    text = build_escalation_text("Pode confirmar?", "paciente X", operator_name="Max")
    assert "Max" in text
    assert "Pode confirmar?" in text
    assert "paciente X" in text


def test_build_handoff_summary_carries_urgency():
    text = build_handoff_summary("fora do escopo", "resumo do caso", urgency="alta")
    assert "alta" in text
    assert "resumo do caso" in text
