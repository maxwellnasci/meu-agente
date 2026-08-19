# Orchestrator

Orquestrador LangGraph (cérebro) que delega tarefas de programação ao OpenClaw
(especialista) via API. Faz parte do laboratório [meu-agente](../README.md).

## Arquitetura do Roteador

O nó `reason` do grafo (roteador do cérebro) usa **OpenRouter** como provedor
de LLM, via `langchain_openai.ChatOpenAI` apontando `base_url` para
`https://openrouter.ai/api/v1` (compatível com a API da OpenAI).

- **Modelo padrão:** `deepseek/deepseek-chat`
- **Variável de ambiente necessária:** `ORCHESTRATOR_OPENROUTER_API_KEY`
  (chave da OpenRouter, carregada de `.env` via `pydantic-settings` com prefixo
  `ORCHESTRATOR_`)

Configuração em `src/orchestrator/config.py`, uso em `src/orchestrator/graph/nodes.py`.

## Setup do ambiente

```bash
cd orchestrator
python -m venv .venv
.venv/bin/pip install -e .
```

Crie um `.env` na raiz de `orchestrator/` com:

```
ORCHESTRATOR_OPENROUTER_API_KEY=sua-chave-aqui
```

## Rodando

```bash
.venv/bin/uvicorn orchestrator.main:app --reload
```
