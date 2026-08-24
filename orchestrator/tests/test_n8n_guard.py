from orchestrator.graph.n8n_guard import check_destructive_n8n_action


def test_non_destructive_tools_are_never_blocked():
    for tool in ("N8nListWorkflows", "N8nGetWorkflow", "N8nCreateWorkflow", "N8nUpdateWorkflow", "N8nActivateWorkflow"):
        assert check_destructive_n8n_action(tool, "") is None


def test_delete_blocked_without_authorization_verb():
    refusal = check_destructive_n8n_action("N8nDeleteWorkflow", "organiza os workflows de marketing")
    assert refusal is not None
    assert "RECUSADO" in refusal


def test_delete_allowed_with_explicit_verb():
    assert check_destructive_n8n_action("N8nDeleteWorkflow", "deleta o workflow teste-antigo") is None


def test_deactivate_blocked_without_authorization_verb():
    refusal = check_destructive_n8n_action("N8nDeactivateWorkflow", "lista todos os workflows ativos")
    assert refusal is not None
    assert "RECUSADO" in refusal


def test_deactivate_allowed_with_explicit_verb():
    assert check_destructive_n8n_action("N8nDeactivateWorkflow", "por favor desative o workflow x") is None


def test_check_is_case_insensitive():
    assert check_destructive_n8n_action("N8nDeleteWorkflow", "DELETE o workflow x") is None
