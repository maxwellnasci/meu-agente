# Padrão multi-cliente Docker — especificação da base replicável

Status: proposta técnica + rascunho (não implementado). Consolida a auditoria
anterior. Nada aqui altera comportamento existente.

Objetivo: cada cliente = 1 pasta `deployments/<cliente>/` autocontida,
subível com `docker compose up -d --build` a partir da própria pasta,
sem conflito de portas/redes no mesmo host, usando só imagens construídas
neste repositório.

## 1. Estrutura de pastas proposta

```text
templates/
  base/                        # NOVO — hoje não existe
    AGENTS_PARTE_A.md          # regras universais (extraídas de
                               # docs/templates/AGENTS_PARTE_B_TEMPLATE.md, PARTE A)
    docker-compose.client.yml  # template canônico do compose por cliente
    env.template               # modelo do .env por cliente
    openclaw.json.template     # modelo do gateway por cliente
  nichos/
    clinica-saude/
      AGENTS_PARTE_B.md        # só PARTE B (migrar do AGENTS.md atual)
      AGENTS.md                # legado — manter até migrar o script
      workflow-exemplo.json
    suporte-ti-pme/
      (idem)
deployments/
  <Cliente>/                   # gerado por scripts/provision-client.sh
    .env                       # 600, gitignored
    AGENTS.md                  # PARTE A + PARTE B composta
    docker-compose.yml         # renderizado do template base
    openclaw.json              # NOVO (a provisionar)
    workflows/workflow-*.json  # path parametrizado por cliente
    data/                      # sqlite do orquestrador (bind mount)
```

Regras:

- `templates/base/` é imutável por cliente; `templates/nichos/` contém só
  PARTE B + workflow de exemplo; `deployments/<cliente>/` é o único
  diretório com segredos e estado.
- Nenhum `.env`, `data/`, `openclaw.json` ou credencial é commitado
  (gitignore já cobre `**/.env`; estender para `deployments/*/data/`).
- O que existe hoje: `templates/nichos/*/AGENTS.md` (só PARTE B na
  prática, sem PARTE A universal), `deployments/` vazio, sem `templates/base/`.

## 2. Template do Docker Compose do cliente (`docker-compose.client.yml`)

Rascunho canônico. Variáveis vêm do `.env` do cliente; nada é hardcoded
por cliente exceto via substituição no provisionamento (`__SLUG__`,
`__CLIENT_NAME__`, `__NICHE__`).

```yaml
# Renderizado por scripts/provision-client.sh a partir de
# templates/base/docker-compose.client.yml. Uso: docker compose up -d --build
services:
  orchestrator-__SLUG__:
    build: ../../orchestrator              # imagem oficial do repo
    image: ${ORCHESTRATOR_IMAGE:-meu-agente-orchestrator:local}
    container_name: orchestrator-__SLUG__
    env_file:
      - path: .env
        required: true
    environment:
      # URL reversa gateway->orquestrador: o gateway chama este host:porta.
      ORCHESTRATOR_PUBLIC_URL: ${ORCHESTRATOR_PUBLIC_URL:-http://host.docker.internal:${ORCHESTRATOR_HOST_PORT:-8000}}
    volumes:
      - ./data:/app/data                  # checkpoints.sqlite por cliente
      - ./AGENTS.md:/app/AGENTS.md:ro      # NOVO — manual visível no container
    ports:
      - "127.0.0.1:${ORCHESTRATOR_HOST_PORT:?ORCHESTRATOR_HOST_PORT obrigatoria}:8000"
    networks:
      - net-__SLUG__                       # rede dedicada por cliente (abaixo)
    restart: unless-stopped
    healthcheck:                           # hoje ausente no compose gerado;
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s

networks:
  net-__SLUG__:
    name: cliente-__SLUG__                 # isolamento de tenant
    driver: bridge
```

Decisões de isolamento:

- **Portas:** só o orquestrador publica porta no host, sempre em
  `127.0.0.1:${ORCHESTRATOR_HOST_PORT}:8000`. Sem checagem de colisão hoje —
  o script passa a rejeitar porta já usada (ver §4). Container escuta sempre
  `:8000` (uvicorn, ver `orchestrator/Dockerfile`); unicidade vem da porta
  do host.
