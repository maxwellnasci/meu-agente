# Sessão 2026-08-04 — Checkpoint final e conclusão da Etapa 8

## Contexto
Migração Kali→Contabo validada em 02/08 22:56 UTC. Sessão de 03/08 com
credito do Claude esgotado: usado Antigravity (Gemini 3.6 Flash
thinking-high + Sonnet 4.6 think) pra investigar mensagens não chegando
no WhatsApp.

## O que o Antigravity/Gemini diagnosticou e corrigiu (03/08)
- Problema 1: duplo conector cloudflared (Contabo + Kali) causando
  round-robin e perda de mensagens. Correção: `systemctl disable --now
  cloudflared` no Kali.
- Problema 2: zero fallback de modelo (`deepseek/deepseek-chat` sem
  fallback), causando falha total em timeout. Correção: `openclaw.json`
  no Contabo -> primary `deepseek/deepseek-v4-flash`, fallback
  `["deepseek/deepseek-chat"]`, aplicado via edição direta + restart
  (config, não código - não precisou rebuild). Backup preservado em
  `/root/.openclaw/openclaw.json.bak-20260803-1934`.

## Checkpoint de verificação (04/08) — achados e resolução

Legenda de origem: **[Claude Code]** = rodado e verificado por mim nesta
sessão; **[Max, terminal direto]** = comando rodado por Max sozinho e
reportado na conversa, não executado por mim.

1. **[Claude Code]** Contradição de horário no relatório inicial do
   container Kali (erro de cópia do Claude Code, colei por engano dados
   do `docker ps` do Contabo sob o rótulo "Kali") - resolvido com
   reconfirmação limpa (`StartedAt` + `date -u` + `docker ps -a` na
   mesma chamada).
2. **[Max, terminal direto]** Gateway do Kali encontrado rodando - causa
   confirmada por Max: ligou o notebook nesse horário. **[Claude Code]**
   observação sobre os dados brutos: `uptime -s` = `2026-08-04 05:30:24`
   UTC (boot) vs `docker inspect StartedAt` = `2026-08-04T08:30:45` UTC
   (container) — gap bruto de ~3h. A reconciliação exata desse gap via
   fuso horário é **hipótese não verificada formalmente**: nunca rodamos
   `timedatectl` no Kali pra confirmar o fuso do sistema.
3. **[Claude Code]** Timestamp bruto do log: erro `sessions.patch ...
   missing scope: operator.admin` em produção às
   `2026-08-03T22:48:46 UTC` (única ocorrência em 48h). **[Max, terminal
   direto]** atribuição: confirmado por Max como tentativa do próprio
   Antigravity durante a sessão de diagnóstico, sem efeito — não
   verificado de forma independente por mim.
4. **[Claude Code]** Bind `0.0.0.0:18789-18790` no docker-compose do
   Kali, config desde 16/jul (`stat` confirmou mtime, sem mudança
   recente). Teste de porta via fallback `/dev/tcp` e socket Python a
   partir do Contabo contra o IPv6 informado: ambos retornaram
   fechada/filtrada (`errno 11`) — sem exposição ativa confirmada nesse
   teste específico. **[Max, terminal direto]** validação adicional via
   `ping6`/`timedatectl` do Contabo (saúde da saída IPv6, fuso horário)
   — não executada por mim. Corrigido por boa prática de qualquer forma
   (bind restrito a `127.0.0.1`, ver Ações executadas).
5. **[Max, terminal direto]** Timezone do Contabo reportado como
   Europe/Berlin (CEST), não UTC — não verificado por mim nesta sessão;
   todos os `date` que rodei usaram `-u` explícito.

## Ações executadas nesta sessão (04/08)

- **[Claude Code]** Etapa 8 concluída: `docker compose stop` no gateway
  do Kali (parado, não deletado, reversível — confirmado via `docker ps`
  / `docker ps -a`).
- **[Claude Code]** Confirmado: cloudflared do Kali inativo e
  desabilitado (`systemctl is-active`/`is-enabled`, checado antes e
  depois do stop).
- **[Max, terminal direto]** `models status` no Contabo com fallback
  ativo — não rodado nem confirmado por mim nesta sessão.
