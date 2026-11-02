"""Unidade do gate de confirmacao de acoes n8n (graph/n8n_confirmation.py)."""

import time

import pytest

from orchestrator.graph.n8n_confirmation import (
    build_pending_confirmation,
    classify_confirmation_reply,
    describe_action,
    get_valid_pending_confirmation,
    is_write_action,
)


@pytest.mark.parametrize(
    "tool,expected",
    [
        ("N8nCreateWorkflow", True),
        ("N8nActivateWorkflow", True),
        ("N8nDeactivateWorkflow", True),
        ("N8nDeleteWorkflow", True),
        ("N8nListWorkflows", False),
        ("N8nGetWorkflow", False),
        ("N8nTriggerWebhook", False),
    ],
)
def test_is_write_action(tool, expected):
    assert is_write_action(tool) is expected


def test_build_pending_confirmation_binds_action_and_workflow():
    rec = build_pending_confirmation("N8nDeleteWorkflow", {"workflow_id": "wf9"}, ttl_sec=900)
    assert rec["action"] == "delete"
    assert rec["tool_name"] == "N8nDeleteWorkflow"
    assert rec["workflow_id"] == "wf9"
    assert rec["args"] == {"workflow_id": "wf9"}
    assert rec["token"] and isinstance(rec["token"], str)
    assert rec["expires_at"] > rec["created_at"]
    assert "EXCLUIR" in rec["summary"]


def test_build_pending_confirmation_tokens_are_unique():
    a = build_pending_confirmation("N8nCreateWorkflow", {"name": "x"}, 900)
    b = build_pending_confirmation("N8nCreateWorkflow", {"name": "x"}, 900)
    assert a["token"] != b["token"]


def test_get_valid_pending_confirmation_accepts_fresh_record():
    rec = build_pending_confirmation("N8nActivateWorkflow", {"workflow_id": "a"}, 900)
    assert get_valid_pending_confirmation(rec) is rec


def test_get_valid_pending_confirmation_rejects_expired():
    rec = build_pending_confirmation("N8nActivateWorkflow", {"workflow_id": "a"}, 900)
    assert get_valid_pending_confirmation(rec, now=time.time() + 10_000) is None


@pytest.mark.parametrize("bad", [None, "clear", {}, {"token": "x"}, {"tool_name": "y"}, 42, []])
def test_get_valid_pending_confirmation_rejects_malformed(bad):
    assert get_valid_pending_confirmation(bad) is None


@pytest.mark.parametrize(
    "text",
    ["sim", "Sim!", "  SIM  ", "pode", "pode sim", "confirmo", "isso mesmo", "ok", "beleza", "pode fazer", "sim por favor"],
)
def test_classify_affirmative(text):
    assert classify_confirmation_reply(text) == "affirm"


@pytest.mark.parametrize("text", ["nao", "Não", "cancela", "melhor nao", "nao pode", "esquece", "nao faz isso"])
def test_classify_negative(text):
    assert classify_confirmation_reply(text) == "deny"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "sim, mas muda o nome do workflow",
        "pode apagar o outro fluxo tambem",
        "o que esse fluxo faz?",
        "cria mais um workflow parecido",
        "talvez",
        "como assim",
    ],
)
def test_classify_unclear(text):
    assert classify_confirmation_reply(text) == "unclear"


@pytest.mark.parametrize(
    "text",
    [
        # achado da auditoria 2026-11-02: UM token afirmativo + qualquer
        # outra coisa liberava uma acao em producao
        "ok mas espera",
        "talvez ok",
        "ok mas muda o nome",
        "pode apagar outro",
        "sim depois",
        "vai la mas antes confirma",
        "ok nao sei",  # contem negacao -> deny (ver abaixo), nunca affirm
    ],
)
def test_classify_never_affirms_when_extra_content_present(text):
    assert classify_confirmation_reply(text) != "affirm"


@pytest.mark.parametrize("text", ["ok nao sei", "sim mas nao", "pode nao", "ok para"])
def test_classify_negation_token_wins_over_affirmation(text):
    assert classify_confirmation_reply(text) == "deny"


@pytest.mark.parametrize("text", ["sim obrigado", "pode sim por favor", "ok valeu", "isso mesmo", "com certeza", "manda ver"])
def test_classify_polite_affirmations_still_work(text):
    assert classify_confirmation_reply(text) == "affirm"


@pytest.mark.parametrize(
    "action, text",
    [
        ("activate", "pode ativar sim"),
        ("activate", "sim ativa"),
        ("create", "pode criar"),
        ("delete", "pode apagar"),
        ("delete", "sim pode excluir"),
        ("deactivate", "ok pode pausar"),
    ],
)
def test_classify_action_verb_confirms_only_the_pending_action(action, text):
    assert classify_confirmation_reply(text, action=action) == "affirm"


@pytest.mark.parametrize(
    "action, text",
    [
        ("create", "pode apagar"),  # verbo de OUTRA acao nao confirma
        ("activate", "pode apagar"),
        ("delete", "pode ativar"),
        ("activate", "pode ativar sim e apaga"),
        ("delete", "pode apagar outro"),
        ("activate", "ativa"),  # so o verbo, sem afirmacao real
        ("create", "cria"),
    ],
)
def test_classify_action_verb_of_another_action_or_alone_is_not_affirm(action, text):
    assert classify_confirmation_reply(text, action=action) != "affirm"


def test_describe_action_create_mentions_inactive():
    txt = describe_action("create", None, "meu-fluxo")
    assert "INATIVO" in txt and "meu-fluxo" in txt
