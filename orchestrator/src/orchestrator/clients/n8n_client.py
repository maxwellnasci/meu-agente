import re

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from orchestrator.config import settings

# So reexecuta se a conexao nunca foi estabelecida - o n8n com certeza nao
# recebeu o request, entao repetir e seguro mesmo para os metodos que
# criam/editam/deletam (nao-idempotentes). Deliberadamente NAO inclui
# timeout de leitura: se o request ja chegou no n8n e so a resposta
# demorou, reexecutar um create/delete/trigger_webhook arrisca duplicar o
# efeito colateral - vira erro direto, sem retry (mesmo raciocinio do
# OpenClawClient, ver openclaw_client.py).
_CONNECT_FAILURE_EXCEPTIONS = (httpx.ConnectError, httpx.ConnectTimeout)

# Referencia: /usr/local/lib/node_modules/n8n/dist/public-api/v1/openapi.yml
# dentro do container n8n em producao (Contabo). Confirmado lendo o spec real
# - nao existe endpoint de "executar workflow por id" na API publica (so
# list/get/create/update/delete/activate/deactivate/transfer/tags). Disparo
# de execucao so e possivel via URL de webhook de um node Webhook do proprio
# workflow, por isso o metodo trigger_webhook chama /webhook(-test)/<path>
# em vez de /api/v1/...
_API_PREFIX = "/api/v1"


class InvalidN8nInput(ValueError):
    """Entrada vinda do LLM (workflow_id, path de webhook, metodo) recusada
    ANTES de qualquer requisicao. Ver `validate_*` abaixo."""


# Allowlist (nao blocklist de ".."): o httpx normaliza segmentos "." e ".."
# e preserva o header X-N8N-API-KEY, entao um workflow_id como
# "../executions/1" redirecionava a chave de API para qualquer endpoint da
# API publica (execucoes, credenciais...). Ids do n8n sao alfanumericos
# (nanoid) ou numericos; so isso passa.
_WORKFLOW_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
# Segmento de path de webhook: nao pode comecar com "." (barra "." / ".." /
# dotfiles) e nao admite "%", "?", "#", "\\" ou espaco (sem encoding tricks).
_WEBHOOK_SEGMENT_RE = re.compile(r"[A-Za-z0-9_~-][A-Za-z0-9_.~-]{0,99}")
_WEBHOOK_MAX_SEGMENTS = 8
_ALLOWED_WEBHOOK_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})


def validate_workflow_id(workflow_id: object) -> str:
    """Devolve o id como str ou levanta InvalidN8nInput."""
    if isinstance(workflow_id, bool) or not isinstance(workflow_id, (str, int)):
        raise InvalidN8nInput("workflow_id deve ser texto ou numero")
    value = str(workflow_id)
    if not _WORKFLOW_ID_RE.fullmatch(value):
        raise InvalidN8nInput("workflow_id invalido: so letras, numeros, '_' e '-' (ate 64 caracteres)")
    return value


def validate_webhook_request(path: object, method: object = "POST") -> tuple[str, str]:
    """Devolve (path_normalizado_sem_barra_inicial, METODO) ou levanta InvalidN8nInput."""
    if not isinstance(path, str) or not isinstance(method, str):
        raise InvalidN8nInput("path e method do webhook devem ser texto")
    relative = path[1:] if path.startswith("/") else path
    segments = relative.split("/")
    if len(segments) > _WEBHOOK_MAX_SEGMENTS or not all(_WEBHOOK_SEGMENT_RE.fullmatch(seg) for seg in segments):
        raise InvalidN8nInput("path de webhook invalido: segmentos de letras, numeros, '_', '-', '.', '~' (sem '..')")
    verb = method.upper()
    if verb not in _ALLOWED_WEBHOOK_METHODS:
        raise InvalidN8nInput(f"metodo HTTP de webhook fora da allowlist: {sorted(_ALLOWED_WEBHOOK_METHODS)}")
    return "/".join(segments), verb


class N8nClient:
    """Client HTTP para a API REST publica de uma instancia de n8n externa
    (Especialista de Automacao). A instancia roda em producao na Contabo -
    este client so fala HTTPS + API key, nao sabe (nem precisa saber) como
    ela roda por tras.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self._base_url = (base_url if base_url is not None else settings.n8n_url) or ""
        self._base_url = self._base_url.rstrip("/")
        self._api_key = api_key or settings.n8n_api_key
        self._timeout = settings.n8n_request_timeout_sec

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["X-N8N-API-KEY"] = self._api_key
        return headers

    @retry(
        retry=retry_if_exception_type(_CONNECT_FAILURE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def _request(self, method: str, path: str, json: dict | None = None, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.request(method, path, json=json, params=params, headers=self._headers())
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()

    async def list_workflows(self, active: bool | None = None, name: str | None = None, limit: int = 50) -> dict:
        params: dict = {"limit": limit}
        if active is not None:
            params["active"] = str(active).lower()
        if name:
            params["name"] = name
        return await self._request("GET", f"{_API_PREFIX}/workflows", params=params)

    async def get_workflow(self, workflow_id: str) -> dict:
        workflow_id = validate_workflow_id(workflow_id)
        return await self._request("GET", f"{_API_PREFIX}/workflows/{workflow_id}")

    async def create_workflow(self, name: str, nodes: list, connections: dict, workflow_settings: dict | None = None) -> dict:
        body = {"name": name, "nodes": nodes, "connections": connections, "settings": workflow_settings or {}}
        return await self._request("POST", f"{_API_PREFIX}/workflows", json=body)

    async def update_workflow(
        self, workflow_id: str, name: str, nodes: list, connections: dict, workflow_settings: dict | None = None
    ) -> dict:
        workflow_id = validate_workflow_id(workflow_id)
        body = {"name": name, "nodes": nodes, "connections": connections, "settings": workflow_settings or {}}
        return await self._request("PUT", f"{_API_PREFIX}/workflows/{workflow_id}", json=body)

    async def delete_workflow(self, workflow_id: str) -> dict:
        workflow_id = validate_workflow_id(workflow_id)
        return await self._request("DELETE", f"{_API_PREFIX}/workflows/{workflow_id}")

    async def activate_workflow(self, workflow_id: str) -> dict:
        workflow_id = validate_workflow_id(workflow_id)
        return await self._request("POST", f"{_API_PREFIX}/workflows/{workflow_id}/activate")

    async def deactivate_workflow(self, workflow_id: str) -> dict:
        workflow_id = validate_workflow_id(workflow_id)
        return await self._request("POST", f"{_API_PREFIX}/workflows/{workflow_id}/deactivate")

    async def trigger_webhook(self, path: str, method: str = "POST", body: dict | None = None, test: bool = False) -> dict:
        """Dispara uma execucao chamando a URL de webhook de um node Webhook
        do proprio workflow (nao existe endpoint generico de "executar
        workflow X" na API publica do n8n - ver comentario no topo do
        arquivo). `test` usa /webhook-test (execucao unica, exige o editor
        de workflow "escutando", modo usado durante desenvolvimento) em vez
        de /webhook (producao, workflow precisa estar ativo)."""
        safe_path, verb = validate_webhook_request(path, method)
        prefix = "/webhook-test" if test else "/webhook"
        full_path = f"{prefix}/{safe_path}"
        response = await self._request_webhook(verb, full_path, body)
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    @retry(
        retry=retry_if_exception_type(_CONNECT_FAILURE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def _request_webhook(self, method: str, path: str, body: dict | None) -> httpx.Response:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.request(method, path, json=body)
            response.raise_for_status()
            return response
