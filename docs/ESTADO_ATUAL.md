# Estado Atual do Projeto

## 🚀 MUDANÇA DE INFRAESTRUTURA — Amigão migrado pro Contabo (2026-08-02), Etapa 8 concluída (2026-08-04)

**O Amigão roda em PRODUÇÃO no servidor Contabo, não mais no Kali.**
Cutover do túnel Cloudflare feito às 22:51 UTC de 2026-08-02, entrega
ponta a ponta confirmada via Contabo às 22:56 UTC. **Etapa 8 concluída
em 2026-08-04**: container antigo do Kali parado (`docker compose
stop`, não deletado, reversível), cloudflared do Kali confirmado
inativo/desabilitado. Checkpoint de verificação (achado sobre boot do
Kali fora do previsto, fix de segurança de portas, falso positivo do
response-audit) em
[SESSAO_2026-08-04_checkpoint-etapa8.md](SESSAO_2026-08-04_checkpoint-etapa8.md).
Detalhes do cutover original: [SESSAO_2026-08-02.md](SESSAO_2026-08-02.md).

| | Antes (até 2026-08-02) | Agora |
|---|---|---|
| Servidor de produção | Kali (notebook do Max) | **Contabo** (VPS, 158.220.125.233) |
| Depende do Kali ligado? | Sim (ponto único de falha) | **Não** |
| Cloudflare Tunnel roda em | Kali | **Contabo** |
| `~/.openclaw/` (estado) | Kali | **Contabo** (`/root/.openclaw/`) |

---

- **Nome do projeto:** MEU AGENTE (OpenClaw isolado para aprendizado)
- **Objetivo:** aprender agentes autônomos com máxima segurança
- **Modelo/cérebro:** Selecionável nativamente na interface web (V3, V4-flash, V4-pro). Em produção (Contabo) desde 2026-08-03: primary `deepseek/deepseek-v4-flash`, fallback `deepseek/deepseek-chat` (aplicado via Antigravity, reportado por Max — não auditado independentemente pelo Claude Code, ver [SESSAO_2026-08-04_checkpoint-etapa8.md](SESSAO_2026-08-04_checkpoint-etapa8.md))
- **Versão OpenClaw:** v2026.6.9 (confirmado - mais recente disponível)
- **Tentativa de update para v2026.6.10:** realizada em 05/07/2026
- **Resultado da tentativa:** v2026.6.9 é a versão mais atual no repositório oficial. Banner "atualização disponível" aparece antes do código ser publicado no GitHub deles.
- **Backup salvo em:** ~/backup-openclaw-20260705-0646/
- **Sistema:** Contabo healthy ✅ (produção). Kali parado por design desde 2026-08-04 (Etapa 8, fallback fechado — estado desejado, não erro)
- **Servidor de produção:** Contabo (VPS, Docker 29.6.1, Ubuntu 24.04.4) desde 2026-08-02. Kali (kernel 6.8.0-134) mantido como fallback parado.
- **nginx-app-1 (Contabo):** requer início manual após reboot
- **WhatsApp:** ✅ Cloud API oficial (Meta) FUNCIONANDO ponta a ponta (webhook recebe, Amigão responde) — agora servido pelo Contabo
- **Canal ativo:** whatsapp-cloud (extensão customizada), substituindo Baileys/Evolution como canal principal de WhatsApp
- **Baileys/Evolution:** descontinuado como canal principal
- **Túnel público:** Cloudflare Tunnel (whatsapp.mxos.com.br → localhost:18789), serviço systemd permanente, reconexão automática. **Conector ativo: Contabo** (desde 2026-08-02 22:51 UTC; antes era o Kali). Portas 18789/18790 do Kali restritas a `127.0.0.1` desde 2026-08-04 (config antiga expunha em `0.0.0.0`, sem exploração confirmada). Porta 18790 (bridge legacy, sem uso) removida por completo do docker-compose tanto no Contabo (produção, host) quanto no Kali (fallback) em 2026-08-04
- Docker socket removido do container do gateway (Contabo) em
  2026-08-04 - fechava rota RCE→root. Secrets DEEPSEEK_API_KEY e
  OPENCLAW_GATEWAY_TOKEN migrados de env cru pra SecretRef em arquivo
  (modo 600). Rotação de chaves e sandbox real (P0.2) pendentes - ver
  PROXIMOS_PASSOS.md.