- **[Max, WhatsApp real + Claude Code, evidência direta]** Regressão ao
  vivo confirmada: Max mandou 6 mensagens reais e confirmou entrega
  recebida no WhatsApp. Grep de log por `agent_end`/`reply_payload_sending`
  veio vazio, mas por motivo trivial: esses são nomes de evento internos
  (`extensions/response-audit/src/plugin.ts:83`), nunca logados como
  texto — o path de sucesso só persiste em store, sem log nenhum
  (`api.logger.warn` só existe no path de falha). Consultei a store real
  (`plugin_state_entries`, namespace `amigao-audit`, SQLite em
  `/root/.openclaw/state/openclaw.sqlite`, via `python3 -c
  sqlite3...` read-only) e confirmei **4 registros de auditoria
  persistidos pro canal `whatsapp-cloud`**, com timestamps batendo com
  os replies reais (09:55:50 a 10:01:17 UTC) — cobertura do
  `response-audit` pro canal confirmada de forma direta, não por log.
  Um desses 4 casos veio `flagged: true, category: "hallucination"`
  (runId `c4a22831-5f4f-4437-a5d7-c7e34d474041`): Max perguntou o saldo
  de créditos, o Amigão rodou `session_status` e respondeu "Saldo atual
  da API (DeepSeek): US$ 5.82". O auditor julgou isso alucinação com o
  reason "session_status não retorna saldo/créditos de conta da API" —
  **esse reason está factualmente incorreto**. Investigação de código
  (`src/agents/tools/session-status-tool.ts` → `src/status/status-text.ts:448-509`
  → `src/infra/provider-usage.fetch.deepseek.ts:24-111`) confirmou que
  `session_status`, pra provedores não-OAuth-only como DeepSeek, faz uma
  chamada HTTP real e ao vivo pro endpoint oficial
  `GET https://api.deepseek.com/user/balance` e embute o saldo retornado
  no texto de status. Max confirmou que os US$ 5.82 batem com o saldo
  real checado direto na DeepSeek. **Conclusão: falso positivo do
  `response-audit`** (o modelo-juiz não tem visibilidade da chamada
  interna da tool) — não uma alucinação do Amigão. Detalhe completo e
  hipótese de melhoria futura registrados em `PROXIMOS_PASSOS.md`.
- **[Claude Code]** Fix de segurança: portas 18789/18790 do Kali
  restritas a `127.0.0.1` (commit `d1c658fd2d`, branch
  `production-local-fixes`).
- **[Claude Code]** Backup remoto criado:
  `github.com/maxwellnasci/max-openclaw-local-fixes` (branch
  `production-local-fixes`, histórico completo) - `origin` do repo
  `openclaw/` permanece intocado, apontando pro upstream público
  oficial.

## Estado atual da infraestrutura
Amigão rodando 24/7 no Contabo, gateway saudável. Kali mantido como
fallback de container parado (não deletado), cloudflared desabilitado.
Model: primary `deepseek/deepseek-v4-flash`, fallback
`deepseek/deepseek-chat` (reportado por Max, ver item "models status"
acima — não auditado por mim). Túnel público com 1 único conector ativo
(Contabo). `response-audit` confirmado cobrindo o canal `whatsapp-cloud`
via evidência direta na store (não só log); 1 falso positivo conhecido,
detalhado acima e em `PROXIMOS_PASSOS.md`.

## Lição de processo
Workflow validado: pensar (Claude, chat) -> Antigravity executa (Gemini
3.6 Flash high + Sonnet 4.6 think) -> Claude Code audita com evidência
real. Nenhuma correção do Antigravity precisou ser revertida hoje.

## Addendum — porta 18790 removida (Contabo + Kali, mesmo dia)

Achado pós-checkpoint: porta 18790 (OPENCLAW_BRIDGE_PORT) exposta em
0.0.0.0/[::] no Contabo - resíduo de feature "bridge" já removida do
OpenClaw (confirmado em docs/gateway/configuration-reference.md e
CHANGELOG.md do próprio upstream: zero listener real, não usada pelo
túnel Cloudflare). Bloqueio externo hoje dependia só de firewall de
borda do provedor, não de config própria - corrigido por completo.