- **Redes:** 1 rede bridge dedicada por cliente (`cliente-<slug>`), em vez
  da `meu-agente-net` compartilhada atual. Gateway/n8n/cloudflared do
  cliente anexam-se a ela quando forem provisionados (§4). Elimina
  visibilidade cruzada entre tenants.
- **Volumes:** `./data` (bind, sqlite) + `./AGENTS.md` (ro). Evoluir para
  named volume (`<slug>-data:/app/data`) se o deploy exigir backup via
  `docker volume`; bind é o padrão enquanto o provisionamento for em host
  único com `data/` versionável no `.gitignore`.
- **Imagens:** só `build: ../../orchestrator` + `image:` parametrizável.
  Nenhuma imagem de terceiros nova; gateway OpenClaw segue o modelo de
  `SETUP_NOVO_CLIENTE.md` (build via `openclaw/scripts/docker/setup.sh` ou
  `docker save/load`), n8n é externo.
- **`.env` mínimo por cliente** (ver `templates/base/env.template` a criar):

```text
CLIENT_NAME='<nome>'
CLIENT_NICHE='<nicho>'
ORCHESTRATOR_IMAGE=${ORCHESTRATOR_IMAGE:-meu-agente-orchestrator:local}
ORCHESTRATOR_HOST_PORT='<porta-unica>'
ORCHESTRATOR_PUBLIC_URL='http://host.docker.internal:<porta-unica>'
ORCHESTRATOR_OPENCLAW_GATEWAY_URL='http://gateway-<slug>:18789'
ORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN=''
ORCHESTRATOR_N8N_URL=''
ORCHESTRATOR_N8N_API_KEY=''
ORCHESTRATOR_ATTENDANT_MODE='atendente'
ORCHESTRATOR_ATTENDANT_OPERATOR_NAME='<nome>'
ORCHESTRATOR_ATTENDANT_OPERATOR_TO='<numero>'
ORCHESTRATOR_ATTENDANT_CHANNEL='whatsapp-cloud'
```

Diferenças contra o `.env`/compose gerados hoje: `GATEWAY_URL` deixa de
ser o fixo `http://openclaw-gateway:18789` (colide entre clientes) e vira
`http://gateway-<slug>:18789`; `ORCHESTRATOR_HOST_PORT` passa a ser
obrigatória (`:?`); adiciona-se `ORCHESTRATOR_PUBLIC_URL` (caminho reverso).

## 3. Modelo de separação de prompts (PARTE A + PARTE B)

```text
deployments/<Cliente>/AGENTS.md = templates/base/AGENTS_PARTE_A.md
                                 + templates/nichos/<nicho>/AGENTS_PARTE_B.md
                                   (com placeholders substituídos)
```

- **PARTE A** (fixa, extraída de
  `docs/templates/AGENTS_PARTE_B_TEMPLATE.md` §§1–4 + `TREINAMENTO_AGENTS_MD.md`):
  identidade base, red-lines (sem inventar dados, sem atribuir falas,
  sem declarar ação não executada, sem diagnóstico profissional),
  tom/pt-BR/WhatsApp-curto, "não sei" como resposta válida, `ask_human`.
  Nunca recebe variável de cliente; atualiza-se por versão
  (ex. cabeçalho `<!-- PARTE A v1 -->`).
- **PARTE B** (por nicho + cliente): escopo Nível 1, red-lines do nicho,
  payload de transbordo, tabela pergunta/resposta, bloco
  `## Configuração deste cliente`. É o único lugar com placeholders.
- **Placeholders:** hoje só 5 são substituídos
  (`NOME_DA_CLINICA/EMPRESA, OPERADOR_NOME/NUMERO, CANAL`); `[ESPECIALIDADES]
  [CONVENIOS] [ENDERECO_TELEFONE] [SISTEMAS] [PLAYBOOKS]` seguem literais.
  Proposta: novos flags do script (ver §4) alimentam esses campos; o que não
  for informado permanece como `[A PREENCHER: ...]` explícito — nunca
  inventar conteúdo.
