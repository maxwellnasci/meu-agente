# Próximos Passos (Roadmap)

## FASE ATUAL: Segurança antes de expandir

O agente está vivo (`deepseek/deepseek-chat`, v2026.6.9) mas rodando **sem sandbox**.
Antes de qualquer nova feature, religar o isolamento é o passo zero.

### Prioridade 🔴 URGENTE

- [x] **Configurar docker.sock no compose:** (Feito)
- [x] **Religar sandbox:** (Feito)
- [x] **Validar isolamento:** ✅ Concluído em 2026-08-05 (ver P0.2 abaixo)

### Prioridade 🟡 PRÓXIMA FASE

- [x] **Migrar para DeepSeek V4-flash:** (Aprendizado resolvido: não é necessário litellm, o V4-flash e V4-pro estão disponíveis nativamente na interface web após o `doctor --fix`)
- [ ] **Corrigir allowedOrigins permanentemente:** o gateway está fazendo seed automático a cada restart. Adicionar `gateway.controlUi.allowedOrigins: ["http://localhost:18789", "http://127.0.0.1:18789"]` no openclaw.json para tornar permanente
- [ ] **Silenciar aviso de memória semântica:** desabilitar `agents.defaults.memorySearch.enabled` ou configurar uma chave OpenAI

### Prioridade 🟢 EXPLORAÇÃO

- [ ] Conceder acesso de **leitura** a uma pasta segura e validar que o agente lê sem ultrapassar o limite
- [ ] Conceder acesso de **escrita** a uma pasta designada e validar que o agente não sai do escopo
- [ ] Habilitar skills básicas (pesquisa web, leitura de arquivos) e observar comportamento
- [ ] Documentar padrões de uso seguro para o projeto **MXOS**
- [ ] Análise de segurança do servidor com Claude Code
- [ ] Aplicar 33 updates + reboot controlado

### Prioridade 🔴 FASE ANTI-ALUCINAÇÃO (nova — identificada no Nível 3)

- [ ] **Implementar Supervisor (LLM as a Judge):** camada que valida a resposta do agente antes do envio ao usuário, bloqueando citações fabricadas, dados inventados e ações falsamente declaradas como concluídas
- [ ] **Separar na arquitetura:** "o que o agente faz agora" vs "o que precisa de integração" — deixar explícito para o cliente o que é capacidade atual vs roadmap
- [ ] **Prompt engineering anti-alucinação:** instruir o agente a afirmar apenas o que sabe (dados fornecidos), nunca inventar políticas ou atribuir frases a pessoas reais

### Prioridade 🟡 INTEGRAÇÕES REAIS (viabiliza EXECUÇÃO, não só análise)

