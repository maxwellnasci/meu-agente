"""Autenticacao via token (ORCHESTRATOR_API_TOKEN) no Orquestrador.

Cobre a dependencia `verify_api_token` (main.py) aplicada a `/v1/turn`
e `/tasks/stream`, com `/health` publico:

- sem token com ORCHESTRATOR_API_TOKEN ativo -> 401
- token invalido -> 401
- token valido (Bearer ou X-Orchestrator-Token) -> processamento normal
- /health sem token -> 200
- api_token None e allow_insecure_dev_auth=False (default) -> FALHA FECHADO,
  401 em toda requisicao (nunca abre por omissao de configuracao)
- api_token None e allow_insecure_dev_auth=True (opt-in explicito) -> libera
"""

import pytest
from fastapi.testclient import TestClient

import orchestrator.main as main_module
from orchestrator.main import app

_TOKEN = "test-secret-token"

_TURN_BODY = {"session_key": "sess-1", "text": "oi", "from": "+5511999999999"}
_STREAM_BODY = {"thread_id": "thread-1", "message": "oi"}


class _FakeGraph:
    async def ainvoke(self, *args, **kwargs):
        return {"final_result": "ola"}

    async def astream_events(self, *args, **kwargs):
        return
        yield


@pytest.fixture
def client():
    client = TestClient(app, raise_server_exceptions=False)
    client.app.state.graph = _FakeGraph()
    yield client
    client.app.state.graph = None


def _set_token(monkeypatch, token: str | None) -> None:
    monkeypatch.setattr(main_module.settings, "api_token", token)


def _set_insecure_dev_auth(monkeypatch, allowed: bool) -> None:
    monkeypatch.setattr(main_module.settings, "allow_insecure_dev_auth", allowed)


def test_turn_sem_token_com_api_token_ativo_retorna_401(client, monkeypatch):
    _set_token(monkeypatch, _TOKEN)
    resp = client.post("/v1/turn", json=_TURN_BODY)
    assert resp.status_code == 401


def test_turn_com_token_invalido_retorna_401(client, monkeypatch):
    _set_token(monkeypatch, _TOKEN)
    resp = client.post(
        "/v1/turn",
        json=_TURN_BODY,
        headers={"Authorization": "Bearer token-errado"},
    )
    assert resp.status_code == 401


def test_stream_sem_token_com_api_token_ativo_retorna_401(client, monkeypatch):
    _set_token(monkeypatch, _TOKEN)
    resp = client.post("/tasks/stream", json=_STREAM_BODY)
    assert resp.status_code == 401


def test_stream_com_token_invalido_retorna_401(client, monkeypatch):
    _set_token(monkeypatch, _TOKEN)
    resp = client.post(
        "/tasks/stream",
        json=_STREAM_BODY,
        headers={"X-Orchestrator-Token": "token-errado"},
    )
    assert resp.status_code == 401


def test_turn_com_token_valido_bearer_processa_normalmente(client, monkeypatch):
    _set_token(monkeypatch, _TOKEN)
    resp = client.post(
        "/v1/turn",
        json=_TURN_BODY,
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"reply_text": "ola"}


def test_turn_com_token_valido_x_header_processa_normalmente(client, monkeypatch):
    _set_token(monkeypatch, _TOKEN)
    resp = client.post(
        "/v1/turn",
        json=_TURN_BODY,
        headers={"X-Orchestrator-Token": _TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json() == {"reply_text": "ola"}


def test_health_publico_sem_token(client, monkeypatch):
    _set_token(monkeypatch, _TOKEN)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_turn_falha_fechado_quando_api_token_nao_configurado(client, monkeypatch):
    """Default (allow_insecure_dev_auth=False): ausencia de token nunca vira
    acesso liberado - a app recusa com 401, nao processa a tarefa."""
    _set_token(monkeypatch, None)
    _set_insecure_dev_auth(monkeypatch, False)
    resp = client.post("/v1/turn", json=_TURN_BODY)
    assert resp.status_code == 401


def test_stream_falha_fechado_quando_api_token_nao_configurado(client, monkeypatch):
    _set_token(monkeypatch, None)
    _set_insecure_dev_auth(monkeypatch, False)
    resp = client.post("/tasks/stream", json=_STREAM_BODY)
    assert resp.status_code == 401


def test_turn_liberado_com_opt_in_explicito_de_modo_dev_inseguro(client, monkeypatch):
    """Unico jeito de rodar sem token: allow_insecure_dev_auth=True,
    explicito (ORCHESTRATOR_ALLOW_INSECURE_DEV_AUTH=true)."""
    _set_token(monkeypatch, None)
    _set_insecure_dev_auth(monkeypatch, True)
    resp = client.post("/v1/turn", json=_TURN_BODY)
    assert resp.status_code == 200
    assert resp.json() == {"reply_text": "ola"}


def test_health_publico_sem_token_mesmo_em_modo_fechado(client, monkeypatch):
    _set_token(monkeypatch, None)
    _set_insecure_dev_auth(monkeypatch, False)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
