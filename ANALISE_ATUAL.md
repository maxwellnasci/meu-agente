# Análise Atual — Prontidão do "meu-agente" como Agente Empresarial

> Diagnóstico read-only. Data: 2026-09-02. Nenhum código, config, dependência
> ou segredo foi alterado. Valores de `.env`, tokens e chaves não são expostos
> aqui — só nomes de variáveis e contratos.

---

## 1. Resumo executivo

O `meu-agente` é um **laboratório maduro de engenharia de agentes**, não ainda
um produto empresarial multiempresa. O que existe é sólido: um gateway OpenClaw
em produção real (servidor Contabo) com sandbox Docker isolado, canal WhatsApp
Cloud API oficial ponta a ponta, e um orquestrador Python (LangGraph/FastAPI)
no padrão **Supervisor / Enxame de Especialistas** com três especialistas
(programação via OpenClaw, ciberseguraça, automação n8n), guards determinísticos
em Python, checkpointing, streaming SSE, CI que publica imagem, e uma cultura de
"sem prova, sem aprovação" com testes de regressão para cada bug de produção.

A distância até "agente empresarial" está concentrada em cinco frentes, todas
hoje **ausentes ou incompletas**:

1. **Autenticação / superfície de rede** — o orquestrador expõe `/v1/turn` e
   `/tasks/stream` **sem autenticação nenhuma**, e esses endpoints têm efeitos
   colaterais reais (rodam agent turns com exec, criam/apagam workflows n8n de
   produção). É o bloqueador nº 1.
2. **RAG / base de conhecimento** — inexistente. O agente não tem como
   responder sobre dados/políticas de um cliente sem inventar. O próprio
   projeto já identificou "alucinação elegante" como o risco central.
3. **Atendimento humano estruturado** — só existe o `ask-max` (o agente
   escala uma dúvida pontual ao operador). Não há fila, takeover de conversa,
   SLA nem inbox de atendentes.
4. **LGPD** — praticamente nenhuma medida: telefone (PII) usado como chave em
   claro no SQLite, sem política de retenção, sem consentimento, sem rota de
   exclusão/exportação de titular, logs gravam conteúdo de mensagem.
5. **Multiempresa (multi-tenant)** — não existe. Hoje é "um deploy inteiro por
   cliente", sem isolamento de dados nem roteamento por tenant.

Além disso, o **cutover do canal WhatsApp para o orquestrador foi decidido mas
não implementado**: hoje o orquestrador só é alcançado indiretamente, como
_tool_ (`ask_orchestrator`) chamada pelo agente pessoal `main` (Amigão). A
orquestração multi-especialista de verdade (fila com 2+ especialistas,
scratchpad compartilhado entre especialistas diferentes, replanejamento) **nunca
rodou em produção** — só nós isolados foram testados.

**Veredito:** pronto para operar como **assistente pessoal / piloto técnico de
um operador** (é o uso real hoje). **Não pronto** para atender clientes finais
de uma empresa sem as frentes 1–4 acima. Multiempresa é um passo posterior.

---

## 2. O que está pronto

### 2.1 Arquitetura e componentes

| Componente | Papel | Estado |
|---|---|---|
| `openclaw/` (gateway Node/TS, fork vendorizado, fora do git) | Runtime de agentes: sandbox, exec, canais, skills | **Produção** (Contabo) |
| `orchestrator/` (Python, LangGraph + FastAPI) | "Cérebro": roteia, mantém estado, delega a especialistas | **Deployado** (Contabo, 2026-08-22) |
| `extensions/` (4 plugins próprios) | `whatsapp-cloud`, `ask-max`, `response-audit`, `github-repo-report` | Backup por cópia de `openclaw/extensions/` |
| `orchestrator-bridge` (plugin no gateway) | Tool `ask_orchestrator` → `POST /v1/turn` | **Produção**, validado ponta a ponta |

**Fluxo de produção atual:**

