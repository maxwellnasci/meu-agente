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
- [ ] **Lacuna `response-audit` + `ask_max`:** investigado em 2026-07-18,
  ver
  [SESSAO_2026-07-18.md](SESSAO_2026-07-18.md#investigação-da-lacuna-do-response-audit-no-turno-do-ask_max).
  Confirmado com o transcript real que o filtro heurístico deveria ter
  disparado (`tool_executed`, mesmo padrão que gerou registro real no
  teste da Marina) — não é ajuste de cobertura do filtro. Causa raiz da
  lacuna em si não isolada (sem erro/exceção nos logs, banco confirmado
  limpo em todos os namespaces, caminho "durable" descartado). Hipótese
  líder: o fix do `senderIsOwner` fez o `before_agent_run` do `ask-max`
  passar a rodar I/O assíncrono real (`consumePendingAskMax`) em TODA
  mensagem do Max, não só nas respostas ao operador — interação com o
  `before_agent_run` do `response-audit` nunca testada em produção antes
  desta sessão. Próximo passo proposto (aguardando aprovação): logs de
  debug temporários nos 4 pontos de captura, mesma técnica que resolveu o
  bug de ordenação de hooks anterior.

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
