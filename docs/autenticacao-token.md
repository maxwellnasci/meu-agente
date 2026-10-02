# Autenticação por Token Bearer: Gateway OpenClaw ↔ Orchestrator

## 1. Contexto & Escopo

Padronização da autenticação entre o gateway OpenClaw e o Orchestrator (FastAPI/LangGraph) via token Bearer. Objetivo: toda chamada do gateway (e de qualquer outro serviço, como n8n ou webhooks externos) ao Orchestrator passa a exigir um token compartilhado (`ORCHESTRATOR_API_TOKEN`), validado de forma fail-closed nos endpoints sensíveis.

---

## 2. Parte 1: Orchestrator (FastAPI / LangGraph)

### 2.1 Geração e Injeção

- **CONFIRMADO:** `ORCHESTRATOR_API_TOKEN` foi gerado com `openssl rand -hex 16`.
- **CONFIRMADO:** o valor foi inserido via append (`>>`) em `orchestrator/.env`, preservando estritamente as demais variáveis de ambiente já presentes (OpenRouter, gateway, n8n) — nenhuma variável existente foi sobrescrita ou removida.
- **CONFIRMADO:** não existe `.env` na raiz do repositório — essa ausência é intencional, não um esquecimento.
- **CONFIRMADO:** o arquivo `.env.bak` foi removido.

### 2.2 Execução do Compose

- **CONFIRMADO:** o orquestrador deve ser executado a partir da pasta `orchestrator/` (ex.: `docker compose up -d --build` dentro de `orchestrator/`).
- **CONFIRMADO:** executar o compose a partir da raiz do repositório cria um projeto Docker Compose duplicado, em conflito de porta com o projeto correto (porta 8000).

### 2.3 Endpoints e Segurança

- **CONFIRMADO:** os endpoints `/v1/turn` e `/tasks/stream` exigem o token Bearer, validado por um middleware/dependência `verify_api_token` em `main.py`, com comportamento fail-closed (requisição sem token válido é rejeitada por padrão).
- **CONFIRMADO:** o endpoint `/health` permanece aberto, sem exigência de token, para permitir healthcheck.

### 2.4 Contrato de API

- **CONFIRMADO:** o schema do payload aceito em `/v1/turn` exige os campos `{"session_key", "text", "from"}`.
- **CONFIRMADO:** o envio do campo `"input"` (em vez do schema correto) resulta em erro `422 Unprocessable Entity`.

### 2.5 Validações

- **CONFIRMADO:** requisição a `/v1/turn` sem token retorna `401 Unauthorized`.
- **CONFIRMADO:** requisição a `/v1/turn` com token válido retorna `200 OK`.

### 2.6 Ponto em Aberto / Hipótese

- **PONTO EM ABERTO:** em investigação anterior, uma chamada retornou `200 OK` sem token, antes da execução de `docker compose up -d --build`. A causa não foi confirmada. Hipótese de trabalho: o container antigo (anterior à adição do middleware `verify_api_token`) ainda estava em execução no momento do teste, respondendo sem a validação nova. Isso não foi verificado de forma definitiva e permanece como pendência de investigação.

---

## 3. Parte 2: Gateway OpenClaw & Extension Orchestrator-Bridge

### 3.1 Mecanismo do Bridge

- **CONFIRMADO:** a extensão orchestrator-bridge lê `process.env.ORCHESTRATOR_API_TOKEN` dinamicamente a cada execução da tool (não armazena o valor em cache/memória de longo prazo).
- **CONFIRMADO:** quando o token é resolvido, a extensão envia o header `Authorization: Bearer <token>`.
- **CONFIRMADO:** quando o token está ausente, a chamada é enviada sem o header `Authorization`, e o Orchestrator bloqueia a requisição (via `verify_api_token`, fail-closed).

### 3.2 Diagnóstico da Falha

- **CONFIRMADO:** o gateway lia unicamente o arquivo `openclaw/.env`, onde a variável `ORCHESTRATOR_API_TOKEN` estava ausente.
- **CONFIRMADO:** com a variável ausente, o container do gateway rodava com o token resolvendo para string vazia, cujo hash SHA-256 correspondente é `e3b0c442` (prefixo do hash de string vazia) — isso gerava `401 Unauthorized` em toda chamada ao Orchestrator.

### 3.3 Correção

- **CONFIRMADO:** o mesmo valor de `ORCHESTRATOR_API_TOKEN` foi adicionado via append (`>>`) em `openclaw/.env`.
- **CONFIRMADO:** o container do gateway foi recriado com `docker compose up -d --force-recreate openclaw-gateway`, executado dentro da pasta `openclaw/`.

### 3.4 Integridade Validada

- **CONFIRMADO:** o hash SHA-256 do token é idêntico nos containers do gateway e do Orchestrator.
- **CONFIRMADO:** a variável `ORCHESTRATOR_API_TOKEN` foi confirmada presente no ambiente (`environ`) de todos os processos internos relevantes, incluindo o processo Node principal do gateway.

### 3.5 Validação Real

- **CONFIRMADO:** uma chamada originada do gateway (IP interno `172.20.0.3`) retornou `200 OK`, registrada nos logs do Orchestrator.

### 3.6 Smoke Test via CLI (causa não confirmada)

- **HIPÓTESE (NÃO CONFIRMADA):** o smoke test via `docker exec ... agent` (CLI) recebeu `401`. Observado: a CLI não conseguiu parear com o gateway (`pairing required`) e caiu em "embedded fallback", um processo avulso. Não explicado: por que esse processo enviou a requisição sem `Authorization`, já que um `curl` de dentro do mesmo container, com a mesma variável, retornou 200. O fluxo contínuo de produção foi validado separadamente na seção 3.5.

---

## 4. Pendências e Cuidados Operacionais

- **PENDÊNCIA:** o container `openclaw-openclaw-cli-1` ficou com rede quebrada como efeito colateral da recriação do gateway (`--force-recreate openclaw-gateway`). Para restabelecer o CLI, rodar:
  ```
  docker compose up -d --force-recreate openclaw-cli
  ```
  dentro da pasta `openclaw/`.
- **ATENÇÃO:** chamadas de outros serviços (como n8n ou webhooks externos) ao Orchestrator sem o token resultarão em `401 Unauthorized`, pelo mesmo mecanismo fail-closed descrito na seção 2.3.
- **POLÍTICA DE CREDENCIAIS:** o valor do token nunca deve ser exibido ou registrado em conversas, logs ou arquivos versionados. Apenas o nome da variável (`ORCHESTRATOR_API_TOKEN`) deve circular em documentação e discussão técnica.