```
WhatsApp Cloud (Meta Graph API)
   │  webhook assinado (HMAC X-Hub-Signature-256)
   ▼
plugin whatsapp-cloud  (rate limit 30/min, replay cache, ack imediato,
   │                     fila de dispatch serializada por remetente)
   ▼
agente `main` / Amigão  (assistente pessoal do Max; AGENTS.md Parte A+B)
   ├── sessions_spawn → especialista `cybersec`  (nativo OpenClaw)
   └── tool ask_orchestrator → orquestrador Python /v1/turn
                                   │
                                   ▼
                       supervisor (LLM via OpenRouter, deepseek-chat)
                          │  tool-calling DispatchSpecialist → fila pending_specialists
             ┌────────────┼─────────────────────┐
             ▼            ▼                     ▼
   specialist_openclaw  specialist_cybersec   specialist_n8n
   (delega ao gateway   (mesmo canal +        (ReAct manual, tools REST
    /v1/chat/completions) prompt hardened +    reais contra n8n de produção)
                          cybersec_guard)
             └────────────┼─────────────────────┘
                          ▼
                   synthesize_final → reply_text
```

### 2.2 Segurança de infraestrutura (validada ao vivo)

- **Sandbox Docker real em produção** (`sandbox.mode: "all"` no Contabo):
  container efêmero por sessão, usuário `sandbox` (não root), imagens com
  hash SHA256 fixo, `workspaceAccess: none`, workspace read-only, tool
  policy allow/deny (inclusive `tools.sandbox.tools.alsoAllow` distinto do
  de raiz — regressão já corrigida). Execução real de `exec` dentro do
  sandbox confirmada com evidência direta (docker logs + docker events).
- `cap_drop: NET_RAW/NET_ADMIN`, `no-new-privileges:true` no compose do gateway.
- WhatsApp: verificação de assinatura HMAC, rate limiting, replay protection,
  ack imediato + processamento assíncrono, **serialização de dispatch por
  remetente** (fix do deadlock `foregroundReplyFence` — bug upstream conhecido).
- Portas do gateway e do orquestrador publicadas em `127.0.0.1` no compose.
- `.gitignore` protege `**/.env`, `*.env`, `gateway-token.json`, `data/`,
  `.orquestra_vault`, `.orquestra_salt`. Repo sem segredos no histórico
  (auditado 2026-08-28).

### 2.3 Guards determinísticos no orquestrador (defesa em profundidade)

- `cybersec_guard.py` — bloqueia, em Python puro antes de qualquer chamada ao
  LLM, instruções que mirem infra de produção própria (Contabo, Amigão,
  evolution-api, WhatsApp Cloud, chatwoot). Trata negação na mesma sentença
  ("nunca testar o Contabo") para não entrar em loop; avalia tanto a mensagem
  do usuário quanto as instruções repassadas pelo supervisor (multi-turn).
- `n8n_guard.py` — recusa `delete`/`deactivate` de workflow pré-existente se a
  instrução não contiver verbo explícito de autorização.
- Trava de loop do supervisor (`max_supervisor_iterations`, default 4) +
  `fresh_turn_input()` que reseta o estado por-tarefa a cada `/v1/turn`
  (corrige bug crítico de produção onde a conversa travava permanentemente).

### 2.4 Persistência, observabilidade, testes, deploy

- **Persistência:** checkpointer `AsyncSqliteSaver` por `thread_id`
  (`orchestrator/data/checkpoints.sqlite`); estado do gateway em
  `~/.openclaw/state/openclaw.sqlite`. Interface pronta para trocar por
  `AsyncPostgresSaver` sem mexer no builder do grafo.
- **Observabilidade:** wiring real do LangSmith (`_configure_langsmith_tracing`,
  ativa com chave); logs INFO estruturados no orquestrador (decisão do
  supervisor, duração/sucesso de cada especialista); hooks OTEL no gateway
  (via env); `scripts/heartbeat-monitor.sh` (SIGUSR2 + diagnostic report ao
  detectar falhas consecutivas de healthcheck); banco de auditoria
  `plugin_state_entries` namespace `amigao-audit`; plugin `response-audit`
  (flag pós-entrega de alucinação/citação fabricada/ação falsamente declarada).
- **Testes:** 8 arquivos no orquestrador — guards, reset de estado multi-turn,
  e2e do cybersec_guard pelo grafo completo, especialista n8n (com teste de
  integração real opcional contra produção), ponte do LangSmith, loops de eco
  do guard. Cada bug de produção virou teste de regressão. CI roda a suíte
  antes de publicar imagem.