- **Contabo (produção):** linha da porta removida direto no
  docker-compose.yml do host (`/root/openclaw/`, sem versionamento git
  nesse arquivo), backup em
  `docker-compose.yml.bak-20260804-1030-port18790fix`. Container
  recriado (`docker compose up -d`), confirmado healthy, porta 18790
  ausente de `docker ps`/`ss -tlnp`, WhatsApp confirmado respondendo
  pós-recriação (evidência de log real, 3 replies).
- **Kali (fallback parado):** mesma linha removida no
  docker-compose.yml versionado, commit `a7ad41b565`, branch
  `production-local-fixes`. Container seguiu parado - mudança vale pra
  próxima vez que subir.

## Addendum — limpeza de pendências (Kali + Contabo, mesmo dia)

- **.env.backup**: encontrado untracked no repo openclaw/ do Kali
  (23/06, credenciais reais confirmadas por padrão chave=valor, não
  inspecionado em detalhe por segurança). Protegido no .gitignore
  (commit 2e9b3004a8) e movido pra fora do repo:
  ~/backups/env.backup-kali-20260623, permissão 600. Backup antigo
  encontrado no mesmo diretório (openclaw-backup-20260729-065526.tar.gz)
  também teve permissão corrigida pra 600 (estava 644, legível por
  qualquer usuário local).
- **docs/ deletado no working tree**: achado mais amplo que o esperado -
  não só docs/.generated/ e docs/.i18n/ (32 arquivos), mas a árvore
  docs/ inteira do repo vendorizado (612 arquivos), sem relação com
  espaço em disco (284G livres) nem com nenhum script conhecido. Causa
  raiz não identificada - possivelmente ligada ao mesmo evento de
  23/06 do .env.backup (mesma janela temporal encontrada em outros
  arquivos de cache). Restaurado via git restore (zero risco, conteúdo
  já estava no histórico git).
- **cloudflared 2026.7.1 → 2026.7.3** (Contabo): sem breaking changes
  identificadas no changelog real (comparação de commits entre tags).
  SHA256 verificado antes de instalar, binário antigo e .deb mantidos
  em backup. Validado: prechecks PASS, 4 conexões QUIC reconectadas,
  mensagem real de WhatsApp respondida pós-update.

## Addendum — correção de pendência: timeout do deepseek

A pendência registrada em PROXIMOS_PASSOS.md ("timeouts ocasionais do
deepseek-v4-flash") tinha como base 3 menções na memória do projeto
que, investigadas a fundo via consulta direta à store de auditoria
(plugin_state_entries, 2026-07-18 a 2026-08-04, 53 registros), se
revelaram ser o próprio Amigão fabricando números específicos de
timeout numa resposta ao usuário (modelo citado nem batia com o
runtime) - corretamente flagrado como hallucination pelo response-audit
na hora (2026-08-03, 20 de 26 auditorias do dia flagged). Não é
evidência de problema real de infraestrutura naquele horário.

Achado real e independente, sem relação com a alucinação: não havia
NENHUM timeout de aplicação configurado para as chamadas de chat do
deepseek (só o hook de auditoria tinha, 20s hardcoded) - dependia só
do comportamento de socket TCP/TLS. Corrigido: adicionado
models.providers.deepseek.timeoutSeconds: 30 no openclaw.json do
Contabo (backup em openclaw.json.bak-20260805-0005-timeoutfix),
runtime-only, sem rebuild. Validado: gateway healthy pós-restart,
mensagem real de WhatsApp processada sem erro.

Investigação read-only separada: update do OpenClaw (v2026.6.9 →
v2026.7.1-2) foi mapeado em detalhe (4.716 commits, 2 conflitos reais
de merge identificados na branch production-local-fixes - um deles em
src/plugins/hooks.ts, relacionado à mesma Bug 4 já corrigida
localmente, resolvida de forma independente pelo upstream também) mas
NÃO aplicado - risco/escopo grande demais pra sessão atual, requer
ambiente de staging dedicado. Plano de rebase já levantado, fica como
próximo passo definido.
