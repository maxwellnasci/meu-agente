from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Chaves `ORCHESTRATOR_*` que moram no MESMO `orchestrator/.env` mas NAO sao
# deste Settings: as do compose (interpolacao `${ORCHESTRATOR_IMAGE}` etc. no
# docker-compose.yml) e as do lado do gateway Node, documentadas ali para o
# par orquestrador<->gateway ficar consistente. Sem esta lista, copiar o
# `orchestrator/.env.example` como `.env` derrubava o import (extra_forbidden).
# Qualquer OUTRA chave desconhecida continua derrubando (protege de typo).
COMPOSE_E_GATEWAY_KEYS = frozenset({"image", "data_dir", "host_port", "network", "url", "turn_timeout_ms"})


class Settings(BaseSettings):
    """Configuracao central do orquestrador, carregada de variaveis de ambiente."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="ORCHESTRATOR_")

    @model_validator(mode="before")
    @classmethod
    def _descartar_chaves_de_compose_e_gateway(cls, data: object) -> object:
        """O `.env` entrega as extras como `orchestrator_<nome>` (minusculo)."""
        if not isinstance(data, dict):
            return data
        prefixo = "orchestrator_"
        return {
            k: v
            for k, v in data.items()
            if not (isinstance(k, str) and k.lower().startswith(prefixo) and k.lower()[len(prefixo):] in COMPOSE_E_GATEWAY_KEYS)
        }

    # API
    # Bind em todas as interfaces DENTRO do container (necessario para o
    # publish do Docker); a exposicao real e controlada pelo compose, que so
    # publica em 127.0.0.1 (ou em rede interna, nos moldes de servidor dedicado).
    host: str = "0.0.0.0"  # nosec B104
    port: int = 8000
    # Token de autenticacao dos endpoints protegidos (/v1/turn,
    # /tasks/stream) - lido de ORCHESTRATOR_API_TOKEN. None = token ausente;
    # por padrao isso faz os endpoints protegidos FALHAREM FECHADO (401) -
    # ver verify_api_token em main.py. So vira modo dev sem autenticacao com
    # allow_insecure_dev_auth=True (opt-in explicito, abaixo).
    api_token: str | None = None

    @field_validator("api_token", mode="before")
    @classmethod
    def _normalize_api_token(cls, v: object) -> str | None:
        """Simetria exata com o cliente TypeScript
        (resolveOrchestratorApiToken em
        extensions/whatsapp-cloud/src/orchestrator-client.ts): trim e
        string vazia/so espacos vira None (token ausente)."""
        if v is None:
            return None
        if not isinstance(v, str):
            return v  # type: ignore[return-value]
        stripped = v.strip()
        return stripped or None

    # Opt-in EXPLICITO para religar o modo dev inseguro (endpoints
    # protegidos liberados sem nenhum token) quando `api_token` nao esta
    # configurado. Default False: falha fechado por omissao (ver
    # verify_api_token em main.py) - ausencia de configuracao nunca vira
    # acesso liberado sozinha. So usar em desenvolvimento local, nunca em
    # deploy real (os compose de `deployments/servidor-dedicado/` nem
    # deixam a stack subir sem ORCHESTRATOR_API_TOKEN, independente desta
    # flag - ver `${ORCHESTRATOR_API_TOKEN:?...}` nos dois moldes).
    allow_insecure_dev_auth: bool = False

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

    @field_validator("n8n_url", "n8n_api_key", mode="before")
    @classmethod
    def _normalize_n8n_config(cls, v: object) -> str | None:
        """Mesma normalizacao de api_token: string vazia/so espacos vira None."""
        if v is None:
            return None
        if not isinstance(v, str):
            return v  # type: ignore[return-value]
        stripped = v.strip()
        return stripped or None

    # Janela de validade (segundos) de uma proposta de acao n8n que muda
    # producao (create/activate/deactivate/delete) enquanto espera o usuario
    # confirmar. Passado o prazo, a pendencia e descartada e o usuario precisa
    # refazer o pedido - ver graph/n8n_confirmation.py. 15 min cobre uma
    # conversa de WhatsApp com idas e vindas sem deixar uma acao "armada"
    # indefinidamente.
    n8n_confirmation_ttl_sec: int = 900

    # Alvos de producao PROPRIA (IPs e dominios, separados por virgula) que o
    # Especialista de Ciberseguranca nunca pode escanear/testar - bloqueio
    # incondicional em graph/cybersec_guard.py (nao tem a excecao de negacao
    # dos nomes de servico). Configuracao e nao codigo de proposito: o IP real
    # do servidor nao deve estar versionado. Defina o IP/dominios reais em
    # ORCHESTRATOR_PROTECTED_TARGETS no .env de cada ambiente.
    protected_targets: str = "mxos.com.br"

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

    # Especialista de Procedimentos (RAG, docs/RAG.md). DESLIGADO por padrao:
    # desligado, o "rag" nao aparece no prompt do supervisor nem no schema da
    # tool DispatchSpecialist e nao pode ser roteado (um despacho alucinado e
    # descartado). Ligue so no ambiente que tiver o indice do manual.
    rag_enabled: bool = False
    # Indice SQLite PROPRIO
    # (sqlite-vec + FTS5), separado do checkpoints.sqlite e gerado offline por
    # `python -m orchestrator.rag.ingest`. O modelo de embedding NAO e
    # configurado aqui: vem da tabela `meta` do proprio indice (evita buscar
    # com um modelo diferente do da ingestao).
    rag_index_path: str = "./data/rag_index.sqlite"
    # hibrido (PADRAO desde a Missao 6: com o indice gerado com contexto em
    # BM25 + embedding, 16/17 de recall@5; decisao pela regra pre-registrada,
    # docs/RAG.md) | bm25 (15/17, sem fastembed) | vetorial. hibrido e vetorial
    # exigem o extra `rag` (fastembed): sem ele, a consulta vira erro tratado.
    rag_search_mode: Literal["bm25", "hibrido", "vetorial"] = "hibrido"
    rag_top_k: int = Field(default=5, ge=1, le=20)
    rag_colecao: str = "supermercado"
    # Cache do modelo de embedding (so usado nos modos hibrido/vetorial).
    rag_embedding_cache_dir: str = "./data/fastembed_cache"
    # Reranking (Missao 7): cross-encoder que reordena `rag_rerank_candidatos`
    # trechos e devolve os `rag_top_k`. None/vazio = sem rerank. Se o modelo
    # nao carregar (ou falhar), a busca cai para o modo acima, com log.
    rag_rerank_model: str | None = None
    rag_rerank_candidatos: int = Field(default=20, ge=1, le=50)
    # Regras do manual no synthesize_final (Missao 9): v1 = Missao 8, sem
    # formato; v2 = v1 + formato do Max (Sim/Nao primeiro, principal curta,
    # oferta de detalhes). O padrao so muda pela regra pre-registrada (docs/RAG.md).
    # v3 (Missao 10) = "pensa primeiro, formata depois": etapa 1 com as regras v1
    # (interna) + etapa 2 que so reescreve no formato (PROMPT_FORMATADOR_V3).
    rag_regras_versao: Literal["v1", "v2", "v3"] = "v1"

    @field_validator("rag_rerank_model", mode="before")
    @classmethod
    def _normalizar_rerank_model(cls, v: object) -> object:
        return v.strip() or None if isinstance(v, str) else v

    # Observabilidade (LangSmith)
    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str = "orchestrator-portfolio"


settings = Settings()
