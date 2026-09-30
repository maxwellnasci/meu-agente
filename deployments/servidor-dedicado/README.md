# Servidor Dedicado por Cliente (Single-Tenant Físico)

Documento de arquitetura e estratégia de produto para a nova linha de deploy
**dedicado**: uma VPS própria por empresa cliente, dividida em **2 Moldes
Modulares** que compõem o catálogo comercial (Core de entrada + Add-on de
automações).

> Este arquivo é documentação de arquitetura. Nenhuma credencial, IP, domínio
> ou dado de cliente real deve ser adicionado aqui — configs concretas de
> clientes ficam fora do controle de versão (ver `.gitignore`,
> `deployments/*`).

---

## Visão Geral e Modelo de Negócio

Hoje o Amigão/OpenClaw roda em modelo multi-tenant compartilhado. A nova
oferta comercial é **single-tenant físico**: cada empresa cliente recebe sua
própria VPS (Hetzner, Contabo, DigitalOcean, etc.), isolada de qualquer outro
cliente.

**Benefícios do modelo:**

- **LGPD / compliance absoluto** — os dados do cliente (conversas, contatos,
  automações) nunca saem da VPS que pertence a ele. Não há banco
  compartilhado, não há tenant_id, não há superfície de vazamento
  cross-cliente.
- **Blast radius zero** — uma queda, um pico de uso ou um bug de outro
  cliente não afeta ninguém além dele mesmo. Cada incidente é isolado por
  construção, não por configuração.
- **Alta percepção de valor corporativo** — "seu próprio servidor" é um
  argumento comercial forte para empresas que já têm requisitos de
  segurança/compliance (jurídico, saúde, financeiro), justificando um ticket
  mais alto que o plano compartilhado.

---

## Arquitetura Modular: os 2 Moldes

A oferta é dividida em dois moldes de docker-compose independentes, pensados
para deploy incremental — o cliente começa no Molde 1 e faz upsell para o
Molde 2 quando precisar de automações mais avançadas.

### Molde 1 — Kit Agente Essencial (Core Standalone / Entrada)

Componentes:

- **`openclaw-gateway`** — Gateway WhatsApp (WhatsApp Cloud API).
- **`orchestrator`** — Orquestrador Python (LangGraph) com persistência local
  leve em SQLite (`checkpoints.sqlite`) e transbordo humano via plugin
  `ask-max`.
- **`cloudflared`** — túnel seguro (Cloudflare Tunnel), único ponto de saída
  para a internet.

Hardware recomendado:

- VPS de **2 vCPUs / 2GB RAM** (~US$ 4-6/mês).
- Consumo esperado: **< 800MB RAM** em repouso/carga moderada.

Casos de uso: cobre **80-90% das empresas** — atendimento 24/7, triagem,
FAQs, suporte de primeiro nível, qualificação de leads e transbordo humano.
Custo baixíssimo, zero manutenção de banco de dados pesado.

### Molde 2 — Kit Power-Up de Automações (Add-on / Expansão)

Componentes adicionados sobre o Molde 1:

- **`n8n`** — motor de fluxos de automação.
- **`postgres`** — banco relacional dedicado ao `n8n`.
- Ingress adicional no Cloudflare Tunnel: `automacoes.<cliente>.com.br`.

Hardware recomendado:

- Upgrade da VPS para **4GB RAM / 2 vCPUs**.
- Consumo estimado: **~2.2GB – 2.8GB RAM** com os dois moldes ativos.

Casos de uso: integrações avançadas com CRM, ERP, Google Calendar, Bling e
automações complexas multi-etapa.

Modelo comercial: **upsell modular** — mensalidade adicional de integração,
vendida separadamente do plano Core.

---

## Blindagem e Rede

Regras de rede válidas para os dois moldes, sem exceção:

- **Nenhuma porta aberta em `0.0.0.0`** no host da VPS.
- Comunicação entre containers exclusivamente via **rede interna bridge**
  dedicada (`agente-net`) — nenhum serviço interno é exposto diretamente ao
  host.
- Acesso externo **100% outbound** via Cloudflare Tunnel: zero portas de
  entrada abertas no firewall da VPS. O tunnel inicia a conexão de dentro
  para fora; não há listener público exposto.

---

## Fluxo de Desenvolvimento e Validação (Metodologia Segura)

1. Construção dos arquivos de molde (docker-compose, `.env.example`,
   scripts de bootstrap) **localmente no Kali Linux**, nunca direto em
   produção.
2. **Validação local** completa (subida dos containers, testes ponta a
   ponta) antes de qualquer deploy em VPS de cliente.
