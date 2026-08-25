# Setup de infraestrutura — servidor de um cliente novo

Runbook pros itens 4 e 5 do roteiro de template multi-cliente
(`docs/PROXIMOS_PASSOS.md`). Preparado em 2026-08-25, é documentação —
nenhum túnel/imagem/servidor real foi criado por esta análise. Cobre os
3 pontos de infra que variam por servidor (GID do Docker, túnel
Cloudflare, imagem do gateway) e a decisão de quais extensões entram por
padrão em cada cliente novo.

## 0. Antes de começar

Decidir: hostname público do cliente (ex.: `whatsapp.clientex.com.br`),
nome do tunnel Cloudflare, e se esse cliente usa o mesmo domínio-base
(`mxos.com.br`) ou um domínio próprio.

## 1. GID do grupo Docker (já resolvido, só aplicar)

```bash
stat -c '%g' /var/run/docker.sock
```

Exportar como `DOCKER_GID` no `.env` do servidor novo. O
`openclaw/docker-compose.yml` já lê `${DOCKER_GID:-124}` (fix aplicado em
2026-08-25, commit `136a0ff77d8` no repo `max-openclaw-local-fixes`) — sem
essa variável, cai no default `124` (valor do Kali) e o sandbox real
(`agents.defaults.sandbox`) perde acesso ao `docker.sock` no servidor
novo. Confirmar o valor certo bate antes de subir o gateway com sandbox
ligado.

## 2. Túnel Cloudflare próprio