- **Deploy:** `scripts/deploy-orchestrator.sh` (roda testes → rsync → commit
  local no servidor → `docker compose build` → `up -d` → healthcheck).
  Alternativa por imagem publicada: `.github/workflows/docker-publish-orchestrator.yml`
  publica `ghcr.io/maxwellnasci/meu-agente-orchestrator` em tag
  `orchestrator-vX.Y.Z` (segredos sempre fora da imagem, `.dockerignore`).
- **Configuração:** `pydantic-settings` com prefixo `ORCHESTRATOR_`; imagem
  configurável via `ORCHESTRATOR_IMAGE`; rede Docker compartilhada
  `openclaw_default` para o orquestrador resolver o gateway por nome de
  container.

### 2.5 Base de conhecimento operacional / template multi-cliente

- Documentação viva extensa (`docs/`): arquitetura, sessões, casos de bug,
  técnicas de debug, runbook de manutenção.
- Templates para bootstrap de cliente novo: `docs/templates/AGENTS_PARTE_B_TEMPLATE.md`,
  `docs/templates/SETUP_NOVO_CLIENTE.md` (GID do Docker, túnel Cloudflare,
  opções de imagem), decisão core vs. add-on por plugin.
- Config de exemplo da Arbo arquivada (`docs/templates/exemplos/`) pronta para
  reativar com cliente real.

---

## 3. O que está incompleto ou apenas planejado

### 3.1 Integração / orquestração

- **Cutover WhatsApp → orquestrador: decidido, não implementado.** Docs
  (`ESTADO_ATUAL.md`, 2026-08-26/27) registram a decisão da "Opção A" (o
  orquestrador vira o dono do canal), mas em produção o canal ainda entrega
  ao agente `main`. O orquestrador só recebe `/health` e chamadas via
  `ask_orchestrator`.
- **Divergência de código a resolver:** a cópia-backup `extensions/whatsapp-cloud/src/inbound.ts`
  **já contém** o handoff direto (`callOrchestratorTurn` substituindo o
  pipeline interno do agente), o que não corresponde ao estado de produção
  descrito nos docs. Ou o backup está à frente da produção, ou é um estado de
  desenvolvimento não deployado. Precisa ser reconciliado antes de qualquer
  decisão de cutover.
- **Orquestração multi-especialista nunca exercitada em produção** — só nós
  isolados foram validados. Fila com 2+ itens, scratchpad lido entre
  especialistas distintos e replanejamento do supervisor são caminho de
  código não testado ao vivo.
- Timeout de request ao gateway (`openclaw_request_timeout_sec` 120s) e
  `turn_timeout_sec` (150s) são longos para um canal síncrono de WhatsApp;
  auditoria sugere reduzir para ~60s.

### 3.2 RAG / base de conhecimento — **ausente**

- Nenhuma ingestão de documentos, nenhum índice vetorial, nenhuma resposta
  com citação de fonte.
- `references/politicas-*.md` como skill é TODO desde jun/2026
  (`PROXIMOS_PASSOS.md`, `ESTADO_ATUAL.md`).
- `agents.defaults.memorySearch` do OpenClaw está **desabilitado** (sem chave
  de embeddings configurada).
- Consequência direta: o agente não tem como sustentar atendimento factual
  sobre um cliente — exatamente o cenário que o projeto identificou como o
  diferencial ("o moat é EXECUÇÃO/integração com dados reais, não análise").

### 3.3 Atendimento humano — parcial

- `ask-max`: o agente escala **uma dúvida pontual** ao operador via WhatsApp e
  roteia a resposta de volta. Útil, mas não é atendimento humano.
- **Não há:** fila de atendimento, takeover de conversa (humano assume o
  contato), status "em atendimento humano" vs "com o bot", horário comercial,
  SLA, inbox de múltiplos atendentes. Chatwoot foi removido da VPS.

### 3.4 Autenticação e superfície de rede

- `/v1/turn` e `/tasks/stream` **sem autenticação** (nem Bearer, nem rate
  limit, nem `max_length` no payload). Alcançável de qualquer processo em
  localhost/LAN; request "simples" dispara o grafo sem preflight CORS.
  (Backlog P1 da auditoria 2026-08-28.)
