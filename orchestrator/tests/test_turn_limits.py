"""Limites de entrada e nao-vazamento de detalhes internos (auditoria 2026-11-02).

- OWASP LLM10 (consumo ilimitado): `text`/`message` sem limite de tamanho
  deixavam um portador do token (ou um bug a montante) mandar prompts de
  megabytes ao LLM pago. Agora recusa com 422 antes de tocar no grafo.
- Vazamento de informacao: `/tasks/stream` devolvia `str(exc)` ao cliente no
  evento `task_failed`. Excecoes de grafo/DB/HTTP podem conter caminhos,
  trechos de resposta de upstream e URLs internas.
"""

import pytest
from fastapi.testclient import TestClient

import orchestrator.main as main_module
from orchestrator.main import app

_TOKEN = "test-secret-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_SECRET_IN_EXC = "postgres://svc:hunter2@10.0.0.7/internal /srv/orchestrator/data/checkpoints.sqlite"


class _BoomGraph:
    async def ainvoke(self, *args, **kwargs):
        raise RuntimeError(_SECRET_IN_EXC)

    async def astream_events(self, *args, **kwargs):
        raise RuntimeError(_SECRET_IN_EXC)
        yield  # pragma: no cover


class _OkGraph:
    async def ainvoke(self, *args, **kwargs):
        return {"final_result": "ola"}

    async def astream_events(self, *args, **kwargs):
        return
        yield  # pragma: no cover


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main_module.settings, "api_token", _TOKEN)
    c = TestClient(app, raise_server_exceptions=False)
    c.app.state.graph = _OkGraph()
    yield c
    c.app.state.graph = None


def _turn(**over):
    body = {"session_key": "sess-1", "text": "oi", "from": "+5511999999999"}
    body.update(over)
    return body


def test_turn_normal_continua_200(client):
    assert client.post("/v1/turn", json=_turn(), headers=_AUTH).status_code == 200


def test_turn_texto_no_limite_ainda_passa(client):
    assert client.post("/v1/turn", json=_turn(text="a" * 32000), headers=_AUTH).status_code == 200


@pytest.mark.parametrize(
    "over",
    [
        {"text": "a" * 32001},
        {"text": "a" * 2_000_000},
        {"session_key": "s" * 257},
        {"session_key": ""},
        {"from": "5" * 65},
    ],
)
def test_turn_acima_do_limite_retorna_422_sem_tocar_no_grafo(client, over):
    client.app.state.graph = _BoomGraph()  # se chegasse no grafo, o fallback viria com 200
    assert client.post("/v1/turn", json=_turn(**over), headers=_AUTH).status_code == 422


@pytest.mark.parametrize("body", [{"thread_id": "t", "message": "a" * 32001}, {"thread_id": "t" * 257, "message": "oi"}])
def test_stream_acima_do_limite_retorna_422(client, body):
    assert client.post("/tasks/stream", json=body, headers=_AUTH).status_code == 422


def test_stream_nao_vaza_detalhe_da_excecao(client):
    client.app.state.graph = _BoomGraph()
    resp = client.post("/tasks/stream", json={"thread_id": "t", "message": "oi"}, headers=_AUTH)
    assert resp.status_code == 200
    assert "task_failed" in resp.text
    assert "hunter2" not in resp.text
    assert "/srv/orchestrator" not in resp.text
    assert "RuntimeError" not in resp.text


def test_turn_fallback_nao_vaza_detalhe_da_excecao(client):
    client.app.state.graph = _BoomGraph()
    resp = client.post("/v1/turn", json=_turn(), headers=_AUTH)
    assert resp.status_code == 200
    assert "hunter2" not in resp.text
