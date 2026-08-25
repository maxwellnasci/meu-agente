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

🔴 **Achado real, roda ponta a ponta em 2026-08-25 num ambiente isolado
(cópia própria em `/tmp`, portas/projeto Docker/config dir diferentes —
não tocou no gateway real que estava rodando): a Opção B QUEBRA a
ativação do sandbox quando combinada com o fix do `DOCKER_GID` desta
sessão.**

O script builda e sobe o gateway normalmente, mas na etapa de sandbox
gera seu próprio overlay (`docker-compose.sandbox.yml`) com
`group_add: ["${DOCKER_GID}"]` — que se soma ao `group_add:
["${DOCKER_GID:-124}"]` que já existe no `docker-compose.yml` base
(nosso fix). O resultado tem 2 entradas idênticas, e a validação de
config do OpenClaw rejeita isso (`group_add items at 0 and 1 are
equal` — schema `uniqueItems`). O script **não trava com erro visível**:
ele detecta a falha, reverte `agents.defaults.sandbox.mode` pra `off` e
segue rodando o gateway **sem sandbox**, só com um `WARNING` no log. Ou
seja: seguir a Opção B como documentada antes ia deixar um cliente novo
rodando com o sandbox de segurança desligado sem ninguém perceber.

**Como evitar**: pra usar a Opção B com sandbox habilitado, o
`docker-compose.yml` base usado por ela não pode ter `group_add`
pré-populado — ou remover a linha antes de rodar o script (deixando ele
injetar sozinho via `docker-compose.sandbox.yml`), ou rodar o script
contra um checkout limpo do upstream em vez do nosso compose já
customizado. Ainda não decidido qual caminho adotar; por enquanto, se
for usar a Opção B, **conferir o log do script procurando por
"Sandbox mode rolled back to off"** antes de considerar o setup pronto.

**Opção C, mencionada só pra registro**: publicar a imagem do gateway no
ghcr.io como foi feito pro orchestrator — resolveria "buildar uma vez
só" de verdade, mas é escopo maior (decidir extensões antes) e já está
marcado como pendência separada em `docs/DEPLOY_IMAGEM.md`.

**Recomendação atualizada**: o mecanismo de merge de compose (mounts
extras) está confirmado seguro, mas **a Opção B não pode virar padrão
ainda** por causa do bug do sandbox acima — resolver isso primeiro
(provavelmente removendo o `group_add` estático do `docker-compose.yml`
base e deixando o script de qualquer uma das opções injetar sozinho)
antes de recomendar pra um cliente novo.

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