Cada servidor precisa do seu próprio túnel (não reusar UUID entre
clientes — isso já causou um incidente real de round-robin/perda de
mensagem, ver `docs/SESSAO_2026-08-04_checkpoint-etapa8.md`, "Problema 1:
duplo conector cloudflared").

```bash
# Uma vez por conta Cloudflare (se ainda não autenticado nesse servidor)
cloudflared tunnel login

# Cria o túnel do cliente novo - gera um UUID e um credentials-file em
# /root/.cloudflared/<UUID>.json (ou ~/.cloudflared/ dependendo do usuário)
cloudflared tunnel create <nome-do-cliente>

# Aponta o hostname público pro túnel (precisa do domínio já em Cloudflare DNS)
cloudflared tunnel route dns <nome-do-cliente> whatsapp.<dominio-do-cliente>
```

Config em `/etc/cloudflared/config.yml` (mesmo formato usado hoje no
Contabo pra `whatsapp.mxos.com.br`, só trocar UUID/hostname/porta):

```yaml
tunnel: <UUID-gerado-no-create>
credentials-file: /etc/cloudflared/<UUID-gerado-no-create>.json

ingress:
  - hostname: whatsapp.<dominio-do-cliente>
    service: http://localhost:18789
  - service: http_status:404
```

Depois: `systemctl enable --now cloudflared` (ou o equivalente do serviço
já criado por `cloudflared service install`).

**Nunca commitar** o `credentials-file` (`<UUID>.json`) nem o
`config.yml` preenchido em nenhum repo — mesma regra dos outros segredos
do projeto.

## 3. Imagem do gateway OpenClaw

Duas opções, com trade-off diferente do que já existe pro orquestrador
(ver `docs/DEPLOY_IMAGEM.md` — lá o orchestrator já publica no ghcr.io):

**Opção A — a que existe hoje (manual)**: build no Kali com as extensões
custom (`ask-max`, `github-repo-report`, `whatsapp-cloud`, ainda não
commitadas no repo vendorizado), depois `docker save`/`scp`/`docker load`
pro servidor novo. Funciona (é o que roda no Contabo), mas não escala —
repete o processo manual a cada cliente.

**Opção B — usar o script de setup do próprio upstream**, que já
automatiza build + detecção de `DOCKER_GID` + config do sandbox:
```bash
cd openclaw/
OPENCLAW_SANDBOX=1 scripts/docker/setup.sh
```
**Correção importante (validada com build real em 2026-08-25):**
`OPENCLAW_EXTENSIONS` **não** controla `ask-max`/`whatsapp-cloud`/
`github-repo-report` — esse build-arg só afeta uma lista fixa de
clusters oficiais do upstream (`acpx`, `msteams`, `whatsapp` sem o
"-cloud", etc., ver `scripts/lib/optional-bundled-clusters.mjs`). Testei
buildando com `OPENCLAW_EXTENSIONS="ask-max,whatsapp-cloud"` (tentando
excluir o `github-repo-report`) e inspecionei a imagem final: as 3
extensões customizadas entram sempre, o build-arg não teve efeito nelas.
Não adianta tentar controlar por aqui — ver seção 4 abaixo pro jeito
certo (runtime, não build-time).

Ainda builda localmente em cada servidor (não resolve "buildar uma vez só"),
mas elimina o processo manual de hoje e já lê `DOCKER_GID` sozinho.

**Correção da ressalva anterior (validado com teste real em 2026-08-25):**
o script **não** gera um `docker-compose.yml` do zero — ele usa o
`docker-compose.yml` real do projeto como base (`COMPOSE_FILE` no script)
e só *adiciona* um `docker-compose.extra.yml` gerado por cima (mounts
extras via `OPENCLAW_EXTRA_MOUNTS`/`OPENCLAW_HOME_VOLUME`), sem
substituir nada. Testei o merge de verdade
(`docker compose -f docker-compose.yml -f <extra>.yml config`) com um
mount extra fake: os 6 mounts customizados existentes (skills, projeto
`meu-agente`, docker.sock, etc.), `cap_drop`, `group_add` (com o fix do
`DOCKER_GID`) e a ausência da porta legada 18790 sobreviveram intactos,
e o mount novo entrou junto — é aditivo, não substitutivo. A ressalva
"não trocar produção sem validar antes" não se aplica mais nesse ponto.
(Nota: `docker-compose.extra.yml` aqui é gerado pelo próprio script pra
mounts — não confundir com `docker-compose.override.yml`, arquivo que
nós criamos manualmente pro fix do `group_add` abaixo; são dois
mecanismos diferentes.)

✅ **Bug do sandbox achado e CORRIGIDO (2026-08-25, validado ao vivo).**
Histórico: rodando a Opção B ponta a ponta (build+up+sandbox) num
ambiente isolado, achei que a ativação do sandbox quebrava
silenciosamente — o `group_add` estático do `docker-compose.yml` base
(fix do `DOCKER_GID` desta sessão) colidia com o `group_add` que o
próprio script injeta ao habilitar sandbox (`docker-compose.sandbox.yml`
gerado por ele), a validação de config rejeitava 2 entradas idênticas
(`group_add items at 0 and 1 are equal`), e o script revertia
`agents.defaults.sandbox.mode` pra `off` sem erro visível — só um
`WARNING` no log. Um cliente novo seguindo a Opção B como documentada
antes ficaria rodando sem a isolação de segurança principal do produto.

**Correção aplicada**: o `group_add` saiu do `docker-compose.yml` base e
virou `docker-compose.override.yml` (novo arquivo). O Compose inclui
`docker-compose.override.yml` automaticamente só quando **ninguém passa
`-f` explícito** — que é exatamente como a Opção A/produção sobe hoje
(`docker compose up -d`/`build`, sem flags, confirmado no histórico de
comandos do Contabo). `scripts/docker/setup.sh` (Opção B) passa `-f`
explícito e por isso **não** pega o override — deixando o script livre
pra injetar o `group_add` dele sozinho, sem colisão.

**Validado ao vivo, duas vezes** (antes e depois do fix, mesmo ambiente
isolado): antes do fix, sandbox revertia pra `off` com `WARNING`; depois
do fix, `Sandbox enabled: mode=non-main, scope=agent,
workspaceAccess=none` sem erro — confirmado em 3 níveis independentes
(não só o log): `docker inspect` mostra `GroupAdd: [124]` no container
real, o mount do `docker.sock` está presente, e o `openclaw.json`
persistido tem `sandbox.mode: "non-main"` de verdade. Produção
(Contabo) não foi tocada — testado só na cópia isolada em `/tmp`.

**Opção C, mencionada só pra registro**: publicar a imagem do gateway no
ghcr.io como foi feito pro orchestrator — resolveria "buildar uma vez
só" de verdade, mas é escopo maior (decidir extensões antes) e já está
marcado como pendência separada em `docs/DEPLOY_IMAGEM.md`.

**Recomendação final**: a Opção B agora pode virar padrão pro próximo
cliente — merge de compose e ativação de sandbox, os dois pontos de
risco, estão validados ao vivo. Falta só decidir quando migrar o Contabo
pra esse fluxo (não obrigatório, os dois caminhos coexistem).

## 4. Quais extensões habilitar (item 5 do roteiro, decidido 2026-08-25)

O código das 3 extensões vai pra imagem sempre (build não distingue —
ver correção na seção 3 acima). O ponto real de controle por cliente é
`openclaw.json` → `plugins.entries.<id>.enabled`, config, não build:

- **`whatsapp-cloud`** — `enabled: true` sempre que o cliente usa
  WhatsApp como interface. É o canal em si, não é uma escolha.
- **`ask-max`** → **`enabled: true` sempre (core)**. `channel`/`to`/
  `accountId` já injetam o operador daquele cliente (config, não
  código) — é o mecanismo de escalonamento humano que a PARTE A do
  AGENTS.md (universal) já pressupõe que existe.
- **`github-repo-report`** → **`enabled: false` por padrão (add-on)**.
  É ferramenta de dev-ops do próprio Max (relatório dos repos GitHub
  dele — `meu-agente`, `Mox---Sistemas`, `arbo`), sem uso pra um cliente
  típico de PME. Só virar `true` se aquele cliente específico for um
  negócio de software/dev que precise disso — a config já suporta isso
  sem precisar editar código nem rebuildar a imagem.

## 5. Depois da infra: config específica do cliente

Não é escopo deste doc (é o resto do roteiro de template), mas pra
fechar o checklist de um cliente novo, falta também:
- `docs/templates/AGENTS_PARTE_B_TEMPLATE.md` preenchido → vira o
  `~/.openclaw/workspace/AGENTS.md` do servidor novo (item 3, já pronto).
- `.env` com segredos do cliente (WhatsApp Cloud token, n8n API key se
  usar, `OPENCLAW_GATEWAY_TOKEN` novo).
- Nota: `OPENCLAW_PROJECT_MOUNT` (mount de `/home/max/.../meu-agente` no
  gateway) é específico do Kali — permite o especialista cybersec
  escanear este próprio projeto. **Não é infra de cliente**, não replicar
  pra servidor novo a menos que aquele cliente também precise que o
  agente escaneie o código dele (nesse caso, apontar pro repo daquele
  cliente, não pro `meu-agente`).