- **Backup do repo local (`openclaw/`):** espelho privado em `github.com/maxwellnasci/max-openclaw-local-fixes` (branch `production-local-fixes`) desde 2026-08-04 — `origin` do clone segue intocado, apontando pro upstream público
- **Nova direção:** fork evolutivo do OpenClaw com 2º agente de segurança
- **Próximos passos:** Etapa 8 concluída (2026-08-04) — próximo: avaliar Claude Security pós-migração; investigar timeouts residuais do deepseek-v4-flash e falso positivo do response-audit (ver PROXIMOS_PASSOS.md)
- **Data da última atualização:** 2026-08-04

---

## ✅ MARCO — Etapa 8 concluída, checkpoint pós-migração auditado (2026-08-04)

- **Etapa 8 concluída**: `docker compose stop` no gateway do Kali —
  parado, não deletado, reversível. Cloudflared do Kali confirmado
  inativo e desabilitado antes e depois do stop.
- **Achado durante o checkpoint**: o gateway do Kali foi encontrado
  rodando (iniciado 2026-08-04 08:30:45 UTC, `RestartCount: 0`) antes da
  Etapa 8 — boot da máquina foi 3h antes (05:30:24 UTC), gap não
  totalmente reconciliado (ver atribuições de origem em
  [SESSAO_2026-08-04_checkpoint-etapa8.md](SESSAO_2026-08-04_checkpoint-etapa8.md)).
  Confirmado por Max que foi ele ligando o notebook.
- **Fix de segurança**: bind de portas 18789/18790 do Kali trocado de
  `0.0.0.0` (exposto, config desde 16/jul) pra `127.0.0.1`, mesma
  prática já usada no Contabo. Commit `d1c658fd2d`, branch
  `production-local-fixes`.
- **Backup remoto do repo local criado**:
  `github.com/maxwellnasci/max-openclaw-local-fixes` — `origin` do
  `openclaw/` (upstream público) permanece intocado.
- **Regressão do WhatsApp confirmada** (Max, 6 mensagens reais
  recebidas) e cobertura do `response-audit` no canal `whatsapp-cloud`
  confirmada via consulta direta na store (4 registros persistidos). Um
  falso positivo (`hallucination`) identificado e explicado — causa raiz
  e hipótese de melhoria futura em `PROXIMOS_PASSOS.md`. Detalhes:
  [SESSAO_2026-08-04_checkpoint-etapa8.md](SESSAO_2026-08-04_checkpoint-etapa8.md).

---

## ✅ MARCO — Amigão migrado pro Contabo, cutover do túnel concluído (2026-08-02)

- **Etapas 0-5** (backup, rsync do estado, transferência da imagem
  Docker, compose ajustado, gateway `healthy` no Contabo, credencial
  WhatsApp validada) concluídas na sessão de 2026-07-29.
- **Etapa 6 (2026-08-02):** `cloudflared` instalado no Contabo, mesma
  versão do Kali (2026.7.1), credenciais do túnel copiadas. Janela de 2
  conectores simultâneos (Kali + Contabo) monitorada com atenção.
- **Etapa 7 — cutover (2026-08-02, 22:51 UTC):** `cloudflared` parado
  no Kali, confirmado só o conector do Contabo ativo. Mensagem real de
  teste confirmou entrega ponta a ponta via Contabo às 22:56 UTC, sem
  erro. **Janela de 2 conectores durou ~8 minutos.**