3. Testes ponta a ponta com **teardown seguro** (`docker compose down -v`)
   entre iterações, garantindo que nenhum estado de teste vaze para o
   próximo ciclo.
4. **Script futuro de bootstrap zero-touch** para VPS virgem (Ubuntu 24.04)
   — provisionar o host do zero (Docker, usuário, firewall) ainda não está
   implementado. O `bootstrap.sh` atual cobre o passo seguinte: prepara o
   diretório de deploy (bind mounts, dono UID 1000, `.env` 600,
   `openclaw.json` a partir do template) de forma idempotente.

---

## Armadilhas conhecidas do Molde 1

Duas regras que não são óbvias lendo só o compose, e que já causaram
falha silenciosa:

### `phoneNumberId` exige valor literal

Em `channels.whatsapp-cloud`, os campos `accessToken`, `appSecret` e
`verifyToken` aceitam SecretRef de ambiente `${VAR}` — passam por
`resolveConfiguredSecretInputString()` (`src/config/types.secrets.ts`).
O `phoneNumberId` **não**: ele é lido cru em
`extensions/whatsapp-cloud/src/accounts.ts`
(`String(merged.phoneNumberId ?? "").trim()`). Um `${VAR}` ali vira string
literal e o agente falha **em silêncio nos dois sentidos** — não envia (URL
do Graph inválida) e não recebe (webhook recusado por `phone_number_id`
divergente).

Por isso o `openclaw.json.template` traz o marcador
`__WHATSAPP_CLOUD_PHONE_NUMBER_ID__`, que o `bootstrap.sh` substitui pelo
número em dígitos vindo do `.env`. Se o marcador sobreviver, o bootstrap
avisa antes de você subir a stack.

### `dmPolicy`/`allowFrom` abertos por padrão

O template sobe com `"dmPolicy": "open"` e `"allowFrom": ["*"]` de
propósito, para não travar o handshake inicial nem o onboarding da empresa.
Em produção, quando o número é restrito ou de uso interno, troque para
`"dmPolicy": "allowlist"` e liste os contatos autorizados em `allowFrom`
(DDI+DDD+número, só dígitos). Deixar `open` em número público significa
responder a desconhecidos e gastar LLM com tráfego não autorizado.

---

## Status

Este documento registra a **arquitetura definida** e os artefatos de
implementação já criados para os dois moldes.

**Molde 1 — Kit Agente Essencial** — criado e homologado, incluindo ciclo
real de `docker compose up -d` em laboratório descartável (containers
`healthy`, bridge `agente-net` testada ativamente, teardown limpo):

| Artefato | Função |
| --- | --- |
| `docker-compose.molde1.yml` | Stack Core (gateway + orquestrador + cloudflared) na rede `agente-net`, sem porta publicada no host |
| `.env.example` | Modelo versionado de variáveis, só placeholders |
| `openclaw.json.template` | Config do gateway com SecretRefs e marcador do `phoneNumberId` |
| `bootstrap.sh` | Prepara a VPS: bind mounts, permissões UID 1000, `.env` 600, config a partir do template, `docker compose config -q` |

Pendente no Molde 1: smoke test de webhook ponta a ponta (o `cloudflared`
ainda não foi validado com um `POST` real/simulado da Meta).

**Molde 2 — Kit Power-Up de Automações** — compose e templates de suporte
criados; validado apenas com `docker compose config -q` (sintaxe), **ainda
sem** ciclo de `up -d` real nem bootstrap dedicado:

| Artefato | Função |
| --- | --- |
| `docker-compose.molde2.yml` | Stack Core do Molde 1 (standalone, replicada, não `extends`) + `n8n` + `postgres`, com `cloudflared` roteando 2 hostnames |
| `.env.example` (seções 8-10) | Variáveis `POSTGRES_*`, `N8N_*` e `ORCHESTRATOR_N8N_*`, adicionadas na mesma seção do arquivo do Molde 1 |

Pendente no Molde 2:
- Ciclo real de `docker compose up -d` (containers + healthchecks + bridge),
  igual ao que já foi feito para o Molde 1.
- `bootstrap.sh` ainda não conhece o diretório `n8n/` (só cria/chowna
  `openclaw/ workspace/ data/`) — hoje o `chown -R 1000:1000 n8n` do
  Molde 2 é manual.
- Segundo hostname do Cloudflare Tunnel (`automacoes.<cliente>.com.br`) só
  existe como variável de ambiente/documentação; a configuração real fica
  no dashboard da Cloudflare, fora deste repositório.
- Script de bootstrap zero-touch do host (Ubuntu 24.04) — comum aos dois
  moldes, continua não implementado.
