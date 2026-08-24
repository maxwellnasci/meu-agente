# Estado Atual do Projeto

## ✅ MARCO — Orquestrador Python (LangGraph): revisão completa + hardening de segurança (2026-08-24)

**Novo objetivo do projeto, definido nesta sessão**: o Orquestrador deixa
de ser só um esqueleto e vira a base de um **portfólio replicável** de
agentes de IA (enxame Supervisor + Especialistas) para uso com empresas.
Ritmo de trabalho combinado: incremental — analisar, melhorar, testar via
WhatsApp pedindo tarefas reais aos agentes, documentar, repetir.

- **Contexto**: em 2026-08-22 o Max usou o Antigravity (Gemini) pra
  destravar a integração Orquestrador↔Gateway↔n8n direto no Contabo (rede
  Docker, bind mount do sandbox, crash-loop de config). Funcionou —
  confirmado via log real (`[whatsapp-cloud] WhatsApp Cloud reply started`
  às 2026-08-22 11:22 UTC) — e ficou documentado em
  `/root/meu-agente-orchestrator/DOCUMENTACAO_ARQUITETURA_E_ERROS.md`
  **no servidor** (ainda não trazido pro repo — pendência aberta, ver
  Próximos Passos).
- **Revisão de código feita nesta sessão** (leitura de todo
  `orchestrator/src/`, testes rodados, config de sandbox do Contabo
  auditada): arquitetura é sólida — supervisor/enxame via LangGraph, trava
  de loop infinito, fallback sempre responde 200 pro WhatsApp, defesa em
  profundidade real no especialista cybersec (bloqueio em Python puro,
  independente do LLM respeitar o prompt). `dangerouslyAllowExternalBindSources`
  aplicado pelo Antigravity no `openclaw.json` do Contabo foi auditado:
  escopo correto (só agente `cybersec`, bind **read-only**, só
  `/opt/claude-skills`, sem segredo exposto).
