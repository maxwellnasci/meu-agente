# Padrão multi-cliente Docker — especificação da base replicável

Status: especificação consolidada (etapa 2). Incorpora as blindagens já
implementadas no `scripts/provision-client.sh` (preservação de `data/`+`.env`
no `--force`, checagem de porta, namespace de webhook por slug,
`[A PREENCHER: ...]`) e as correções do Cão de Guarda/Revisor desta etapa
(rede bridge por DNS, sem `docker.sock`, consumidor do `AGENTS.md`,
isolamento de `deployments/`). Onde o script ainda diverge do alvo
(rede compartilhada, `GATEWAY_URL` fixo), o alvo normativo é o descrito aqui.

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
  (gitignore já cobre `**/.env`, `**/data/`, `**/gateway-token.json`; manter
  assim). Recomendação operacional: tratar `deployments/` como diretório de
  segredos+estado — ou mantê-lo fora do versionamento público via `.gitignore`
  (`deployments/` com exceção apenas de `deployments/.gitkeep`), ou apontar o
  provisionador para um diretório operacional fora do repo (ex.
  `/srv/meu-agente/clients/`, com `DEPLOYMENTS_DIR` configurável, perms
  `root:docker 0750` e `.env` a `0600`). Nunca publicar `deployments/<cliente>/`
  com tokens reais.
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
      # URL reversa gateway->orquestrador NA MESMA rede bridge isolada:
      # DNS interno do container. Nunca host.docker.internal / 127.0.0.1
      # (no Linux isso é loopback do próprio container e a chamada falha).
      ORCHESTRATOR_PUBLIC_URL: ${ORCHESTRATOR_PUBLIC_URL:-http://orchestrator-__SLUG__:8000}
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

- **Comunicação interna (rede bridge):** serviços do mesmo cliente falam
  entre si pelo DNS interno da rede isolada `cliente-<slug>-net`, sempre com
  o nome do container — ex. gateway→orquestrador via
  `http://orchestrator-<slug>:8000`, orquestrador→gateway via
  `http://gateway-<slug>:18789`. É **proibido** usar `host.docker.internal`
  apontando para `127.0.0.1` no Linux: dentro do container isso resolve para
  o loopback do próprio container, não do host, e a chamada entre serviços
  falha. O bind `127.0.0.1:${ORCHESTRATOR_HOST_PORT}:8000` existe só para
  acesso do operador a partir do host (`curl http://localhost:<porta>/health`);
  tráfego container↔container nunca passa por ele.
- **`docker.sock` desativado (regra de segurança):** para instâncias de
  clientes de atendimento comercial (clínicas, suporte N1, vendas), a
  montagem de `/var/run/docker.sock` é **proibida** em qualquer serviço do
  compose do cliente. Motivo: o atendimento processa texto arbitrário de
  terceiros; uma injeção de prompt que alcance um agente com acesso ao socket
  escala para controle total do host (criar containers privilegiados, montar
  `/`, ler segredos de outros tenants). O compose canônico acima não monta o
  socket — e nenhum override por cliente deve reintroduzi-lo. Sandbox/execução
  de código do atendimento usa worker sem Docker; se um caso futuro exigir
  Docker, fica fora do compose do tenant, em serviço dedicado e auditado.
- **Portas:** só o orquestrador publica porta no host, sempre em
  `127.0.0.1:${ORCHESTRATOR_HOST_PORT}:8000`. Implementado: o script rejeita
  porta já em escuta no host (`ss`, com fallback `lsof`/socket Python) e
  avisa sem abortar se outro `deployments/*/.env` declarar a mesma
  `ORCHESTRATOR_HOST_PORT`. Container escuta sempre `:8000` (uvicorn, ver
  `orchestrator/Dockerfile`); unicidade vem da porta do host.
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
ORCHESTRATOR_PUBLIC_URL='http://orchestrator-<slug>:8000'
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

## 3. Modelo de separação de prompts (PARTE A + PARTE B) e quem consome o quê

> Regra de consumo (não misturar): os prompts de decisão do orquestrador
> residem no grafo Python (`orchestrator/src/orchestrator/graph/nodes.py` —
> nós, guardas e transbordo) e **não** leem `AGENTS.md` em runtime. O
> `AGENTS.md` (PARTE A universal + PARTE B do nicho, já com placeholders
> substituídos) é montado no **Workspace do Gateway OpenClaw** do cliente
> (`./AGENTS.md:/app/AGENTS.md:ro` no compose do gateway, ou equivalente no
> `openclaw.json` do tenant) para guiar a **persona e as red-lines do
> atendimento** (tom, idioma, limites do Nível 1, o que nunca inventar,
> quando escalar via `ask_human`). Prompt de grafo decide; `AGENTS.md`
> persona-liza. Nada de segredo vai para o `AGENTS.md` — segredos ficam só
> no `.env` (600, gitignored).

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
- **Placeholders (implementado):** 5 são substituídos em passada única
  (`NOME_DA_CLINICA/EMPRESA, OPERADOR_NOME/NUMERO, CANAL`); `ESPECIALIDADES,
  CONVENIOS, ENDERECO_TELEFONE, SISTEMAS, PLAYBOOKS` sem flag na CLI viram
  `[A PREENCHER: <CAMPO>]` explícito com aviso no stderr — nunca inventar
  conteúdo. Lista fechada de propósito: texto de exemplo como `[ID]` e
  valores literais via argumento (ex. operador `[CANAL]`) não são tocados.
- **Composição:** substituição single-pass (`re.sub` com dicionário, como
  hoje) aplicada só à PARTE B, depois concatenação A + B. Migrar
  `templates/nichos/*/AGENTS.md` para `AGENTS_PARTE_B.md` mantendo o caminho
  antigo como alias até o script migrar.

## 4. Evolução do `provision-client.sh`

Comportamento implementado (ver `scripts/provision-client.sh`): gera `AGENTS.md`
(single-pass, 5 placeholders + `[A PREENCHER: ...]`), `workflows/` com webhook
sufixado `-<slug>`, `.env` (600, preservado no `--force`), `docker-compose.yml`
(só orquestrador; `--force` preserva `data/`+`.env` com troca atômica e recusa
porta em escuta no host). Divergências ainda abertas contra o alvo do §2 (rede
compartilhada `meu-agente-net` em vez da dedicada, `GATEWAY_URL` fixo,
sem healthcheck/mount `AGENTS.md:ro`): migrar quando o compose do gateway por
cliente for provisionado. Novos parâmetros/arquivos para `docker compose up -d`
funcionar por cliente:

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
