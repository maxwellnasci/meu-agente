from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracao central do orquestrador, carregada de variaveis de ambiente."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="ORCHESTRATOR_")

    # API
    host: str = "0.0.0.0"
    port: int = 8000

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

    # Checkpointing
    checkpointer_sqlite_path: str = "./data/checkpoints.sqlite"

    # Observabilidade (LangSmith)
    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str = "orchestrator-portfolio"


settings = Settings()
