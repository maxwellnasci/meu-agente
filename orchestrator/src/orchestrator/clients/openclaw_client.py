import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from orchestrator.config import settings
from orchestrator.schemas.requests import SpecialistCallRequest, SpecialistCallResult

# So reexecuta a chamada se a conexao NUNCA foi estabelecida (DNS falhou,
# gateway recusou a conexao, etc.) - ou seja, o Gateway com certeza nao
# recebeu o request, entao repetir e seguro. Deliberadamente NAO inclui
# timeout de leitura (`httpx.ReadTimeout`/`TimeoutException`): esta chamada
# roda um agent turn real (pode executar comandos, editar arquivos) - se o
# request JA chegou no Gateway e so a resposta demorou, reexecutar arrisca
# rodar a mesma acao duas vezes. Timeout de leitura vira erro direto (ver
# `call`), sem retry.
_CONNECT_FAILURE_EXCEPTIONS = (httpx.ConnectError, httpx.ConnectTimeout)

# Confirmado lendo o codigo-fonte real do Gateway (openclaw/src/gateway/) e
# openclaw/docs/gateway/openai-http-api.md: nao existe rota REST "/api/tasks"
# no OpenClaw - o Gateway e um servidor WS+HTTP multiplexado, e a unica
# superficie HTTP documentada capaz de rodar um agent turn completo (com
# exec/sandbox liberado) e o endpoint OpenAI-compativel abaixo. O outro
# candidato, POST /tools/invoke, bloqueia exec/spawn/shell por padrao (deny
# list fixa do Gateway HTTP) - inutil pro caso de uso do Especialista.
#
# Esse endpoint e desabilitado por padrao no openclaw.json alvo:
# gateway.http.endpoints.chatCompletions.enabled precisa estar true.
_TASK_ENDPOINT = "/v1/chat/completions"


class OpenClawClient:
    """Client HTTP para o gateway do OpenClaw (Especialista em Programacao).

    O orquestrador trata o OpenClaw como um servico externo: nao sabe (nem
    precisa saber) que por tras existe sandbox Docker isolado - so envia uma
    instrucao e recebe um resultado validado. Ver docs/ARQUITETURA_ORQUESTRADOR.md.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url or settings.openclaw_gateway_url
        self._timeout = settings.openclaw_request_timeout_sec

    async def call(self, request: SpecialistCallRequest) -> SpecialistCallResult:
        """Envia uma tarefa ao OpenClaw e retorna o resultado.

        Nenhuma excecao de rede vaza pro grafo: qualquer falha de I/O (timeout,
        conexao recusada, status 4xx/5xx) vira um
        SpecialistCallResult(success=False, error=...), que e o contrato que
        os nos do grafo sabem interpretar - o grafo decide o proximo passo a
        partir do campo `success`, nunca precisa de try/except pro client.
        """
        headers = {}
        if settings.openclaw_gateway_token:
            headers["Authorization"] = f"Bearer {settings.openclaw_gateway_token}"

        # Contrato OpenAI Chat Completions (ver docs/gateway/openai-http-api.md
        # do OpenClaw): "model" e um alvo de agent, nao um provider/model real -
        # "openclaw/default" roteia pro agente default configurado no Gateway.
        body = {
            "model": settings.openclaw_agent_model,
            "messages": [{"role": "user", "content": request.task_description}],
        }

        try:
            payload = await self._post(body, headers)
        except httpx.TimeoutException as exc:
            return SpecialistCallResult(success=False, output="", error=f"timeout ao chamar OpenClaw: {exc}")
        except httpx.HTTPStatusError as exc:
            return SpecialistCallResult(
                success=False,
                output="",
                error=f"OpenClaw retornou {exc.response.status_code}: {exc.response.text}",
            )
        except httpx.RequestError as exc:
            return SpecialistCallResult(success=False, output="", error=f"erro de rede ao chamar OpenClaw: {exc}")
        except ValueError as exc:
            # response.json() falhou (corpo nao-JSON) - trata como falha do especialista,
            # nao deixa o ValueError vazar pro grafo.
            return SpecialistCallResult(success=False, output="", error=f"resposta invalida do OpenClaw: {exc}")

        try:
            output = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            return SpecialistCallResult(
                success=False, output="", error=f"formato de resposta inesperado do OpenClaw: {exc} - payload={payload}"
            )

        return SpecialistCallResult(success=True, output=output)

    @retry(
        retry=retry_if_exception_type(_CONNECT_FAILURE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def _post(self, body: dict, headers: dict) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(_TASK_ENDPOINT, json=body, headers=headers)
            response.raise_for_status()
            return response.json()
