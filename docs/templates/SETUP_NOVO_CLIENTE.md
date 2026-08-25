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
automatiza build + detecção de `DOCKER_GID` + config do sandbox. Exemplo
já refletindo a decisão do item 5 abaixo (`github-repo-report` de fora
por padrão):
```bash
cd openclaw/
OPENCLAW_SANDBOX=1 OPENCLAW_EXTENSIONS="ask-max,whatsapp-cloud" \
  scripts/docker/setup.sh
```
Ainda builda localmente em cada servidor (não resolve "buildar uma vez só"),
mas elimina o processo manual de hoje e já lê `DOCKER_GID` sozinho.
**Atenção**: esse script gera seu próprio `docker-compose.yml` a partir de
`docker-compose.extra.yml` (mecanismo de overlay do próprio upstream) — o
`docker-compose.yml` atual do projeto tem customizações acumuladas ao
longo de meses (mount de skills, mount do projeto `meu-agente`, remoção
da porta legada 18790, hardening de `cap_drop`/`security_opt`) que
**não foram testadas** contra esse fluxo. Não trocar a produção pra essa
opção sem antes validar isolado que o overlay preserva tudo isso.

**Opção C, mencionada só pra registro**: publicar a imagem do gateway no
ghcr.io como foi feito pro orchestrator — resolveria "buildar uma vez
só" de verdade, mas é escopo maior (decidir extensões antes) e já está
marcado como pendência separada em `docs/DEPLOY_IMAGEM.md`.

**Recomendação**: pro próximo cliente, usar a Opção B primeiro num
ambiente de teste isolado (não Contabo) pra validar se o overlay resolve
sem perder as customizações — aí sim vira o padrão. Não decidido ainda,
fica como próximo passo.

## 4. Quais extensões habilitar (item 5 do roteiro, decidido 2026-08-25)

- **`whatsapp-cloud`** — o canal em si, sempre necessário se o cliente
  usa WhatsApp como interface. Não é uma escolha, é a infra de transporte.
- **`ask-max`** → **core, habilitar sempre**. `channel`/`to`/`accountId`
  já injetam o operador daquele cliente (config, não código) — é o
  mecanismo de escalonamento humano que a PARTE A do AGENTS.md (universal)
  já pressupõe que existe.
- **`github-repo-report`** → **add-on, não habilitar por padrão**. É
  ferramenta de dev-ops do próprio Max (relatório dos repos GitHub dele —
  `meu-agente`, `Mox---Sistemas`, `arbo`), sem uso pra um cliente típico
  de PME. Só habilitar se aquele cliente específico for um negócio de
  software/dev que precise disso.

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