- **Resultado:** Amigão rodando 100% em produção no Contabo — não
  depende mais do Kali estar ligado (resolve o gap de disponibilidade
  registrado no incidente de 2026-07-18). Etapa 8 (desligar de vez o
  container antigo do Kali) agendada condicional a 24h de observação
  estável. Detalhes completos: [SESSAO_2026-08-02.md](SESSAO_2026-08-02.md).

---

## ✅ MARCO — Bug de fila travada corrigido + backup git das extensões fechado (2026-07-20)

- **Bug de fila travada (sessão trava ~6min por mensagem):** causa raiz
  real confirmada — deadlock conhecido do core do OpenClaw
  (`foregroundReplyFenceByKey`, bug upstream `openclaw/openclaw#91914`,
  fix nunca mergeado). Corrigido via serialização por remetente em
  `extensions/whatsapp-cloud/src/webhook.ts` (não mexe em core), 6 testes
  novos, validado ao vivo pós-redeploy (rajada de 4 mensagens: 370s+/msg
  → ~22s total, zero travamento). Detalhes:
  [SESSAO_2026-07-20.md](SESSAO_2026-07-20.md).
- **Backup git das 4 extensões próprias:** pendência fechada — `ask-max`,
  `whatsapp-cloud`, `response-audit`, `github-repo-report` agora têm
  snapshot real no GitHub (`maxwellnasci/meu-agente`), sem depender só do
  branch local não-enviado dentro do `.git` interno do `openclaw/`. Ver
  nota de arquitetura acima e [SESSAO_2026-07-20.md](SESSAO_2026-07-20.md).
- **Próximo passo decidido:** planejar migração do Amigão pro servidor
  Contabo.

---

## ✅ MARCO — Bug 4 resolvido, `github-repo-report` conectado e funcional (2026-07-17)

Investigação de 3 dias (15–17/07) concluída. Case completo, com linha do
tempo honesta (incluindo as 4 hipóteses refutadas e a ressalva sobre a causa
exata do incidente original nunca ter sido capturada ao vivo):
[docs/CASE_BUG4_INVESTIGACAO_COMPLETA.md](CASE_BUG4_INVESTIGACAO_COMPLETA.md).

- **Mecanismo principal (contenção síncrona de SQLite, `busy_timeout`):**
  corrigido (30s → 3s), deployado de verdade em produção (confirmado por
  grep no bundle rodando, não só no commit), testado sob carga real do
  WhatsApp repetidas vezes sem recorrência.
- **2 bugs adicionais encontrados durante a investigação e corrigidos:**
  policy da tool sem bloqueio imediato para repo desconhecido (esperava
  ~130s em aprovação sem entrega possível no WhatsApp), e detector nativo de
  sessão travada com bug de escopo (limpava estado compartilhado sem
  filtrar por `runId`).
- **Bug de configuração encontrado e corrigido:** o allowlist que expõe a
  tool ao modelo estava em `tools.sandbox.tools.alsoAllow` (caminho sem
  efeito com `sandbox.mode: "off"`) em todas as tentativas anteriores;
  corrigido para `tools.alsoAllow` no nível raiz.
- **Confirmado ao vivo:** `tool.call` real de `github_repo_report` capturado
  no WhatsApp de produção (`toolName: github_repo_report`, `isError: false`),
  relatório estruturado real entregue ao usuário.
- **`github-repo-report`:** conectado em produção. Nenhum bug ativo
  conhecido relacionado a esta investigação.

---

## ✅ MARCO — WhatsApp Cloud API funcionando ponta a ponta (2026-07-14)

Primeira mensagem real recebida E respondida pelo Amigão via WhatsApp Cloud
API oficial da Meta. Fluxo completo: WhatsApp → Meta → Cloudflare Tunnel →
OpenClaw Gateway → Amigão (memória, sandbox, DeepSeek) → resposta via Graph API.

- **Infraestrutura:** Cloudflare Tunnel (`whatsapp.mxos.com.br`), serviço
  systemd permanente, não depende do Contabo estar de pé.
