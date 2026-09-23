from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracao central do orquestrador, carregada de variaveis de ambiente."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="ORCHESTRATOR_")

    # API
    host: str = "0.0.0.0"
    port: int = 8000
    # Token de autenticacao dos endpoints protegidos (/v1/turn,
    # /tasks/stream) - lido de ORCHESTRATOR_API_TOKEN. None = modo dev,
    # sem autenticacao (nao quebrar suites existentes).
    api_token: str | None = None

    @field_validator("api_token", mode="before")
    @classmethod
    def _normalize_api_token(cls, v: object) -> str | None:
        """Simetria exata com o cliente TypeScript
        (resolveOrchestratorApiToken em
        extensions/whatsapp-cloud/src/orchestrator-client.ts): trim e
        string vazia/so espacos vira None (modo dev, sem autenticacao)."""
        if v is None:
            return None
        if not isinstance(v, str):
            return v  # type: ignore[return-value]
        stripped = v.strip()
        return stripped or None

    # OpenClaw gateway (Especialista em Programacao) - fala com o endpoint
    # OpenAI-compativel /v1/chat/completions do Gateway (ver
    # clients/openclaw_client.py). Esse endpoint roda a instrucao como um
    # agent run normal do OpenClaw (mesmo codepath de `openclaw agent`), e
    # e desabilitado por padrao no openclaw.json alvo -
    # gateway.http.endpoints.chatCompletions.enabled precisa estar true.
    openclaw_gateway_url: str = "http://localhost:18789"
    openclaw_gateway_token: str | None = None
    openclaw_agent_model: str = "openclaw/default"
    openclaw_request_timeout_sec: int = 120

    # n8n (Especialista de Automacao) - fala com a API REST publica de uma
    # instancia de n8n externa em producao (Contabo, https://n8n.mxos.com.br).
    # Ver clients/n8n_client.py. A API key fica em ORCHESTRATOR_N8N_API_KEY.
    n8n_url: str | None = None
    n8n_api_key: str | None = None
    n8n_request_timeout_sec: int = 30

    # Janela de validade (segundos) de uma proposta de acao n8n que muda
    # producao (create/activate/deactivate/delete) enquanto espera o usuario
    # confirmar. Passado o prazo, a pendencia e descartada e o usuario precisa
    # refazer o pedido - ver graph/n8n_confirmation.py. 15 min cobre uma
    # conversa de WhatsApp com idas e vindas sem deixar uma acao "armada"
    # indefinidamente.
    n8n_confirmation_ttl_sec: int = 900

    # Roteador do Cerebro (no `reason`) - via OpenRouter (padrao OpenAI,
    # base_url apontando pro OpenRouter). A chave fica em
    # ORCHESTRATOR_OPENROUTER_API_KEY.
    openrouter_api_key: str | None = None
    router_model: str = "deepseek/deepseek-chat"

    # Resposta direta do Cerebro (no `general_answer`), mesma chave/base_url
    # do roteador acima - modelo separado pra poder trocar independente do
    # roteador (classificacao barata vs conversa natural) sem acoplar os dois.
    general_model: str = "deepseek/deepseek-chat"

    # Trava de loop infinito do Enxame: quantas vezes o no `supervisor` pode
    # rodar numa unica execucao do grafo antes de `synthesize_final` abortar
    # com uma mensagem de seguranca fixa (ver graph/nodes.py). Cada rodada
    # do supervisor pode despachar varios especialistas de uma vez (tool
    # calls paralelas), entao isto limita "quantas vezes o supervisor
    # reavalia o progresso", nao quantos especialistas rodam no total.
    max_supervisor_iterations: int = 4

    # Endpoint sincrono /v1/turn (porta de entrada Node.js) - tempo maximo de
    # espera pela execucao completa do grafo antes de devolver uma resposta
    # de fallback ao usuario. Precisa ser maior que
    # openclaw_request_timeout_sec: o grafo inclui a chamada ao Especialista
    # por baixo, entao um turn_timeout_sec menor corta a execucao pela
    # metade (e descarta um resultado que estava prestes a chegar) em vez de
    # deixar o timeout real acontecer dentro da chamada HTTP ao OpenClaw.
    # Margem de 30s cobre o roteador + overhead do grafo em volta da chamada.
    turn_timeout_sec: int = 150

    # Modo Atendente (resposta conversacional + transbordo humano).
    # `attendant_mode` e o perfil padrao do orquestrador: "atendente" usa as
    # tools de transbordo (schemas/human_tools.py, entrega via plugin
    # ask-max no gateway); "executor" usa as tools de automacao n8n
    # (schemas/n8n_tools.py + guardrails em graph/n8n_guard.py). E so um
    # rotulo de perfil/padrao - nao desliga nada sozinho.
    attendant_mode: str = "atendente"

    # Operador humano de destino do transbordo. 100% configuracao, nunca
    # valor fixo no codigo: `to` e o contato no canal (ex.: WhatsApp so com
    # digitos), `name` e o nome de exibicao usado na mensagem de
    # escalonamento, `channel`/`account_id` identificam o canal no gateway.
    # Espelham ASKMAX_* no .env.example da raiz.
    attendant_operator_name: str = "Max"
    attendant_operator_to: str | None = None
    attendant_channel: str = "whatsapp-cloud"
    attendant_account_id: str | None = None

    # Checkpointing
    checkpointer_sqlite_path: str = "./data/checkpoints.sqlite"

    # Observabilidade (LangSmith)
    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str = "orchestrator-portfolio"


settings = Settings()
