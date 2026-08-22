"""Teste local do especialista de ciberseguranca: gate de autorizacao e
fluxo do node (sem depender do gateway OpenClaw real - o client HTTP e
mockado para isolar a logica do node)."""

from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.graph.cybersec_guard import check_production_infra_block
from orchestrator.graph.nodes import specialist_cybersec_node
from orchestrator.schemas.requests import SpecialistCallResult


def test_guard_blocks_known_production_infra():
    assert check_production_infra_block("escaneia o servidor Contabo de producao") is not None
    assert check_production_infra_block("roda um pentest no Amigao") is not None
    assert check_production_infra_block("testa a evolution-api em producao") is not None


def test_guard_allows_user_owned_target():
    assert check_production_infra_block("escaneia meu-dominio-de-teste.com, e meu e autorizo") is None
    assert check_production_infra_block("roda o 02-vulnerability-scanner no projeto local orchestrator/") is None


def test_guard_allows_supervisor_echoed_caution_about_production_infra():
    """Regressao do bug de loop: o supervisor as vezes ecoa, na propria
    instrucao que gera para o especialista, a advertencia do seu system
    prompt ("nunca teste Contabo/Amigao/n8n/..."). Isso NAO e um pedido de
    acao contra a producao - e o supervisor proibindo o alvo -, entao o
    guard nao deve bloquear (bloquear aqui derrubava a instrucao real
    tambem, fazendo o supervisor tentar de novo e entrar em loop ate o
    limite de iteracoes)."""
    caution_instruction = (
        "Realize um pentest completo no dominio exemplo.com, que o usuario "
        "controla e autorizou explicitamente. Nunca inclua nessa analise "
        "infraestrutura de producao propria como Contabo, Amigao, n8n, "
        "chatwoot ou evolution-api."
    )
    assert check_production_infra_block(caution_instruction) is None


def test_guard_still_blocks_real_request_mixed_with_caution_language():
    """Contraste com o teste acima: se OUTRA sentenca da mesma instrucao
    pede a acao de verdade contra o alvo de producao (sem negacao naquela
    sentenca especifica), o guard ainda bloqueia - a checagem por sentenca
    nao abre uma brecha geral, so ignora a sentenca que e proibicao."""
    mixed_instruction = (
        "Nunca teste infraestrutura de terceiros sem autorizacao. "
        "Escaneia o servidor Contabo em busca de vulnerabilidades."
    )
    assert check_production_infra_block(mixed_instruction) is not None


@pytest.mark.asyncio
async def test_node_refuses_without_calling_client_for_production_target():
    from langchain_core.messages import HumanMessage
    state = {
        "messages": [HumanMessage(content="escaneia a infra Contabo (Amigao/n8n)")],
        "pending_specialists": [{"specialist": "cybersec", "instructions": "escaneia a infra Contabo (Amigao/n8n)"}],
        "internal_scratchpad": [],
    }
    with patch("orchestrator.graph.nodes.OpenClawClient") as mock_client_cls:
        result = await specialist_cybersec_node(state)

    mock_client_cls.assert_not_called()
    assert result["pending_specialists"] == []
    assert "RECUSADO" in result["internal_scratchpad"][0]


@pytest.mark.asyncio
async def test_node_calls_client_for_authorized_local_target():
    from langchain_core.messages import HumanMessage
    state = {
        "messages": [HumanMessage(content="Roda a skill 02-vulnerability-scanner contra o projeto local orchestrator/ (eu controlo e autorizo este alvo).")],
        "pending_specialists": [
            {
                "specialist": "cybersec",
                "instructions": (
                    "Roda a skill 02-vulnerability-scanner contra o projeto local "
                    "orchestrator/ (eu controlo e autorizo este alvo)."
                ),
            }
        ],
        "internal_scratchpad": [],
    }
    fake_result = SpecialistCallResult(success=True, output="achados: nenhuma CVE critica")
    with patch("orchestrator.graph.nodes.OpenClawClient") as mock_client_cls:
        mock_client_cls.return_value.call = AsyncMock(return_value=fake_result)
        result = await specialist_cybersec_node(state)

    mock_client_cls.return_value.call.assert_awaited_once()
    sent_request = mock_client_cls.return_value.call.await_args.args[0]
    assert "orchestrator/" in sent_request.task_description
    assert "REGRA DE AUTORIZACAO" in sent_request.task_description
    assert result["internal_scratchpad"] == ["[cybersec] achados: nenhuma CVE critica"]
    assert result["pending_specialists"] == []