- **Canal:** `extensions/whatsapp-cloud/`, implementado como canal real
  (padrão `extensions/sms`), não TaskFlow — garante conversa contínua com
  memória por número de telefone. 16 testes automatizados, typecheck limpo.
- **Credenciais:** token de acesso PERMANENTE via System User (não expira),
  guardado em `~/.openclaw/credentials/whatsapp-cloud.json` (chmod 600).
- **Detalhes completos:** [docs/SESSAO_2026-07-14.md](SESSAO_2026-07-14.md)

---

## Confirmações adicionais — 2026-07-14 (sessão da tarde)

### Comportamento de boot (o que sobe sozinho ao ligar o Kali)
Restart policies verificadas com `docker inspect` e `systemctl is-enabled`:

| Componente | Sobe sozinho? | Evidência |
|---|---|---|
| Docker daemon | ✅ Sim | `systemctl is-enabled docker` → `enabled` |
| cloudflared (túnel) | ✅ Sim | `systemctl is-enabled cloudflared` → `enabled` |
| `openclaw-openclaw-gateway-1` | ✅ Sim | `RestartPolicy.Name` → `unless-stopped` |
| `openclaw-openclaw-cli-1` | ❌ Não | `RestartPolicy.Name` → `no` |

Ou seja: desligando e ligando o Kali, o fluxo do WhatsApp (Docker +
túnel + gateway) volta sozinho, sem intervenção manual. Só o
`openclaw-cli` precisa ser subido manualmente se for necessário
(`docker compose up -d openclaw-cli`), pois sua restart policy é `no`.

Ressalva: `unless-stopped` só reinicia automaticamente se o container
não tiver sido parado manualmente (`docker stop`/`compose stop`)
antes do desligamento.

### Troca de modelo no WhatsApp (V4-pro) — confirmado como temporária
Durante a sessão de hoje o modelo foi trocado para **V4-pro** via
comando na própria conversa do WhatsApp. Checado `~/.openclaw/openclaw.json`:
`agents.defaults.model.primary` continua `"deepseek/deepseek-chat"`,
ou seja, **a troca vale só para aquela sessão/conversa** — não é o
padrão do sistema. Se V4-pro deve virar o modelo padrão permanente,
é necessário atualizar manualmente o campo `model.primary` em
`openclaw.json` para o identificador correspondente ao V4-pro.

---

## Registro de pendências — 2026-07-15

