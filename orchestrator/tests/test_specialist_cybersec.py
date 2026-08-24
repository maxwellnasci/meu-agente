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


@pytest.mark.asyncio
async def test_node_refuses_when_production_keyword_in_job_instructions_only():
    """Regressao multi-turn: o guard deve bloquear mesmo quando a keyword de
    infra de producao esta apenas nas instrucoes do supervisor (`job.instructions`)
    e NAO na mensagem original do usuario. Antes do fix, apenas `task_description`
    era checado - um payload malicioso ou echo no `instructions` do supervisor
    criava uma janela de bypass que deixava a instrucao chegar ao especialista."""
    from langchain_core.messages import HumanMessage

    # Mensagem do usuario e inocente (sem keyword de producao)
    # mas o supervisor (injetado/corrompido) passa Contabo em instructions.
    state = {
        "messages": [HumanMessage(content="analisa a seguranca do meu dominio teste.com")],
        "pending_specialists": [
            {
                "specialist": "cybersec",
                "instructions": "Escaneia o servidor Contabo em busca de portas abertas.",
            }
        ],
        "internal_scratchpad": [],
    }
    with patch("orchestrator.graph.nodes.OpenClawClient") as mock_client_cls:
        result = await specialist_cybersec_node(state)

    # O client nao deve ser chamado - o guard deve ter bloqueado via instructions
    mock_client_cls.assert_not_called()
    assert result["pending_specialists"] == []
    assert "RECUSADO" in result["internal_scratchpad"][0]


@pytest.mark.asyncio
async def test_last_error_cleared_on_subsequent_specialist_success():
    """Regressao: `last_error` setado por uma falha anterior nao deve poluir
    a resposta final quando uma rodada subsequente conclui com sucesso. O
    `supervisor_node` agora reseta `last_error=None` ao despachar novos
    especialistas, e os nodes de especialista nao escrevem `last_error` em
    atualizacoes de sucesso - testamos o node de cybersec como representativo."""
    from langchain_core.messages import HumanMessage

    state = {
        "messages": [HumanMessage(content="analisa o projeto local orchestrator/")],
        "pending_specialists": [
            {
                "specialist": "cybersec",
                "instructions": "Roda 02-vulnerability-scanner no projeto local orchestrator/ (autorizado).",
            }
        ],
        "internal_scratchpad": [],
        # Simula erro residual de uma rodada anterior
        "last_error": "falha de rede na rodada anterior",
    }
    fake_result = SpecialistCallResult(success=True, output="sem CVEs criticas")
    with patch("orchestrator.graph.nodes.OpenClawClient") as mock_client_cls:
        mock_client_cls.return_value.call = AsyncMock(return_value=fake_result)
        result = await specialist_cybersec_node(state)

    # Em caso de sucesso, o node nao deve (re)escrever last_error
    assert "last_error" not in result, (
        "specialist_cybersec_node nao deve emitir last_error em caso de sucesso "
        "(supervisor_node ja reseta ao despachar; o node de especialista so escreve em falha)"
    )
    assert result["internal_scratchpad"] == ["[cybersec] sem CVEs criticas"]