- **Gap de segurança encontrado e corrigido**: o especialista **n8n**
  (mexe numa instância real de produção — criar/editar/**deletar**/
  ativar/desativar workflows) só tinha proteção via prompt ("REGRA DE
  CAUTELA"), sem bloqueio em código — diferente do cybersec. Criado
  `orchestrator/src/orchestrator/graph/n8n_guard.py`: mesma filosofia do
  `cybersec_guard.py`, bloqueia incondicionalmente `N8nDeleteWorkflow`/
  `N8nDeactivateWorkflow` se a instrução da tarefa não contiver um verbo
  de autorização explícito. Também fechado o fix que já estava pendente
  de sessão anterior: `cybersec_guard` agora cobre mais marcadores de
  negação e checa tanto a mensagem original do usuário quanto as
  instruções repassadas pelo supervisor (defesa multi-turn), evitando a
  janela de bypass por eco/prompt injection.
- **Validado**: 27/27 testes (local + novos), build da imagem Docker no
  Contabo, gates testados de verdade dentro do container recém-deployado
  (bloqueiam produção sem autorização, liberam com autorização explícita).
  Commit local `0ceb8d9` (push pro GitHub ainda pendente de confirmação),
  commit espelho no repo do Contabo `340bed7`.
- **Gaps identificados, ainda não corrigidos** (próximos passos):
  1. Doc do Antigravity (`DOCUMENTACAO_ARQUITETURA_E_ERROS.md`) trazer do
     Contabo pro `docs/` do repo.
  2. Deploy do orchestrator pro Contabo é manual, repo lá **sem remote
     git configurado** — não é repetível/versionado de verdade. Considerar
     apontar um remote real (GitHub) ou script de deploy.
  3. `test_api.py` (raiz do repo) tem um **token Bearer hardcoded** —
     remover/mover pra fora do git antes de commitar qualquer coisa dali.
  4. `orchestrator/response.json` é resíduo de teste manual, sem uso —
     candidato a remoção.

---

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
- **Canal ativo:** whatsapp-cloud (extensão customizada). O canal oficial é **exclusivamente** a WhatsApp Cloud API.
- **Baileys/Evolution/Chatwoot:** Desativados e removidos fisicamente do servidor Contabo (RAM recuperada).
- **Túnel público:** Cloudflare Tunnel (whatsapp.mxos.com.br → localhost:18789), serviço systemd permanente, reconexão automática. **Conector ativo: Contabo** (desde 2026-08-02 22:51 UTC; antes era o Kali). Portas 18789/18790 do Kali restritas a `127.0.0.1` desde 2026-08-04 (config antiga expunha em `0.0.0.0`, sem exploração confirmada). Porta 18790 (bridge legacy, sem uso) removida por completo do docker-compose tanto no Contabo (produção, host) quanto no Kali (fallback) em 2026-08-04
- Docker socket removido do container do gateway (Contabo) em
  2026-08-04 - fechava rota RCE→root. Secrets DEEPSEEK_API_KEY e
  OPENCLAW_GATEWAY_TOKEN migrados de env cru pra SecretRef em arquivo
  (modo 600). **Docker socket religado em 2026-08-05 (P0.2, sandbox
  real) — desta vez com isolamento de verdade**: `sandbox.mode: "all"`,
  `docker.sock` montado só no `openclaw-gateway` (não no `openclaw-cli`),
  `group_add: "988"` (GID real do Contabo), `memory: "512m"` +
  `pidsLimit: 256` no `sandbox.docker`. Validado ao vivo: execução real
  de tool via WhatsApp confirmada rodando dentro de um container
  `openclaw-sbx-agent-main-*` efêmero, não direto no gateway. Rotação
  de chaves ainda pendente - ver PROXIMOS_PASSOS.md. Detalhes completos
  em [SESSAO_2026-08-05.md](SESSAO_2026-08-05.md).
- **Backup do repo local (`openclaw/`):** espelho privado em `github.com/maxwellnasci/max-openclaw-local-fixes` (branch `production-local-fixes`) desde 2026-08-04 — `origin` do clone segue intocado, apontando pro upstream público
- **Nova direção:** fork evolutivo do OpenClaw com 2º agente de segurança
- **Próximos passos:** P0.2 (sandbox real) concluído (2026-08-05), regressão do tool-policy (ask_max/github_repo_report bloqueados pelo sandbox) encontrada e corrigida (2026-08-06), github-repo-report migrado pra config-driven e deployado em produção (2026-08-06), heurística de prioridade pra `false_action` deployada e validada em produção (2026-08-10) — próximo: itens 3-5 do roteiro de template (AGENTS.md Parte B, setup de infra por cliente, core vs. add-on), rotação de chaves, avaliar Claude Security pós-migração; investigar timeouts residuais do deepseek-v4-flash e falso positivo do response-audit (saldo DeepSeek, ver PROXIMOS_PASSOS.md)
- **Data da última atualização:** 2026-08-10

---

## ✅ MARCO — heurística de prioridade para `false_action` deployada e validada em produção (2026-08-10)

- **Objetivo**: implementar a recomendação em aberto do Adendo 3 do teste
  local híbrido (`test/local-hybrid-audit`, commit `bb95eac`) — regra
  heurística zero-custo (`declared_action_text` + zero ferramentas
  executadas no turno) pra priorizar suspeita de `false_action` sem chamar
  modelo algum.
- **Desenho**: `HeuristicDecision` ganha `highSuspicionFalseAction`. É
  **sinal de prioridade pro prompt do juiz LLM, nunca veredito** — o Adendo
  3 cogitou a mesma condição como flag direta sem modelo; a implementação
  real optou pelo caminho mais cauteloso, decisão final sempre do LLM. 15
  testes unitários (2 arquivos), 100% verde.
- **Build e transferência**: `openclaw:local-sandboxed-v3`,
  `sha256:17410e1c22b8...`, 880MB. Transferido via `docker save | gzip |
  ssh | gunzip | docker load` (~1min24s). Mesma divergência de Image
  ID/tamanho entre Kali e Contabo já vista em 2026-08-06 (versões de Docker
  diferentes), conteúdo confirmado idêntico via `grep -c` da string-chave
  no bundle, dos dois lados.
- **Validação nível 1** (regressão): mensagem comum não gera registro de
  auditoria — comportamento esperado (heurística só audita com gatilho),
  zero erro.
- **Validação nível 2 — o achado real**: mensagem de teste tentou induzir o
  agente a confirmar um envio que não aconteceu (injeção de prompt). O
  agente **recusou e negou a ação** (texto exato no doc da sessão). Isso
  disparou `highSuspicionFalseAction: true` (confirmado pela matemática do
  código: verbo de ação declarada presente + zero ferramentas), injetando o
  sinal no prompt do juiz — que corretamente retornou `flagged: false`,
  identificando a negação. **Prova ao vivo de por que o desenho "sinal de
  prioridade, nunca bypass" foi a escolha certa**: se a regra tivesse sido
  implementada como veredito direto (como o Adendo 3 cogitou), esse turno
  — o comportamento mais correto possível do agente — teria sido marcado
  como falso positivo de `false_action`.
- **Backup**: `.env.bak-20260810-1050-false-action-heuristic-deploy`.
  Rollback documentado, não usado (imagem v2 intocada). Detalhes completos:
  [SESSAO_2026-08-10_false-action-heuristic-deploy.md](SESSAO_2026-08-10_false-action-heuristic-deploy.md).

---

## ✅ MARCO — github-repo-report migrado para config-driven, deploy validado em produção (2026-08-06)

- **Objetivo**: item 2 do "Roteiro: extrair template genérico" —
  `repo-registry.ts` tinha owner/slugs hardcoded em TypeScript, exigia
  editar código-fonte (e rebuild de imagem) pra reusar em outro
  cliente. Movido pra config carregável via `openclaw.json`, sem
  regressão de comportamento.
- **Refactor**: `configSchema` novo no `openclaw.plugin.json`
  (`owner` + `repos[]`); `src/config.ts` novo (parse `zod`, mesmo
  padrão de `extensions/webhooks`); `repo-registry.ts` virou builders
  genéricos; `schema.ts` virou função (enum construído em runtime a
  partir do config); `tool.ts`/`policy.ts` recebem o registry como
  parâmetro; `plugin.ts` decide **não registrar a tool** se zero repos
  configurados (safe-by-default — enum vazio degradaria pra string
  livre sem essa checagem). 36 testes, 9 arquivos, 100% verde.
- **Achado sem relação com o refactor**: falha do `pnpm build:docker`
  local (`ERR_NO_TYPESCRIPT` no script do plugin `canvas`) confirmada
  como ambiente do host (Node do Kali), não bug — o build Docker real
  rodou esse mesmo passo limpo dentro do container oficial.
- **Achado crítico pré-deploy**: `openclaw.json` de produção tinha
  `github-repo-report: { enabled: true }` **sem bloco `config`** — com
  o código novo isso desregistraria a tool silenciosamente (zero
  erro/crash, só um log INFO). Resolvido antes do corte: config
  equivalente adicionado (owner `maxwellnasci`, `meu-agente`/`arbo`
  desabilitados, `Mox---Sistemas` habilitado), replicando exatamente o
  comportamento hardcoded anterior.
- **Build e transferência**: `docker build
  --build-arg OPENCLAW_INSTALL_DOCKER_CLI=1 -t
  openclaw:local-sandboxed-v2 .` — limpo, `sha256:0cc028678cfe...`,
  880MB. Transferido via `docker save | gzip | ssh | gunzip | docker
  load`. Divergência de Image ID entre Kali e Contabo investigada e
  explicada (versões de Docker diferentes) — conteúdo confirmado
  idêntico via `sha256sum` dos arquivos compilados, não só pelo ID.
- **Validação ao vivo**: mensagem real via WhatsApp ("me dá um
  relatório do repositório Mox") retornou relatório real e detalhado
  do repo (URL de produção, stack, contagem de arquivos) — confirma a
  tool registrada e executando de verdade com o config novo, não só o
  container subindo saudável.
- **Backups**:
  `openclaw.json.bak-20260806-1339-github-repo-report-config`,
  `.env.bak-20260806-1341-github-repo-report-deploy`. Rollback em 2
  passos independentes, documentado e não usado (imagem antiga
  `openclaw:local-sandboxed` nunca foi tocada). Detalhes completos:
  [SESSAO_2026-08-06_github-repo-report.md](SESSAO_2026-08-06_github-repo-report.md).

**Referência rápida de rollback:**
```bash
# 1. Reverter a imagem (via .env + recriação):
ssh contabo "cd /root/openclaw && sed -i 's/OPENCLAW_IMAGE=openclaw:local-sandboxed-v2\$/OPENCLAW_IMAGE=openclaw:local-sandboxed/' .env && docker compose up -d"

# 2. Reverter o config (openclaw.json, comportamento hardcoded antigo volta):
ssh contabo "cp /root/.openclaw/openclaw.json /root/.openclaw/openclaw.json.pre-rollback && cp /root/.openclaw/openclaw.json.bak-20260806-1339-github-repo-report-config /root/.openclaw/openclaw.json && docker compose up -d"
```

---

## ✅ MARCO — P0.2 concluído: sandbox real ativo em produção (2026-08-05)

- **Objetivo**: religar o isolamento por container removido em 2026-08-04
  (P0.1), desta vez com sandbox de verdade em vez de acesso irrestrito ao
  `docker.sock`.
- **Build**: imagem do gateway reconstruída no Kali com
  `--build-arg OPENCLAW_INSTALL_DOCKER_CLI=1` (tag
  `openclaw:local-sandboxed`, Docker CLI + compose-plugin instalados via
  repo APT oficial com verificação de fingerprint GPG). Imagem separada
  `openclaw-sandbox:bookworm-slim` (usada pelos containers-filho
  `openclaw-sbx-*`) rebuilded — cache hit, confirmando que já estava em
  dia com o Dockerfile. Ambas transferidas pro Contabo via
  `docker save | ssh | docker load` (mesmo método usado na migração
  original de 2026-07-29), evitando manter um checkout de código-fonte
  em produção (o Dockerfile só existe no Kali; o `/root/openclaw` do
  Contabo nunca teve um, um gap descoberto durante a investigação).
- **Config**: `openclaw.json` → `sandbox.mode: "all"` (era `"off"`),
  `docker.memory: "512m"` + `docker.pidsLimit: 256` (`pidsLimit` bate
  com o exemplo oficial do upstream em `docs/gateway/config-agents.md`;
  `memory` é metade do exemplo de referência, ponto de partida
  conservador). `docker-compose.yml` → `docker.sock` remontado só no
  `openclaw-gateway` (não no `openclaw-cli`) + `group_add: "988"` (GID
  real do grupo `docker` no Contabo — diferente do 124 usado no Kali,
  confirmado antes de aplicar). `.env` → `OPENCLAW_IMAGE=openclaw:local-sandboxed`
  (mantém `openclaw:local` intocada como rollback instantâneo).
- **Validação ao vivo**: `docker exec ... docker --version` funcional
  (29.7.1); `id` do processo do gateway confirma grupo 988; uma
  mensagem de teste real via WhatsApp gerou um container
  `openclaw-sbx-agent-main-*` de verdade (`sleep infinity`, `scope:
  "agent"` como esperado), com os logs do gateway confirmando a tool
  policy do sandbox sendo aplicada (`tools.allow`/`tools.deny`
  filtrando tools) — isolamento real em uso, não só o container
  subindo à toa.
- **Incidente sem impacto residual**: um `chown root:root` equivocado
  no `openclaw.json` (o backup só parecia `root:root` porque o `cp` sem
  `-p` não preserva o dono original — o arquivo de produção real
  precisa de uid 1000/`node`) causou um crash loop de ~4min (`EACCES`,
  exit 78) até ser diagnosticado pela própria mensagem de erro do
  OpenClaw e corrigido.
- Backups dos 3 arquivos (`docker-compose.yml`, `.env`, `openclaw.json`)
  tirados no Contabo antes de qualquer mudança real
  (`*-20260805-1048-sandboxfix`), prontos pra rollback. Detalhes
  completos: [SESSAO_2026-08-05.md](SESSAO_2026-08-05.md).
- **Validação final (2026-08-06)**: execução real da tool `exec`
  dentro do container sandbox confirmada com evidência direta (docker
  logs do gateway + docker events do container + resposta funcional
  sem grupo 988 do host) — fecha a ressalva anterior sobre execução
  não comprovada diretamente. **Os 3 itens P0 do plano de segurança do
  Amigão (docker.sock/RCE, sandbox real, secrets fora do env) estão
  todos corrigidos e validados com evidência real.** Detalhes:
  [SESSAO_2026-08-05.md](SESSAO_2026-08-05.md#validação-final-do-p02--sandbox-real-confirmado).
- **⚠️→✅ Regressão encontrada e corrigida (2026-08-06)**: ligar
  `sandbox.mode: "all"` fez a política de tools do sandbox cair no
  `DEFAULT_TOOL_ALLOW` (allowlist default do OpenClaw), que bloqueava
  `ask_max` (rede de segurança contra alucinação) e
  `github_repo_report` desde a ativação do P0.2, sem ninguém perceber
  até uma investigação de inventário de capacidades. Causa raiz: faltava
  `tools.sandbox.tools.alsoAllow` (campo distinto do `tools.alsoAllow`
  de raiz, que só expõe a tool ao modelo — não à política do sandbox).
  Corrigido no `openclaw.json` do Contabo (backup
  `openclaw.json.bak-20260806-0041-toolpolicyfix`), validado ao vivo
  (log caiu de 14 → 12 tools removidas por turno, isolamento do
  `exec`/Docker intocado). Detalhes:
  [SESSAO_2026-08-05.md](SESSAO_2026-08-05.md#regressão-encontrada-e-corrigida-ask_maxgithub_repo_report-bloqueados-pelo-sandbox).

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

## TESTES DE INTEGRAÇÃO (EVOLUTION API) - DESCONTINUADO:

- [x] ❌ (Desativado) Max coloca o chip de teste no celular e conecta instância "amigao"
- [x] ❌ (Desativado) Primeiro WhatsApp real enviado via comando `curl` local na Contabo (2026-06-26)
- **Status:** Serviços removidos do servidor; substituídos pela WhatsApp Cloud API oficial.

## PRÓXIMOS PASSOS:

- [ ] Configurar secrets.json (cofre centralizado)
- [ ] Criar `references/politicas-arbo.md` como skill para dar base de conhecimento real ao agente
- [ ] Construir skill send-whatsapp-cloud no OpenClaw workspace (se necessário enviar ativamente)
- [ ] Testar reusabilidade do AGENTS.md Parte A em cenário diferente (clínica, oficina)
- [ ] Aplicar blueprint MXOS em cliente real

---

## Estado dos arquivos de configuração

Tabela abaixo descreve o ambiente **Kali (dev local/fallback)**. A
**produção real roda no Contabo** desde 2026-08-02 e diverge em dois
pontos desde 2026-08-05 (P0.2): imagem `openclaw:local-sandboxed` (não
`openclaw:local`) e `group_add` com GID **988** (não 124 — GID do grupo
`docker` diverge entre as duas máquinas). Detalhes:
[SESSAO_2026-08-05.md](SESSAO_2026-08-05.md).

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
