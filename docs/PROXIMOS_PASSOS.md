# Próximos Passos (Roadmap)

## FASE ATUAL: Segurança antes de expandir

O agente está vivo (`deepseek/deepseek-chat`, v2026.6.9) mas rodando **sem sandbox**.
Antes de qualquer nova feature, religar o isolamento é o passo zero.

### Prioridade 🔴 URGENTE

- [x] **Configurar docker.sock no compose:** (Feito)
- [x] **Religar sandbox:** (Feito)
- [x] **Validar isolamento:** (Em andamento)

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
- [ ] **Migrar Amigão pro servidor Contabo** — hoje depende do Kali estar ligado; rodar no Contabo dá independência.
  **Reforçado por incidente real em 2026-07-18**: notebook desligado (uso
  normal, não bug) das 08:25 às 17:19 (`-03`, ~8h55min) deixou o gateway —
  e o `response-audit` recém-conectado — fora do ar o dia inteiro sem
  ninguém perceber até o usuário voltar e pedir um resumo. Container
  voltou sozinho graças a `restart: unless-stopped` + `docker.service`
  habilitado no boot, mas só porque a máquina foi religada; não teria
  voltado sozinha se tivesse ficado desligada. Detalhes da investigação em
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
  2. [ ] 🔧 **Requer sessão dedicada de investigação** — a correção de
     verdade, ainda pendente: auditar todo `return` do pipeline de
     entrega (`src/auto-reply/reply/dispatch-from-config.ts`,
     `src/auto-reply/reply/agent-runner.ts`) pra achar qual(is)
     caminho(s) de saída entregam a resposta final com sucesso mas pulam
     `.complete()` no `ReplyOperation`, cobrindo pelo menos os 2 formatos
     de turno já confirmados. Validar ao vivo depois com a mesma técnica
     de rajada concorrente desta sessão (fila deve esvaziar em segundos,
     não minutos). Não mexer no limiar de 5min do health-monitor rápido —
     a cautela ali continua correta. **Prioridade reduzida de urgência**
     depois da etapa 1: o pior cenário multi-usuário (um contato travando
     o Amigão pra todos) já está mitigado; isso é a correção de fundo,
     não bloqueia mais um lançamento imediato.

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

## Pendência (baixa prioridade): 7 erros de typecheck em github-repo-report/*.test.ts

### Problema
`pnpm tsgo:extensions:test` acusa 7 erros em
`extensions/github-repo-report/src/{audit-log,github-fetch,schema,tool}.test.ts`.
Confirmado (2026-07-18) que são só de tipagem de teste, zero impacto real:
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