1. **Token permanente System User: confirmado funcionando.**
   Correção do dia anterior (ver [SESSAO_2026-07-14.md](SESSAO_2026-07-14.md#correção-mesmo-dia-à-tarde-o-token-system-user-de-mais-cedo-não-era-de-verdade))
   validada via `debug_token`: `type: SYSTEM_USER`, `expires_at: 0`. Sem
   expiração inesperada desde então.
2. **Boot automático: confirmado** (já registrado na sessão de
   2026-07-14, seção "Confirmações adicionais" acima). Docker +
   cloudflared + `openclaw-openclaw-gateway-1` sobem sozinhos ao ligar
   o Kali. `openclaw-cli` continua exigindo start manual
   (`docker compose up -d openclaw-cli`).
3. **Troca de modelo via comando na conversa do WhatsApp:** confirmado
   que é temporária (vale só pra sessão/conversa, não altera
   `model.primary` em `openclaw.json` — já registrado na sessão de
   2026-07-14). **Em aberto:** decidir se V4-pro deve virar padrão
   permanente do sistema ou se a troca por sessão é o comportamento
   desejado.
4. **Teste de segurança do allowFrom: 3/3 cenários validados**
   (assinatura inválida, assinatura válida fora do allowFrom,
   assinatura válida dentro do allowFrom). Sem falha de segurança
   detectada. Detalhes e matriz completa: [SESSAO_2026-07-15.md](SESSAO_2026-07-15.md).

---

## ESTADO FINAL DO DIA 2026-06-24

- **Agente "Amigão":** Operacional
- **Modelo:** V4-pro (selecionado na sessão)
- **Sandbox:** Validado (`whoami` retornou "sandbox")
- **Nível de segurança:** *Defense in depth* com 6 camadas implementadas e testadas
- **Autenticação de Sub-agentes:** Corrigida via auth profiles (sqlite)
- **Warnings:** Limpos (allowedOrigins e memorySearch)
- **Status:** Estável, pronto para testar criação de arquivos

---

## ✅ SANDBOX ATIVO — Sistema blindado

**`sandbox.mode: "all"`** está configurado e operacional desde 2026-06-23.
O agente executa comandos em micro-containers descartáveis via `docker.sock`.
O `workspaceAccess: "none"` permanece ativo — o agente não acessa o filesystem do host.

---

## Checklist do que JÁ foi feito:

- [x] ✅ Ambiente mapeado (Node v24.16, Docker ativo, 389GB livres)
- [x] ✅ Auditoria de segurança do docker-compose (sem privileged, cap_drop, no-new-privileges)
- [x] ✅ Pastas de estado criadas (~/.openclaw, workspace, ~/.openclaw-auth-profile-secrets)
- [x] ✅ .env criado com token gateway + chave DeepSeek
- [x] ✅ .env protegido pelo .gitignore (não vaza no git)
- [x] ✅ openclaw.json com gateway.mode: "local" + cron desabilitado
- [x] ✅ pnpm v11.9.0 instalado
- [x] ✅ Imagem Docker openclaw:local reconstruída com Docker CLI interno (809MB)
- [x] ✅ Container `openclaw-openclaw-gateway-1` subiu e ficou estável
- [x] ✅ Plugin @openclaw/deepseek-provider instalado via `openclaw doctor --fix`
- [x] ✅ Plugin registry reconstruído (54/78 plugins indexados)
- [x] ✅ Primeira conversa bem-sucedida com DeepSeek V3
- [x] ✅ Portas validadas sem conflito com n8n (5678) e postgres (5432)
- [x] ✅ **Sandbox ativo e validado em produção** (teste whoami passou)
- [x] ✅ **DeepSeek V4-pro funcional** (selecionável na interface)
- [x] ✅ **Documentação completa no GitHub**
- [x] ✅ **6 camadas de segurança implementadas e testadas**
- [x] ✅ **Correção de auth de sub-agentes** (paste-api-key)
- [x] ✅ **Warnings limpos no gateway** (allowedOrigins, memorySearch)
- [x] ✅ **Acesso SSH configurado** (chave ed25519 no servidor Contabo)

## TESTES DE CAPACIDADE:

- [x] ✅ **Nível 1** — Sandbox validado (whoami, ls, data)
- [x] ✅ **Nível 2** — Sub-agentes paralelos funcionam, auth corrigido confirmado (2026-06-24)
- [x] ✅ **Nível 3** — Cenário MXOS-like testado com aprendizados críticos documentados (2026-06-24)
- [x] ✅ **Nível 3 pós-treinamento** — 3 falhas críticas resolvidas via AGENTS.md customizado (2026-06-24)

## MÉTODO DE TREINAMENTO — VALIDADO ✅

**Treinamento via AGENTS.md: FUNCIONAL**

O OpenClaw injeta automaticamente "Bootstrap Files" no system prompt de cada sessão.
O `AGENTS.md` é o **manual operacional do agente** — relido toda sessão nova.

| Componente | Status |
|---|---|
| AGENTS.md customizado (Parte A — universal) | ✅ Escrito e ativo |
| AGENTS.md customizado (Parte B — Arbo) | ✅ Escrito e ativo |
| Treinamento sem restart de gateway | ✅ Confirmado (`/new` basta) |
| Custo de treinamento | ✅ Zero (só edição de markdown) |
| Template reutilizável para novos clientes | ✅ Parte A é genérica e transferível |

**Falhas críticas do Nível 3 resolvidas:**
- ✅ Política inventada → eliminada
- ✅ Citação fabricada → eliminada
- ✅ Ação falsa declarada → eliminada

Detalhes completos: [docs/TREINAMENTO_AGENTS_MD.md](TREINAMENTO_AGENTS_MD.md)

## PROBLEMAS CONHECIDOS A RESOLVER:

- ~~⚠️ **Alucinação funcional**~~ → ✅ Resolvido via AGENTS.md (Red Lines)
- ~~⚠️ **Citações fabricadas**~~ → ✅ Resolvido via AGENTS.md (Red Lines)
- ~~⚠️ **Ações sem integração declaradas como concluídas**~~ → ✅ Resolvido via AGENTS.md (Red Lines)
- ⚠️ **Sem integrações reais** — agente ainda não acessa sistemas da Arbo (agenda, banco, WhatsApp)

## TESTES DE INTEGRAÇÃO (EVOLUTION API):

- [x] ✅ **Max coloca o chip de teste no celular e conecta instância "amigao"**
- [x] ✅ **Primeiro WhatsApp real enviado** via comando `curl` local na Contabo (2026-06-26)

## PRÓXIMOS PASSOS:

- [ ] Configurar webhook na instância "amigao" para receber mensagens
- [ ] Configurar plugin webhooks do OpenClaw (rota evolution-inbound)
- [ ] Construir skill send-whatsapp no OpenClaw workspace
- [ ] Configurar secrets.json (cofre centralizado)
- [ ] Criar `references/politicas-arbo.md` como skill para dar base de conhecimento real ao agente
- [ ] Testar reusabilidade do AGENTS.md Parte A em cenário diferente (clínica, oficina)
- [ ] Aplicar blueprint MXOS em cliente real

---

## Estado dos arquivos de configuração

| Arquivo | Localização | Status |
|---|---|---|
| openclaw.json | `~/.openclaw/openclaw.json` | ✅ Ativo — fora do git |
| .env | `openclaw/.env` | ✅ Protegido pelo .gitignore |
| state/openclaw.sqlite | `~/.openclaw/state/` | ✅ Ativo — fora do git |
| Imagem Docker | `openclaw:local` (809MB, com Docker CLI) | ✅ Construída localmente |
| docker-compose.yml | `openclaw/docker-compose.yml` | ✅ docker.sock + GID 124 ativos |

---

## Nota de Arquitetura — Por que `openclaw/` não está no git do `meu-agente`

A pasta `openclaw/` é um clone do repositório upstream oficial (`github.com/openclaw/openclaw`),
com seu próprio `.git` interno.
Ela está no `.gitignore` intencionalmente para manter separação entre código de terceiros e o projeto pessoal.
As alterações feitas no `docker-compose.yml` ficam salvas localmente nesta pasta e **devem ser reaplicadas manualmente** caso a pasta seja deletada e reclonada.

**Exceção — as 4 extensões próprias têm backup real desde 2026-07-20:**
`ask-max`, `whatsapp-cloud`, `response-audit` e `github-repo-report` são
código nosso, não de terceiros, mas moram dentro de `openclaw/extensions/`
por exigência do Docker build (contexto = `openclaw/`). Git não permite
rastrear seletivamente uma subpasta de um repo aninhado a partir do repo
pai, e symlink pra fora quebraria o build da imagem. Solução: cópia de
exportação em `extensions/` (raiz do `meu-agente`, rastreada normalmente),
atualizada sob demanda via `scripts/sync-extensions-backup.sh`.
`openclaw/extensions/*` continua sendo a fonte de verdade em produção —
nada mudou no runtime. Detalhes: [SESSAO_2026-07-20.md](SESSAO_2026-07-20.md#pendência-fechada-backup-git-das-extensões-próprias).

### Alterações locais ao docker-compose.yml (não rastreadas pelo git):
```yaml
# Linhas 50-52 — descomentar sandbox:
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
group_add:
  - "124"
```