- **Composição:** substituição single-pass (`re.sub` com dicionário, como
  hoje) aplicada só à PARTE B, depois concatenação A + B. Migrar
  `templates/nichos/*/AGENTS.md` para `AGENTS_PARTE_B.md` mantendo o caminho
  antigo como alias até o script migrar.

## 4. Evolução do `provision-client.sh`

Comportamento atual (ver `scripts/provision-client.sh`): gera `AGENTS.md`
(single-pass, 5 placeholders), `workflows/`, `.env` (600),
`docker-compose.yml` (só orquestrador, rede compartilhada, sem healthcheck).
Novos parâmetros/arquivos para `docker compose up -d` funcionar por cliente:

Novos flags (todos opcionais exceto `--port`, que passa a ser obrigatório
para forçar alocação consciente):

- `--port <n>` obrigatório + checagem de colisão: rejeita se a porta já
  aparece em `deployments/*/.env` (`ORCHESTRATOR_HOST_PORT`) ou responde
  em `127.0.0.1:<porta>` (`(echo > /dev/tcp/127.0.0.1/<porta>)`).
- `--especialidades, --convenios, --endereco-telefone, --sistemas, --playbooks`
  (texto livre, mesmas regras anti-injeção atuais) → preenchem os `[...]`
  restantes da PARTE B; ausentes viram `[A PREENCHER: <CAMPO>]`.
- `--gateway-port/--n8n-url/--n8n-key` (reservados; guardam valores no `.env`,
  sem subir serviços ainda).
- `--base-template <path>` (default `templates/base/`): permite versionar a
  PARTE A / compose canônico.

Novos arquivos gerados por cliente:

1. `docker-compose.yml` renderizado de `templates/base/docker-compose.client.yml`
   (rede `cliente-<slug>`, healthcheck, mount `AGENTS.md:ro`,
   `ORCHESTRATOR_HOST_PORT:?`).
2. `.env` no modelo do §2 (`GATEWAY_URL=http://gateway-<slug>:18789`,
   `ORCHESTRATOR_PUBLIC_URL` reverso, demais segredos vazios).
3. `AGENTS.md` composto (A fixa + B do nicho com substituição).
4. `openclaw.json` (esqueleto do gateway do cliente: nome, portas
   `18789/3978` deslocadas ou rede dedicada, `chatCompletions.enabled=true`)
   — esqueleto nesta etapa, compose do gateway fica para etapa seguinte.
5. `workflows/workflow-<slug>-*.json` com `path:` parametrizado
   (`<slug>-atendimento` em vez de `clinica-atendimento` genérico) para
   permitir importar no mesmo n8n sem colisão.

Critério de pronto: após `provision-client.sh --name X ... --port N`,
`cd deployments/X && docker compose up -d --build && curl
http://localhost:N/health` retorna 200 sem tocar em outro cliente.

## 5. Viabilidade e não-conflitos

- **Portas:** unicidade garantida por `ORCHESTRATOR_HOST_PORT` obrigatória +
  checagem no script + bind em `127.0.0.1`. Falha rápida (`:?...`) se ausente.
- **Redes:** 1 bridge por cliente; nomes `cliente-<slug>` e
  `orchestrator-<slug>`/`gateway-<slug>` derivados do slug atual
  (lowercase, `tr -c 'a-z0-9' '-'`). Sem nomes globais fixos.
- **Imagens:** nenhuma imagem nova — orquestrador via `build:
  ../../orchestrator`; gateway/n8n seguem o runbook existente
  (`docs/templates/SETUP_NOVO_CLIENTE.md`, `docs/DEPLOY_IMAGEM.md`).
- **Fora do escopo desta etapa (registrado, não proposto):** compose do
  gateway OpenClaw por cliente, `cloudflared`, proxy reverso, n8n dedicado,
  TLS/segredos Meta — o compose do §2 sobe só o orquestrador isolado; os
  demais serviços entram nas etapas seguintes sobre a mesma rede
  `cliente-<slug>`.
