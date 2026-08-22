import httpx

from orchestrator.config import settings

# Referencia: /usr/local/lib/node_modules/n8n/dist/public-api/v1/openapi.yml
# dentro do container n8n em producao (Contabo). Confirmado lendo o spec real
# - nao existe endpoint de "executar workflow por id" na API publica (so
# list/get/create/update/delete/activate/deactivate/transfer/tags). Disparo
# de execucao so e possivel via URL de webhook de um node Webhook do proprio
# workflow, por isso o metodo trigger_webhook chama /webhook(-test)/<path>
# em vez de /api/v1/...
_API_PREFIX = "/api/v1"


class N8nClient:
    """Client HTTP para a API REST publica de uma instancia de n8n externa
    (Especialista de Automacao). A instancia roda em producao na Contabo -
    este client so fala HTTPS + API key, nao sabe (nem precisa saber) como
    ela roda por tras.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self._base_url = (base_url or settings.n8n_url or "").rstrip("/")
        self._api_key = api_key or settings.n8n_api_key
        self._timeout = settings.n8n_request_timeout_sec

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["X-N8N-API-KEY"] = self._api_key
        return headers

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
        return await self._request("GET", f"{_API_PREFIX}/workflows/{workflow_id}")

    async def create_workflow(self, name: str, nodes: list, connections: dict, workflow_settings: dict | None = None) -> dict:
        body = {"name": name, "nodes": nodes, "connections": connections, "settings": workflow_settings or {}}
        return await self._request("POST", f"{_API_PREFIX}/workflows", json=body)

    async def update_workflow(
        self, workflow_id: str, name: str, nodes: list, connections: dict, workflow_settings: dict | None = None
    ) -> dict:
        body = {"name": name, "nodes": nodes, "connections": connections, "settings": workflow_settings or {}}
        return await self._request("PUT", f"{_API_PREFIX}/workflows/{workflow_id}", json=body)

    async def delete_workflow(self, workflow_id: str) -> dict:
        return await self._request("DELETE", f"{_API_PREFIX}/workflows/{workflow_id}")

    async def activate_workflow(self, workflow_id: str) -> dict:
        return await self._request("POST", f"{_API_PREFIX}/workflows/{workflow_id}/activate")

    async def deactivate_workflow(self, workflow_id: str) -> dict:
        return await self._request("POST", f"{_API_PREFIX}/workflows/{workflow_id}/deactivate")

    async def trigger_webhook(self, path: str, method: str = "POST", body: dict | None = None, test: bool = False) -> dict:
        """Dispara uma execucao chamando a URL de webhook de um node Webhook
        do proprio workflow (nao existe endpoint generico de "executar
        workflow X" na API publica do n8n - ver comentario no topo do
        arquivo). `test` usa /webhook-test (execucao unica, exige o editor
        de workflow "escutando", modo usado durante desenvolvimento) em vez
        de /webhook (producao, workflow precisa estar ativo)."""
        prefix = "/webhook-test" if test else "/webhook"
        full_path = f"{prefix}/{path.lstrip('/')}"
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.request(method.upper(), full_path, json=body)
            response.raise_for_status()
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError:
                return {"raw": response.text}