- Portas `3978` (MS Teams do gateway) e `5678` (n8n local) em `0.0.0.0` na LAN
  — deveriam estar em `127.0.0.1`. (P1.)
- `OPENCLAW_GATEWAY_TOKEN` existe e é verificado (sha256 idêntico entre
  gateway e orquestrador), mas **vazou em output de tool durante a auditoria**
  — rotação pendente (P3).
- `.env` rastreado no `.git` local do repo `/root/openclaw` no Contabo (sem
  remote) — pendência de limpeza de histórico.

### 3.5 Multiempresa (multi-tenant) — **ausente**

- `openclaw.json` é single-tenant; o orquestrador aponta para **uma** instância
  n8n e **um** gateway via `settings` (env vars).
- Sem modelo de dados por empresa, sem roteamento canal/número → tenant, sem
  isolamento de estado nem de credenciais por cliente.
- O modelo atual é "template + deploy manual por cliente" (runbook), sem
  onboarding self-service.

### 3.6 LGPD — **quase nada**

- Telefone do usuário usado como `thread_id`/`session_key` em claro no SQLite.
- Sem política de retenção; o checkpointer cresce indefinidamente ("poda de
  histórico" é P4).
- Sem registro de consentimento, sem DPA, sem base legal documentada, sem rota
  de exportação/exclusão de titular.
- Logs (INFO) e banco de auditoria registram conteúdo de mensagem.
- Sem anonimização/pseudonimização.

### 3.7 Auditoria

- Existe material bruto (logs estruturados + banco `amigao-audit` +
  `response-audit`), mas **não** uma trilha de auditoria consolidada,
  imutável, exportável, com quem/o quê/quando/entrada/saída/decisão do
  supervisor por turno, nem retenção definida.

### 3.8 Monitoramento

- Gateway: healthcheck no compose + heartbeat local (roda no Kali).
- **Orquestrador: sem healthcheck no compose e 1 worker uvicorn** — um hang
  não se auto-recupera. (P2: healthcheck + `--workers 2`.)
- Sem uptime-check externo do túnel Cloudflare (o daemon roda no Contabo, não
  é observável de fora).
- Sem alerting (ninguém é avisado quando o orquestrador ou o gateway cai — já
  houve incidente de ~9h fora do ar sem ninguém perceber, com o Kali).
- Sem dashboard, sem métricas de negócio (volume, taxa de resolução,
  escalonamento).

### 3.9 Persistência / disponibilidade

- SQLite dos dois lados; sem Postgres, sem backup automatizado do estado, sem
  HA. Migração para Postgres é documentada como "caminho de evolução", não
  feita.
- Ponto único de falha: SQLite, 1 worker uvicorn, túnel Cloudflare, OpenRouter,
  e o **Kali como dependência viva** (as skills de ciberseguraça só existem
  montadas lá via bind-mount; se o orquestrador escalar sem replicá-las, o
  Contabo passa a depender do Kali).

### 3.10 Testes / CI / higiene

- Testes só do orquestrador. As extensões TS têm alguns `*.test.ts` mas há
  **8 erros de typecheck pendentes** em `github-repo-report/*.test.ts` e não
  há CI rodando testes/lint das extensões.
- Sem teste de integração do fluxo WhatsApp completo.
- `n8n_guard.py` só conhece os cues `desativ`/`pause`/`pausa` — "desliga",
  "para", "tira do ar" passariam. (P2.)
- Comentário `# TESTE_CURSOR: validando conexão e edição em tempo real`
  commitado em `orchestrator/src/orchestrator/graph/n8n_guard.py:37`.
- Commits automáticos ("Orquestra: Tarefa #22 aprovada") de uma ferramenta
  externa (`orquestra` CLI, `~/.local/bin/orquestra` + `~/.orquestra.json`,
  documentada em `CURSOR_INTEGRATION.md`) entrando no repo.
- Lixo na raiz: `bug4-monitor.log`, `bug4-*.sh`, `test_copilot_models.py`,
  `.orquestra_logs.md`. `ANALISE.md` da raiz na verdade é doc de variáveis de
  ambiente (nome enganoso — o README diz "auditoria inicial de segurança").
- Bloco-resumo do topo de `docs/ESTADO_ATUAL.md` desatualizado (diz "Kali
  parado"). Sem `orchestrator/.env.example`.

### 3.11 Conformidade de canal (Meta)

- App WhatsApp Cloud **não verificado** pela Meta → limitado a 5 destinatários
  cadastrados manualmente na allowlist.
- Política Meta (jan/2026) proíbe "General Purpose AI" sem foco declarado —
  risco de suspensão; `AGENTS.md` precisa de escopo explícito.

---

## 4. Riscos e pontos críticos

| # | Risco | Severidade | Nota |
|---|---|---|---|
| R1 | `/v1/turn` e `/tasks/stream` sem auth, com efeitos colaterais reais (exec, criar/apagar workflow n8n de produção) | **Bloqueador** | Qualquer processo em localhost/LAN dispara o grafo |
| R2 | Sem RAG/base de conhecimento → agente inventa dados/políticas do cliente | **Bloqueador** para atendimento | O projeto já nomeou "alucinação elegante" como risco central |
| R3 | LGPD ausente: PII em claro, sem retenção/consentimento/exclusão | **Bloqueador legal** para dados de terceiros no Brasil | |
| R4 | Sem atendimento humano estruturado (fila, takeover, SLA) | **Bloqueador** para operação de suporte | `ask-max` cobre só dúvida pontual do agente |
| R5 | Sem multi-tenancy | Bloqueador para SaaS; OK para "1 agente / 1 empresa" | Hoje = N deploys manuais |
| R6 | Cutover WhatsApp→orquestrador não feito + orquestração multi-especialista nunca testada em produção | Alto | Metade do sistema (n8n + cérebro LangGraph) sem caminho até o usuário final |
| R7 | Orquestrador sem healthcheck e 1 worker; sem alerting; uptime do túnel não observável de fora | Alto | Já houve ~9h fora do ar sem detecção |
| R8 | SQLite + sem backup automatizado + Kali como dependência viva de skills | Alto | Ponto único de falha múltiplo |
| R9 | Fork OpenClaw vendorizado fora do git; mudanças de compose reaplicadas à mão; backup de extensões por cópia manual | Médio | Divergência silenciosa já ocorreu (container com imagem antiga, 11 vs 12 plugins) |
| R10 | Token do gateway vazou; `.env` no histórico git do Contabo | Médio | Rotação + limpeza de histórico pendentes |
| R11 | `n8n_guard` com cobertura de verbos incompleta | Médio | "desliga/para/tira do ar" não são bloqueados |
| R12 | Dependência de OpenRouter (deepseek-chat) sem fallback de provider no orquestrador | Médio | `eval-router.py` é um começo de governança de modelo |
| R13 | App WhatsApp não verificado (5 destinatários) + risco de política Meta | Médio | Impede qualquer piloto com volume real |

---

## 5. Backlog priorizado

### AGORA — destrava segurança e coerência (pré-requisito de qualquer uso com terceiros)

1. **Auth em `/v1/turn` e `/tasks/stream`**: Bearer token + rate limit +
   `max_length` no payload; atualizar os 2 callers
   (`extensions/whatsapp-cloud/src/orchestrator-client.ts` e
   `openclaw/extensions/orchestrator-bridge/src/ask-orchestrator-tool.ts`).
2. **Bind `127.0.0.1`** nas portas `3978` e `5678`.
3. **Healthcheck do orquestrador no compose** + `--workers 2` (ou restart
   automático confiável equivalente).
4. **Rotacionar `OPENCLAW_GATEWAY_TOKEN`** (server-side, propagar
   gateway+orquestrador+cli); limpar `.env` do histórico git do repo do Contabo.
5. **Decidir o cutover WhatsApp→orquestrador**: implementar (com rollback por
   config) **ou** registrar formalmente que o orquestrador fica como serviço
   interno chamado por tool. Reconciliar a cópia `extensions/whatsapp-cloud`
   com o que está em produção.
6. **Higiene**: remover o comentário `TESTE_CURSOR`; ampliar cues do
   `n8n_guard` + teste; criar `orchestrator/.env.example`; mover
   `bug4-*`/`test_copilot_models.py`/`.orquestra_logs.md` da raiz; atualizar o
   bloco-resumo de `ESTADO_ATUAL.md`; revisar commits automáticos do
   `orquestra` CLI no repo.

### PRÓXIMO — vira "funcionário digital para UMA empresa"

7. **RAG mínimo**: ingestão de documentos do cliente + busca + resposta com
   citação de fonte; ligar `memorySearch` (chave de embeddings) ou um
   retriever externo. Somar ao prompt anti-alucinação + implementar o
   "Supervisor / LLM-as-judge" já previsto no roadmap.
8. **Atendimento humano**: status bot/humano por conversa, takeover, fila,
   notificação ao atendente (reaproveitar a infra do `ask-max`), horário/SLA.
9. **Persistência**: migrar checkpointer para Postgres; backup automatizado do
   estado; política de retenção (TTL por `thread_id`, poda de histórico).
10. **Trilha de auditoria** consolidada e exportável (turno: quem, quando,
    entrada, saída, decisão do supervisor, especialistas acionados, guards
    disparados) com retenção definida.
11. **LGPD base**: hash do telefone como chave (PII fora de texto claro);
    retenção + consentimento + rota de exportação/exclusão de titular; revisão
    dos logs que gravam conteúdo.
12. **Monitoramento**: uptime-check externo do túnel; alerting quando
    orquestrador/gateway cai; dashboard básico + métricas de negócio.
13. **Robustez**: teste de integração do fluxo WhatsApp completo; CI rodando
    testes + typecheck das extensões (fechar os 8 erros); reduzir
    `openclaw_request_timeout_sec` para ~60s.
14. **Reduzir dependência do Kali**: replicar as skills de ciberseguraça no
    Contabo ou empacotá-las na imagem do gateway.
15. **Canal Meta**: submeter o app para verificação; declarar o foco do bot no
    `AGENTS.md`.

### FUTURO — vira SaaS multiempresa

16. **Multi-tenancy**: modelo de dados por tenant; roteamento canal/número →
    tenant; isolamento de estado e de credenciais (n8n/gateway/modelo por
    cliente); config por tenant fora do `openclaw.json`.
17. **Onboarding self-service** de cliente (hoje é runbook manual).
18. **HA / escala horizontal** do orquestrador (stateless + Postgres/Redis).
19. **Painel de operação por cliente**; observabilidade e métricas por tenant.
20. **Consolidar o fork OpenClaw** (submodule ou patches versionados) e
    publicar a imagem do gateway via CI.
21. **Governança de modelos**: fallback de provider no orquestrador; avaliação
    contínua (evoluir `eval-router.py`).

---

## 6. Recomendação objetiva do melhor próximo passo

**Fechar o "vertical slice" de UMA empresa antes de tocar em multiempresa**, na
seguinte ordem:

1. **Tapar os furos de segurança do bloco "Agora" (itens 1–4)** — uma sessão.
   É pré-requisito absoluto para qualquer uso com dados de terceiros e destrava
   todo o resto. Sem auth no `/v1/turn`, nada mais deveria avançar.

2. **Resolver o cutover (item 5)** — tomar a decisão binária: o orquestrador
   passa a ser o dono do canal WhatsApp (e aí a orquestração multi-especialista
   finalmente roda em produção e os especialistas n8n/cybersec ganham caminho
   até o usuário), **ou** fica formalmente como serviço interno. Enquanto isso
   estiver ambíguo, metade do sistema não tem propósito operacional e o roadmap
   não fecha.

3. **Construir RAG mínimo + handoff humano (itens 7 e 8)** — são as duas
   lacunas que separam "demo técnica impressionante" de "funcionário digital que
   uma empresa paga". O próprio projeto já concluiu que o diferencial é
   integração com dados reais e execução, não geração de texto.

Multi-tenancy e LGPD-completo ficam explicitamente para **depois de ter 1
cliente real rodando**. Ressalva: no instante em que houver cliente com dados de
terceiros, os três itens mínimos de LGPD (item 11) sobem para "Agora" — retenção
definida, rota de exclusão de titular e PII fora de texto claro não são
negociáveis para produção no Brasil.