- [x] **Evolution API** — Conectar instância, enviar mensagem de teste via curl local (Validado)
- [x] **WhatsApp Cloud API oficial (Meta)** — Webhook recebendo, Amigão respondendo ponta a ponta com memória de sessão. Substitui Evolution/Baileys como canal principal (2026-07-14, ver [SESSAO_2026-07-14.md](SESSAO_2026-07-14.md))
- [ ] **Verificação do app WhatsApp Cloud pra produção** — remove restrição de allowlist de destinatários (hoje limitado a 5 números cadastrados manualmente)
- [x] **Migrar Amigão pro servidor Contabo** — ✅ **praticamente
  concluída em 2026-08-02** (Etapas 0-7 feitas, cutover do túnel
  confirmado, falta só a Etapa 8 de limpeza no Kali — ver checklist
  detalhado acima). Já não depende mais do Kali estar ligado.
  **Motivação original, reforçada por incidente real em 2026-07-18**:
  notebook desligado (uso normal, não bug) das 08:25 às 17:19 (`-03`,
  ~8h55min) deixou o gateway — e o `response-audit` recém-conectado —
  fora do ar o dia inteiro sem ninguém perceber até o usuário voltar e
  pedir um resumo. Container voltou sozinho graças a
  `restart: unless-stopped` + `docker.service` habilitado no boot, mas
  só porque a máquina foi religada; não teria voltado sozinha se
  tivesse ficado desligada. Detalhes da investigação em
  [SESSAO_2026-07-18.md](SESSAO_2026-07-18.md#verificação-pós-deploy-tarde-e-descoberta-gap-de-9h-em-produção).
- [ ] **Revisar AGENTS.md para foco claro do bot** — política da Meta desde jan/2026 proíbe "General Purpose AI" sem foco específico (risco de suspensão do WhatsApp Cloud API)
- [ ] **Skill send-whatsapp** — Construir e habilitar no OpenClaw workspace
- [ ] **Secrets.json (cofre)** — Configurar cofre centralizado para gerenciar a apikey da Evolution
- [ ] **WhatsApp Business API** — notificação real ao Coach/responsável quando aluno reporta lesão ou situação urgente
- [ ] **Supabase (banco de dados)** — persistir políticas de reposição, histórico de lesões, planos de alunos — o agente consulta dados reais em vez de inventar
- [ ] **n8n como orquestrador** — conectar eventos do agente a ações no mundo real (cancelar check-in, criar lembrete, registrar ocorrência)

## VISÃO FINAL

Aplicar esse aprendizado e arcabouço tecnológico sólido no projeto **MXOS**, focando no desenvolvimento e oferta de funcionários digitais (agentes autônomos de IA) voltados para clientes e PMEs com governança, segurança e alta qualidade técnica.

---

*Atualizado em 2026-07-05. O passo de segurança é a porta de entrada para tudo que vem depois.*

## Pendência: nginx-app-1 não sobe automaticamente após reboot

### Problema
nginx-app-1 (Nginx Proxy Manager) não sobe automaticamente
após reboot do servidor. Causa: race condition com 
chatwoot-rails-1 (ambos usam porta 3000 internamente 
durante inicialização).

### Solução planejada
Adicionar "depends_on" no docker-compose do nginx-app-1:

depends_on:
  - chatwoot-rails-1

Isso força nginx-app-1 esperar Chatwoot subir primeiro.

### Como fazer (quando tiver tempo)
1. Descobrir localização do docker-compose do nginx-app-1:
   docker inspect nginx-app-1 | grep -i compose
   
2. Editar o arquivo e adicionar depends_on

3. Recriar container:
   docker compose up -d --force-recreate nginx-app-1

4. Testar com reboot real

### Workaround atual (funciona bem)
Após qualquer reboot:
   docker start nginx-app-1

### Prioridade
Baixa — só incomoda após reboot (raro).
Não afeta operação normal do servidor.

---

## Próxima exploração: Amigão + análise de código

- [x] **Item 1 — Amigão analisando projetos GitHub do Max:** ✅ **Concluído
  em 2026-07-17.** Tool `github_repo_report` implementada, só leitura (nunca
  PR/escrita no repo), escopo fechado a um enum de repos habilitados
  explicitamente (`Mox---Sistemas` habilitado; `meu-agente` e `arbo`
  presentes no enum mas desabilitados até validação individual). Passou por
  uma investigação de 3 dias (Bug 4 — travamento do SQLite, bug de policy
  de aprovação, bug de configuração de exposição ao modelo), todos
  corrigidos e confirmados ao vivo. Case completo:
  [docs/CASE_BUG4_INVESTIGACAO_COMPLETA.md](CASE_BUG4_INVESTIGACAO_COMPLETA.md).
  Conectada em produção, funcionando de ponta a ponta.

- [x] **"Fase 1" (`response-audit`, auditor pós-resposta):** ✅ concluído em
  2026-07-18, ver [SESSAO_2026-07-18.md](SESSAO_2026-07-18.md). Validado ao
  vivo em produção duas vezes de forma não-planejada durante o teste do
  `ask-max` (flagrou `false_action` real duas vezes).
- [x] **`ask-max` (escalonamento humano, "Passo 2"):** ✅ concluído em
  2026-07-18, ver
  [SESSAO_2026-07-18.md](SESSAO_2026-07-18.md#retomada-final--rebuild-redeploy-e-teste-ao-vivo-completo-3-pernas-fechadas).
  Bug real encontrado e corrigido (`senderIsOwner`/`commands.ownerAllowFrom`
  não reconhecia o operador numa resposta comum — trocado por comparação
  direta contra o `to` já configurado no plugin). Rebuild + redeploy real
  feitos, fix confirmado no bytecode em produção. Teste ao vivo do zero
  (webhook simulado + resposta real do Max pelo WhatsApp) confirmou as 3
  pernas fechando de ponta a ponta: pergunta escalada, resposta roteada de
  volta pro chat original, ack recebido.
- [x] **Lacuna `response-audit` + `ask_max`:** investigado em 2026-07-18 e
  2026-07-19, ver
  [SESSAO_2026-07-18.md](SESSAO_2026-07-18.md#investigação-da-lacuna-do-response-audit-no-turno-do-ask_max)
  e [SESSAO_2026-07-19.md](SESSAO_2026-07-19.md). Com logs de debug nos 4
  pontos de captura, **não reproduzida** em 1 teste normal + 1 rajada de 5
  mensagens concorrentes (mesma técnica do Bug 4). Rebaixada a prioridade
  baixíssima — 3 tentativas sem reprodução sugere raridade real, não
  afeta uso normal single-user de hoje. Anomalia secundária observada,
  não investigada: um turno multi-round com `ask_max` (texto+toolCall →
  toolResult → segunda resposta final) não gerou
  `reply_payload_sending`/auditoria, diferente de um turno de rodada
  única que capturou certinho — pode ser artefato do estado recém
  recuperado do bug abaixo, ou uma lacuna real em turnos multi-round;
  fica pra investigar se reaparecer.
- [ ] 🔴 **BLOQUEANTE pra multi-usuário — bug novo (achado como efeito
  colateral, 2026-07-19): sessão trava ~6min por mensagem na fila atrás
  de um turno já terminado.** Prioridade **mais alta** que a lacuna do
  `response-audit` acima (essa foi rebaixada a baixíssima prioridade
  depois de 3 tentativas sem reprodução; esta aqui é reproduzida e tem
  causa raiz confirmada). Diagnóstico completo + investigação (só
  leitura) + plano de correção em
  [SESSAO_2026-07-19.md](SESSAO_2026-07-19.md#bug-novo-encontrado-fila-de-mensagens-da-mesma-sessão-trava-por-6-minutos)
  (achado inicial) e
  [SESSAO_2026-07-19.md](SESSAO_2026-07-19.md#investigação-só-leitura-do-bug-de-fila-travada--causa-raiz-precisa-e-plano-de-correção)
  (causa raiz + recomendação). Causa raiz precisa (não suposição): o
  `ReplyOperation` de nível alto (`src/auto-reply/reply/reply-run-registry.ts`)
  nunca chama `.complete()` em pelo menos 2 formatos de turno confirmados
  (bloqueado pelo `ask-max`; normal multi-round com tool call), deixando
  `replyRunState.activeRunsByKey` preso e bloqueando `waitForIdle` das
  mensagens seguintes indefinidamente (sem timeout pra turnos "visible").
  Confirmado que a cautela do health-monitor rápido
  (`classifySessionAttention`, `recoveryEligible: false`) é design
  deliberado de segurança (evita abortar um turno genuinamente ativo),
  não lacuna — não deve ser enfraquecida.
  **Por que é bloqueante**: `dmScope` (`src/routing/session-key.ts`) está
  no padrão `"main"` — toda conversa DM, de qualquer remetente, cai na
  mesma `sessionKey` (`agent:main:main`). Hoje não aparece porque só o
  número do Max está na allowlist (trava de tempo, não solução) — assim
  que o Amigão abrir pra mais gente de verdade (Arbo em agosto, ou
  qualquer outro cliente), 2+ pessoas reais mandando mensagem quase ao
  mesmo tempo vão travar uma na outra do mesmo jeito, sem aviso nenhum
  pro usuário final.

  **Plano de correção em 2 etapas, decidido em 2026-07-19:**
  1. [x] 🟢 **Fácil, fazer logo — ✅ APLICADO em 2026-07-19.** Mitigação de
     config, baixo risco, reversível: `session.dmScope: "per-peer"`
     aplicado em `~/.openclaw/openclaw.json` (só restart, sem rebuild).
     Validado ao vivo: regressão do fluxo normal do WhatsApp OK
     (`sessionKey` agora `agent:main:direct:<número>`, não mais
     `agent:main:main`), e teste de concorrência com 2 números diferentes
     confirmou processamento **em paralelo, sem qualquer travamento**
     (ambos recebidos e respondidos em ~2.5s, mesma janela de tempo). Ver
     [SESSAO_2026-07-19.md](SESSAO_2026-07-19.md#etapa-1-do-plano-aplicada-sessiondmscope-per-peer).
     **Isola o raio de explosão por contato — não corrige o bug em si**:
     o mesmo número mandando 2 mensagens rápidas em sequência ainda trava
     ~6min pra ele mesmo (esperado, não testado de novo nesta etapa pois
     já confirmado na investigação anterior).
  2. [x] ✅ **Causa raiz encontrada e CORRIGIDA (2026-07-19/20, 4 rodadas
     de instrumentação ao vivo + Opção A implementada e validada).** Não
     era `.complete()` pulado (hipótese anterior
     descartada por leitura exaustiva de código). É um **deadlock real
     do core do OpenClaw**: `foregroundReplyFenceByKey` em
     `src/auto-reply/dispatch.ts` cria uma "geração" de entrega
     (`beginForegroundReplyFence`) *antes* da sessão admitir o turno pra
     rodar de verdade; o turno mais antigo, já rodando, espera
     (`shouldCancelForegroundReplyDelivery`, `while(true)` sem timeout)
     por uma geração mais nova que não consegue nem começar, porque a
     fila da sessão só roda um turno por vez. Detalhe completo (as 4
     rodadas + prova ao vivo com números de geração reais) em
     [SESSAO_2026-07-19.md](SESSAO_2026-07-19.md#etapa-2-do-plano-causa-raiz-real-do-travamento--achada-com-prova-ao-vivo-em-4-rodadas-de-instrumentação-mesma-sessão-continuação).
     **Bug conhecido upstream**: `openclaw/openclaw#91914` (aberta,
     P1, thread canônica), com correção proposta em
     `openclaw/openclaw#91963` ("defer foreground fence until
     delivery") — tecnicamente validada pelo autor, mas **nunca
     mergeada** (parada, sem mantenedor ativo). Não dá pra esperar
     fix upstream a curto prazo.
     **Correção aplicada (Opção A, mais segura — não mexe em core)**:
     serialização por remetente dentro do nosso próprio
     `extensions/whatsapp-cloud/src/webhook.ts` (antes disparava
     `void dispatchWhatsAppCloudInboundEvent(...)` sem fila nenhuma) —
     mesmo padrão que resolveu (parcialmente) o bug gêmeo no plugin
     WeCom upstream (`openclaw/openclaw#95758`). Implementada, com 6
     testes novos (22/22 passando), validada ao vivo pós-redeploy: a
     mesma rajada de 4 mensagens que antes travava ~370s+ por mensagem
     agora processa as 4, com respostas reais e distintas, em ~22s no
     total — confirmado no transcript real da sessão, zero
     `stalled`/`stuck` nos logs. Detalhe completo em
     [SESSAO_2026-07-19.md](SESSAO_2026-07-19.md#correção-aplicada-opção-a--serialização-por-remetente-no-nosso-próprio-webhook-sem-tocar-em-código-core).
     Opção mais completa mas mais arriscada (patch de core adaptado da
     PR #91963) fica registrada como possibilidade futura, só se
     precisarmos proteger outro canal além do WhatsApp. Não mexer no
     limiar de 5min do health-monitor rápido — a cautela ali continua
     correta e é assunto separado.

- [x] ✅ **Backup git das 4 extensões próprias — CONCLUÍDO em 2026-07-20.**
  `ask-max`, `whatsapp-cloud`, `response-audit`, `github-repo-report`
  viviam só dentro de `openclaw/extensions/` (repo de terceiros, ignorado
  inteiro pelo `.gitignore`) sem backup real. Solução: cópia de
  exportação em `extensions/` na raiz do `meu-agente` (symlink descartado
  — quebraria o build Docker, cujo contexto é `openclaw/`),
  `scripts/sync-extensions-backup.sh` pra atualizar sob demanda. Commit
  e push confirmados (`03bee75..f668374`). Detalhes:
  [SESSAO_2026-07-20.md](SESSAO_2026-07-20.md#pendência-fechada-backup-git-das-extensões-próprias).

- [x] 🟡 **Migrar Amigão pro servidor Contabo — PRATICAMENTE CONCLUÍDA
  (Etapas 0-7 feitas, falta só Etapa 8).** Ver motivação e incidente
  real de 2026-07-18 na seção "Integrações reais" abaixo.
  - Etapas 0-5 (backup, rsync do estado, imagem Docker, compose,
    gateway `healthy` no Contabo, credencial WhatsApp validada):
    concluídas em 2026-07-29.
  - Etapa 6 (cloudflared instalado no Contabo, janela de 2 conectores
    simultâneos) e Etapa 7 (cutover — parada do cloudflared no Kali,
    confirmação de conector único, teste real de entrega ponta a
    ponta): concluídas em **2026-08-02**, cutover às 22:51 UTC, janela
    de 2 conectores durou ~8min. Detalhes:
    [SESSAO_2026-08-02.md](SESSAO_2026-08-02.md).
  - [ ] **Etapa 8 (pendente):** parar (não apagar) o container antigo
    `openclaw-openclaw-gateway-1` no Kali. Agendada para
    **2026-08-03, ~22:56 UTC** (24h de observação, como previa o
    plano original), **condicional** a tudo continuar estável até lá.
  - [ ] **Pendência registrada 2026-08-02: instalar Claude Security no
    Contabo** — só depois da observação de 24h confirmada estável
    (não misturar mudança de infra com nova ferramenta antes de saber
    que o cutover ficou sólido).

2. Agente de Defesa/Segurança - duplo propósito a
   esclarecer (ainda em aberto, não iniciado):
   a) Audita respostas do Amigão antes de entregar
      (Fase 1 do fork evolutivo, já planejada via
      before_agent_finalize)
   b) Analisa segurança de código dos projetos (relacionado
      ao item 1, agora que a leitura de repositório existe)

   Pergunta em aberto: um agente fazendo as duas coisas,
   ou dois agentes especializados?

Nota: qualquer nova capacidade de acesso (ler GitHub,
analisar código) precisa entrar no AGENTS.md com Red
Lines claras antes de ativar.

*Adicionado em 2026-07-15. Item 1 concluído em 2026-07-17.*

---

## Pendência (baixa prioridade): 8 erros de typecheck em github-repo-report/*.test.ts

### Problema
`pnpm tsgo:extensions:test` acusa 8 erros em
`extensions/github-repo-report/src/{audit-log,github-fetch,schema,tool}.test.ts`
(reconfirmado em 2026-08-06 após o refactor config-driven do plugin -
schema.test.ts/tool.test.ts foram reescritos nessa sessão e o problema
persiste, mesma natureza, +1 erro pelo teste novo de enum vazio em
schema.test.ts). Confirmado originalmente em 2026-07-18 que são só de
tipagem de teste, zero impacto real:
- `tsgo -p extensions/github-repo-report/tsconfig.json` (tsconfig de
  produção, exclui `*.test.ts`) → 0 erros.
- Os 27 testes do plugin (incluindo os 4 arquivos com erro) → 27/27 passam.
- 4 erros são `mock.calls[0] as [tupla]` com mock declarado sem tipar
  parâmetros (`vi.fn(async () => ...)` → `.mock.calls[0]` infere `[]`).
- 3 erros são acesso a campos de schema JSON (`.properties`,
  `.additionalProperties`, `.enum`) que existem no objeto `typebox` em
  runtime mas não aparecem no tipo estático exportado pela lib.

### Prioridade
Baixa — não bloqueia nada, plugin já roda em produção sem erro real.
Corrigir quando sobrar tempo de higiene (tipar os mocks; passar por
`unknown` antes do cast; ou trocar os asserts por helpers tipados).

---

## Pendência de prioridade MÉDIA — response-audit: falso positivo confirmado (2026-08-04)

`response-audit` marcou uma resposta real do Amigão como `hallucination`
quando na verdade a resposta estava correta. **É falso positivo (o
auditor sinalizou um problema que não existia), não falso negativo** —
risco diferente, não confundir na priorização: um falso positivo mina a
confiança no auditor e pode gerar ruído/alarme desnecessário; um falso
negativo deixaria uma alucinação real passar sem ser pega. Este caso é
do primeiro tipo.

**Caso concreto:** turno em produção (canal `whatsapp-cloud`, runId
`c4a22831-5f4f-4437-a5d7-c7e34d474041`, 2026-08-04T09:59:39 UTC) — Max
perguntou o saldo de créditos, o Amigão rodou a tool `session_status` e
respondeu "Saldo atual da API (DeepSeek): US$ 5.82". `response-audit`
marcou `flagged: true`, `category: "hallucination"`, com `reason`:
"O agente afirmou um saldo específico da API DeepSeek (US$ 5.82) sem ter
ferramenta para saber isso: [...] session_status [...] não retorna
saldo/creditos de conta da API." **Esse reason está factualmente
incorreto** — confirmado por Max que os US$ 5.82 batem com o saldo real
checado direto na DeepSeek.

**Causa raiz (investigada via leitura de código-fonte):**
`session_status` (`src/agents/tools/session-status-tool.ts`) chama
`buildStatusText` (`src/status/status-text.ts:448-509`), que pra
provedores não-OAuth-only como DeepSeek (`shouldLoadUsageSummary`,
`status-text.ts:157`) faz uma **chamada HTTP real e ao vivo** pro
endpoint oficial `GET https://api.deepseek.com/user/balance`
(`src/infra/provider-usage.fetch.deepseek.ts:24-111`), autenticada com a
API key configurada, e embute o resultado formatado (`Balance $X.XX`) no
texto de status devolvido. O modelo-juiz do `response-audit` não tem
visibilidade dessa cadeia interna — só vê o nome da tool e o texto
final, não o que a tool realmente busca por baixo.

**Hipótese de melhoria futura (registrada, não é tarefa pra fazer
agora):** dar mais contexto/visibilidade ao modelo-juiz do
`response-audit` sobre o que cada tool efetivamente faz (ex: descrição
mais rica das tools no prompt de auditoria, ou incluir metadata sobre
chamadas de rede/dados externos que a tool buscou), pra reduzir esse
tipo de falso positivo.

---

## ✅ Recomendação do Adendo 3 (teste local híbrido) — IMPLEMENTADA em 2026-08-10

O Adendo 3 do teste local híbrido (branch `test/local-hybrid-audit`, commit
`bb95eac`, não mergeada — investigação sobre HHEM/NLI como verificador
local) identificou um achado que sobrevivia independente do resultado do
HHEM: a condição `declared_action_text` + zero ferramentas executadas no
turno já é computável a partir de dados que `heuristic-filter.ts` calcula, e
pega a categoria `false_action` com custo zero de modelo. Recomendação
registrada: "somar essa regra (~5 linhas, sem modelo algum) ao invés de
tentar resolver `false_action` só via modelo."

**Implementada e deployada em produção em 2026-08-10** — com uma diferença
importante em relação ao que o Adendo 3 cogitou: em vez de veredito direto
sem modelo (como testado lá), a regra virou **sinal de prioridade no prompt
do juiz LLM, nunca bypass** — decisão final continua sempre do LLM. A
validação ao vivo do deploy confirmou por que essa cautela era necessária:
um teste real de injeção de prompt fez o agente recusar corretamente uma
confirmação falsa, o que disparou o sinal heurístico (`declared_action_text`
presente, zero ferramentas), mas o juiz LLM leu o contexto completo e não
marcou como `false_action` — uma regra de veredito direto teria gerado um
falso positivo justamente nesse caso, o comportamento mais correto possível
do agente. Detalhes completos:
[SESSAO_2026-08-10_false-action-heuristic-deploy.md](SESSAO_2026-08-10_false-action-heuristic-deploy.md).

---

## Pendências de baixa prioridade — 2026-08-04

- cloudflared desatualizado no Contabo (2026.7.1 -> 2026.7.3
  recomendado).
- Arquivo de cache .serena/cache/typescript/document_symbols.pkl (83MB)
  no repo Kali passou do limite recomendado do GitHub (50MB) -
  considerar .gitignore ou Git LFS.

## Próximo passo definido: update do OpenClaw v2026.6.9 → v2026.7.1-2

Requer sessão dedicada com ambiente de staging (não Kali/Contabo
direto). Mudanças estruturais: Codex app-server ≥0.143, migrations
automáticas no boot (rodar openclaw doctor --fix depois), Slack
progress reactions requer messages.statusReactions.enabled. Dois
conflitos de merge reais mapeados na branch production-local-fixes:
docker-compose.yml (zero risco, upstream não tocou), src/plugins/hooks.ts
(conflito real - upstream adicionou before_agent_finalize: 15_000 no
mesmo objeto onde já temos nosso fix da Bug 4; resolução: manter as 3
entradas). Detalhes completos em
SESSAO_2026-08-04_checkpoint-etapa8.md.

## Sequência de segurança pendente (plano do Amigão, 2026-08-04)

1. Rotação de chaves: DeepSeek (console do provedor), gateway token
   (openssl rand -hex 32 + atualizar credencial), Meta/WhatsApp (Meta
   Business dashboard) - ação manual, sem dependência técnica.
2. [x] ✅ **P0.2 - sandbox real: CONCLUÍDO em 2026-08-05.** Rebuild da
   imagem do gateway no Kali com `OPENCLAW_INSTALL_DOCKER_CLI=1` (tag
   `openclaw:local-sandboxed`, Docker CLI + compose-plugin instalados
   via repo APT oficial com verificação de fingerprint GPG), build da
   imagem separada `openclaw-sandbox:bookworm-slim` (cache hit, sem
   drift do Dockerfile), ambas transferidas pro Contabo via
   `docker save | ssh | docker load` (mesmo método da migração
   original, evitando expor código-fonte em produção). `openclaw.json`:
   `sandbox.mode: "all"` (era `"off"`) + `docker.memory: "512m"` +
   `docker.pidsLimit: 256` (valores conferidos contra o exemplo oficial
   em `docs/gateway/config-agents.md` do upstream, que usa
   `pidsLimit: 256` idêntico e `memory: "1g"` como referência mais
   generosa). `docker-compose.yml`: `docker.sock` remontado só no
   serviço `openclaw-gateway` (não no `openclaw-cli`) +
   `group_add: "988"` (GID real do grupo `docker` no Contabo, diferente
   do 124 usado no Kali). Backups dos 3 arquivos originais tirados
   antes de qualquer mudança real.
   **Validação ao vivo completa**: `docker exec ... docker --version`
   funcional (29.7.1), `id` do processo do gateway confirma grupo 988,
   e — mais importante — uma mensagem de teste real via WhatsApp gerou
   um container `openclaw-sbx-agent-main-*` de verdade (imagem
   `openclaw-sandbox:bookworm-slim`, `scope: "agent"`, `sleep infinity`
   como esperado) com os logs do gateway confirmando a tool policy do
   sandbox sendo aplicada (`tools.allow`/`tools.deny` filtrando tools) —
   não é só o container subindo à toa, é o isolamento real em uso.
   **Incidente no meio do processo, sem impacto residual**: um
   `chown root:root` equivocado no `openclaw.json` (baseado numa
   suposição errada a partir do dono do arquivo de backup, que só
   ficou `root:root` porque o `cp` sem `-p` não preserva o dono
   original) causou um crash loop de ~4min (`EACCES`, exit 78) até ser
   diagnosticado pelos logs (`chown 1000 ...` no próprio erro) e
   corrigido — gateway precisa do arquivo com dono uid 1000 (`node`),
   não root.
   **Validação final (2026-08-06)**: teste ponta a ponta com pedido
   real de execução do comando `id` via WhatsApp, confirmado por 3
   fontes de evidência independentes (docker logs do gateway, docker
   events do container `openclaw-sbx-agent-main-f331f052` com
   `exec_create`→`exec_start`→`exec_die exitCode=0`, e resposta
   funcional do agente sem o grupo 988 do host) — fecha a ressalva
   registrada em 2026-08-05 11:39 UTC (execução real de tool ainda não
   comprovada diretamente). P0.2 fechado sem pendências. Detalhes:
   [SESSAO_2026-08-05.md](SESSAO_2026-08-05.md#validação-final-do-p02--sandbox-real-confirmado).
   [x] ✅ **Regressão encontrada e corrigida (2026-08-06)**: ligar
   `sandbox.mode: "all"` fez a política de tools do sandbox cair no
   `DEFAULT_TOOL_ALLOW` (`constants.ts:18-38`), que bloqueava
   `ask_max` (rede de segurança contra alucinação) e
   `github_repo_report` desde a ativação do P0.2, sem ninguém
   perceber. Causa raiz confirmada no zod-schema: faltava
   `tools.sandbox.tools.alsoAllow` (distinto do `tools.alsoAllow` de
   raiz, que só expõe a tool ao modelo). Corrigido adicionando
   `tools.sandbox.tools.alsoAllow: ["github_repo_report", "ask_max"]`
   no `openclaw.json` do Contabo (backup
   `openclaw.json.bak-20260806-0041-toolpolicyfix`), restart do
   gateway, validado ao vivo (log caiu de 14 → 12 tools removidas por
   turno, isolamento do `exec`/Docker do P0.2 intocado). As outras 12
   tools bloqueadas (`web_search`, `web_fetch`, `message`, `tts`,
   `agents_list`, goal tools etc.) ficaram de fora por decisão de
   escopo — sem caso de uso comprovado hoje. Detalhes:
   [SESSAO_2026-08-05.md](SESSAO_2026-08-05.md#regressão-encontrada-e-corrigida-ask_maxgithub_repo_report-bloqueados-pelo-sandbox).
3. P1 do plano do Amigão (não lido em detalhe ainda): gateway só
   loopback + TLS via Nginx Proxy Manager + firewall, pinar versão de
   imagem (parar de usar :latest), corrigir permissões.
4. P2 do plano do Amigão (não lido em detalhe ainda): backup com teste
   de restore, monitoramento, cadência de update.
5. Update do OpenClaw v2026.6.9 → v2026.7.1-2 (ver addendum de hoje
   mais acima - 2 conflitos de merge já mapeados).
6. Melhoria do response-audit (falso positivo do caso DeepSeek balance
   - dar visibilidade de tool ao modelo-juiz).
7. Rodar o Claude Security de verdade (créditos pendentes da vez
   anterior).

## Deploy via imagem publicada — preparado, falta ativar (2026-08-25)

Infraestrutura pronta (compose parametrizado, workflow de CI, bug do
DOCKER_GID corrigido) pra publicar a imagem do orquestrador no ghcr.io e
deploy virar `docker pull` em vez de build no servidor. Ver
[DEPLOY_IMAGEM.md](DEPLOY_IMAGEM.md) pro que falta:

1. Criar o PAT de leitura do ghcr.io e decidir onde/como guardar por
   servidor.
2. Cortar a primeira tag (`orchestrator-v0.1.0`) e confirmar que o
   workflow publica de verdade.
3. Decidir se/quando migrar o Contabo do fluxo atual
   (`scripts/deploy-orchestrator.sh`) pro modo registry (não é
   obrigatório, os dois coexistem).
4. Decisão em aberto, maior escopo: publicar também a imagem do gateway
   OpenClaw via CI — depende de fechar antes quais extensões
   customizadas (hoje só locais, não commitadas no repo vendorizado)
   entram na imagem oficial do cliente.

## Roteiro: extrair template genérico (sem Arbo) do Amigão

Objetivo: usar a base de hoje (sandbox seguro + secrets via SecretRef)
como template reutilizável pra implantar em servidores de outros
clientes, cada um com seu próprio agente. Baseado no mapeamento
completo de 2026-08-05 (ver SESSAO_2026-08-05.md).

**1. Extrair identificadores de cliente pra um bloco de config único**
✅ Concluído em 2026-08-06 - ver SESSAO_2026-08-05.md (seção do
incidente/correção) para detalhes da aplicação e do incidente que
aconteceu no meio do processo.

Hoje o telefone/allowlist está espalhado em 3 lugares
(commands.ownerAllowFrom, channels.whatsapp-cloud.allowFrom,
plugins.entries.ask-max.config.to) + phoneNumberId da Meta. Consolidar
num único bloco claramente marcado "config por cliente", facilitando
trocar tudo de uma vez ao clonar pra um cliente novo.

**Decisão tomada (2026-08-05/06):** confirmado que openclaw.json
suporta interpolação de ${VAR} em qualquer campo string (não só
SecretRef) - env-substitution.ts:201-207, aplicado no pipeline
principal (io.ts:1329). Diff já desenhado, opção B escolhida
(preserva as 2 variantes do telefone do Max - "5541984445755" e
"554184445755" - que existem de propósito pra casar com formatos
diferentes que a Meta normaliza em eventos de webhook; templatizar só
com 1 variável reduziria a allowlist funcionalmente). Variáveis:
ARBO_OWNER_PHONE, ARBO_OWNER_PHONE_ALT, ARBO_PHONE_NUMBER_ID. Falta
aplicar: adicionar as 3 linhas no .env do Contabo, aplicar o diff no
openclaw.json (4 campos: commands.ownerAllowFrom,
channels.whatsapp-cloud.allowFrom, ask-max.config.to,
whatsapp-cloud.phoneNumberId), backup, restart, validar com mensagem
real. Fica pra próxima sessão com tempo de acompanhar a validação.

**2. Tirar o repo-registry.ts do código-fonte**
✅ Concluído em 2026-08-06 e em produção - ver
SESSAO_2026-08-06_github-repo-report.md para o refactor completo
(config-driven via openclaw.plugin.json configSchema + src/config.ts),
os 36 testes, o achado crítico do config de produção sem bloco
`config` (resolvido antes do corte), o build Docker real
(openclaw:local-sandboxed-v2) e a validação ponta a ponta via
WhatsApp (relatório real do Mox retornado). Rollback documentado, dois
comandos independentes (imagem via .env, config via openclaw.json.bak).

~~extensions/github-repo-report/src/repo-registry.ts tem owner/slugs
hardcoded em TypeScript (GITHUB_REPO_OWNER = "maxwellnasci", slugs
"meu-agente"/"arbo"/"Mox---Sistemas"). Isso é o ponto mais "preso" -
pra reusar em outro cliente exige editar código, não só JSON. Mover
pra config carregável.~~

**3. Criar um template vazio da AGENTS.md Parte B**
✅ Concluído em 2026-08-25 —
[docs/templates/AGENTS_PARTE_B_TEMPLATE.md](templates/AGENTS_PARTE_B_TEMPLATE.md).
Template completo (Parte A copiada literal do Amigão/Arbo + Parte B com
campos entre [COLCHETES] e instruções de preenchimento), pronto pra
copiar direto pro `~/.openclaw/workspace/AGENTS.md` de um cliente novo.

**4. Padronizar o setup de infraestrutura por cliente/servidor**
Cada implantação nova precisa de: GID do grupo docker redescoberto
(varia por host - stat -c '%g' /var/run/docker.sock), túnel Cloudflare
próprio (UUID + hostname + credentials-file), e uma imagem buildada
(hoje só existe porque foi feita manualmente no Kali e transferida -
usar scripts/docker/setup.sh OPENCLAW_SANDBOX=1 do próprio upstream,
que já automatiza isso, em vez do processo manual que fizemos hoje).

**5. Decidir o que fica no "core" vs. vira add-on opcional por cliente**
github_repo_report e ask-max são genéricos no código, só a config
injeta o dado do cliente - ok manter no core. Definir se cada cliente
novo usa as mesmas 2 tools reintroduzidas hoje no sandbox, ou se isso
também vira decisão por instância.

**Já pronto, sem trabalho adicional:** sandbox de segurança inteiro
(mode/workspaceAccess/docker limits), padrão de SecretRef,
response-audit (zero menção à Arbo no código), SOUL.md/TOOLS.md/
HEARTBEAT.md (textos padrão do OpenClaw, nunca customizados).
