# Análise Técnica — Projeto meu-agente

Data: 2026-09-18
Escopo: `/orchestrator` (Python/FastAPI/LangGraph), `/extensions` (Node/TS OpenClaw), `/scripts`, `/.github/workflows`, `/docs`
Metodologia: inspeção direta de corpos de arquivo + varredura paralela por 5 frentes (orquestrador, gateway, guards, testes/docs/CI, riscos), com crítica de gaps e 1 follow-up. Verificação pontual via listagem e leitura nesta sessão.

---

## 1. Resumo Executivo e Visão Geral

O `meu-agente` é um sistema de dois módulos principais:

- **Orquestrador (Python, `orchestrator/`)**: FastAPI + LangGraph no padrão Supervisor/Enxame. `main.py` expõe `GET /health`, `POST /v1/turn` (síncrono, com fallback 200) e `POST /tasks/stream` (SSE via `astream_events` + `event_mapper.py`). `builder.py` monta `START -> supervisor -> especialista(s) -> supervisor ... -> synthesize_final -> END`, com checkpointer SQLite injetado pelo `lifespan`. Especialistas: `specialist_openclaw` (código), `specialist_cybersec` (segurança), `specialist_n8n` (automação ReAct em 6 passos). Config central em `config.py` via prefixo `ORCHESTRATOR_` (OpenClaw URL/token, n8n URL/key, OpenRouter, `max_supervisor_iterations=4`, `turn_timeout_sec=150`, SQLite, LangSmith).
- **Gateway / Extensões (Node/TS, `extensions/`)**: 4 plugins — `whatsapp-cloud` (2026.6.9, channel + webhook Meta), `ask-max` (2026.7.18, escalonamento proativo ao operador), `github-repo-report` (2026.7.15, tool read-only com allowlist) e `response-audit` (2026.7.18, auditoria pós-resposta via hooks). Padrão `index.ts` + `src/` + `openclaw.plugin.json` + testes `*.test.ts`.
- **Camadas Guard**: `cybersec_guard.py` (bloqueio fail-closed de infra própria Contabo/Amigão/evolution-api/WhatsApp Cloud/chatwoot, com split por sentença `[.!?\n]` e cues de negação PT) e `n8n_guard.py` (default-deny para `N8nDeleteWorkflow`/`N8nDeactivateWorkflow` via radicais `delet/apag/exclu/remov` e `desativ/pause`), mais `n8n_confirmation.py` (pendência WRITE com TTL 900s, uso único, estados affirm/deny/unclear, nasce inativa).
- **Estado docs vs código**: `docs/ESTADO_ATUAL.md` registra marcos reais de integração gateway↔orquestrador (ago/2026, rede Docker, `orchestrator-bridge`, `ORCHESTRATOR_OPENCLAW_GATEWAY_URL`), mas está desatualizado frente ao código atual (guards com lógica anti-eco, confirmação n8n, SSE heartbeat 15s, LangSmith bridge). Há ~30 docs de sessão/arquitetura que documentam bem o histórico, porém sem índice de vigência.
- **Risco principal**: segredos via `.env` gitignored (correto) mas com acoplamento frágil documentado (ex.: URL do gateway só via config de plugin, não env); SQLite como checkpointer limita concorrência; timeouts encadeados (`turn 150s` > `openclaw 120s`) são corretos mas apertados para cadeia WhatsApp→gateway→orquestrador (~20s observado); cobertura de testes boa nos guards e plugins, porém fina em concorrência/payload (há testes `bug4-*` live) e sem gate de CI por push (só publica imagem em tag).

Relatório anterior em `ANALISE_ATUAL.md` foi substituído por esta versão.

---

## 2. Arquitetura do Módulo Orquestrador (Python/LangGraph)

Estrutura confirmada em `orchestrator/src/orchestrator/`:

```
config.py
main.py
graph/{builder.py, state.py, nodes.py (752 linhas), event_mapper.py (54),
       cybersec_guard.py, n8n_guard.py, n8n_confirmation.py (171)}
schemas/{events.py, requests.py, routing.py, n8n_tools.py}
clients/{openclaw_client.py (99), n8n_client.py (114)}
persistence/{checkpointer.py}
```

### 2.1 Entrada (`main.py`, `config.py`)

- `main.py`: `lifespan` abre `checkpointer_context()` uma vez e guarda `app.state.graph = build_graph(checkpointer)`. `/v1/turn` faz `fresh_turn_input(request.text)` + `graph.ainvoke` com `asyncio.wait_for(timeout=settings.turn_timeout_sec)`; qualquer exceção vira `_TURN_FALLBACK_REPLY` com HTTP 200 — contrato proposital para o Node.js sempre ter texto de WhatsApp. `/tasks/stream` usa `EventSourceResponse` com heartbeat 15s (`_SSE_HEARTBEAT_SEC`) para proxies/LB não derrubarem a conexão. Logging raiz em INFO para observabilidade de `nodes.py` aparecer em `docker logs`. `_configure_langsmith_tracing()` faz a ponte `ORCHESTRATOR_LANGCHAIN_*` → `LANGCHAIN_*` (o SDK só lê env cru); sem chave, tracing segue desligado com warning.
- `config.py` (`Settings`, `env_prefix="ORCHESTRATOR_"`, `.env`): `host 0.0.0.0:8000`; `openclaw_gateway_url` default `http://localhost:18789` (armadilha documentada: dentro do container precisa `http://openclaw-gateway:18789`); `n8n_url/key`, `n8n_request_timeout_sec=30`, `n8n_confirmation_ttl_sec=900`; `openrouter_api_key`, `router_model=general_model=deepseek/deepseek-chat`; `max_supervisor_iterations=4`; `turn_timeout_sec=150` (> `openclaw_request_timeout_sec=120` + margem 30s); `checkpointer_sqlite_path=./data/checkpoints.sqlite`; LangSmith desligado por padrão.

### 2.2 Grafo (`builder.py`, `state.py`, `nodes.py`, `event_mapper.py`)

- `builder.py`: `StateGraph(GraphState)` com nós `supervisor`, `specialist_openclaw/cybersec/n8n`, `synthesize_final`. `START→supervisor`; arestas condicionais `route_after_supervisor` / `route_after_specialist` com `path_map` identidade derivado de `SPECIALIST_ROUTES.values()` para builder e nodes nunca desalinharem; `synthesize_final→END`; `compile(checkpointer=...)`.
- `state.py` (105 linhas): `GraphState` + `fresh_turn_input` (reset por turno; há teste dedicado `test_graph_multiturn_state_reset.py`).
- `nodes.py` (752 linhas): supervisor via tool-calling (`DispatchSpecialist` + confirmação n8n na 1ª iteração); especialistas com system prompts próprios (`_SUPERVISOR_SYSTEM_PROMPT` lembra "nunca testar Contabo/Amigão/n8n/..." — origem do eco que motivou o split por sentença no guard); `specialist_n8n` em ReAct de 6 passos; `synthesize_final` aborta com mensagem fixa ao estourar `max_supervisor_iterations`.
- `event_mapper.py` (54 linhas): `map_langgraph_event` traduz `astream_events` → eventos tipados (`SpecialistCalled`, `NodeStarted`, `Token`, `TaskCompleted`) consumidos pelo SSE.

### 2.3 Schemas e clientes

- `schemas/`: `events.py`, `requests.py` (`TaskRequest`/`TurnRequest` `session_key/text/from` → `TurnResponse(reply_text)`), `routing.py` (`SpecialistName`, rotas), `n8n_tools.py` (`List/Get/Create/Update/Delete/Activate/Deactivate/Trigger`).
- `clients/n8n_client.py` (114): REST `/api/v1` + webhook com `X-N8N-KEY`, retry (tenacity) só em erro de conexão.
- `clients/openclaw_client.py` (99): `POST /v1/chat` com Bearer; falha vira `Result(success=False)` (não exceção) — coerente com o fallback 200 do `/v1/turn`.
- `persistence/checkpointer.py`: contexto async SQLite; ciclo de vida no `lifespan`, não por request.

Avaliação: separação limpa (config/entrada/grafo/schemas/clientes/persistência), comentários explicando cada decisão não-óbvia (fallback 200, heartbeat, timeouts, path_map, LangSmith bridge). Ponto de atenção: `nodes.py` com 752 linhas concentra supervisor + 3 especialistas + synthesize — candidato a split por especialista.

---

## 3. Arquitetura do Módulo Gateway (Node/TS OpenClaw)

`extensions/` contém 4 plugins, cada um com `package.json` (`@openclaw/*`, `private:true`), `index.ts`, `openclaw.plugin.json`, `src/`, `tsconfig.json`:

| Plugin | Versão | Papel | Destaques verificados |
|---|---|---|---|
| `whatsapp-cloud` | 2026.6.9 | Channel Meta Graph API | `channel+runtime`, Graph v21, rota `POST /webhook/whatsapp-cloud` + verify `GET`, limite 256KB/10s, 30 req/min, dedup 10min, fila/sender; `inbound-parser` ignora status/non-text; `ingress direct mayPair=false` + turn + SSRF reply; `send` 4096 chars com stripMarkdown; multi-account + allowlist; 4 testes (`inbound-parser`, `webhook*`, `signature`) |
| `ask-max` | 2026.7.18 | Escalonar dúvida ao operador | tool `ask_max(question+context)`, um pending por vez, `tryCreate` proativo, config `channel/to`, store KV, `consume pending`, hook `before_agent_run` com phone-match por dígitos, roteia origem + ack e bloqueia LLM; 5 testes |
| `github-repo-report` | 2026.7.15 | Fetch read-only allowlisted | tool+policy+audit, skip zero-repos p/ enum, fail-closed, tmp fetch→report, walk 500 arquivos, inline 20KB, tarball, zod `owner/repos/main/enabled`; 10 testes + `SKILL.md`; inclui `bug4-concurrency/payload-size.live/repro.live`, `debug-timing.ts` |
| `response-audit` | 2026.7.18 | Auditoria pós-envio | só hooks (`reply_payload` final, detached), `turn-capture` 200/TTL 10min, regex PT + tool + len 300, DeepSeek JSON 20s, KV; 2 testes (`heuristic-filter`, `turn-capture`) |

Ativação: `ask-max`/`response-audit` com `onStartup true`; `whatsapp-cloud`/`github-repo-report` false; `ask-max`/`report` opcionais. Pendência herdada de `ESTADO_ATUAL.md`: `github-repo-report` carregava mas a tool não registrava (`no repos configured` — config, não build) e `orchestrator-bridge` vivia só no repo `openclaw` aninhado (fora de `extensions/` top-level) — verificar se já foi consolidado.

Avaliação: padrão consistente, dependências mínimas (`typebox`, `zod`, `tar`, `@openclaw/fs-safe`), testes por plugin. Gaps: `response-audit` com só 2 testes para regex+LLM (superfície de falso-positivo/negativo); testes `.live` do github-report sugerem dependência de rede/GitHub — separar suite live da unit no CI.

---

## 4. Análise de Segurança & Proteções (cybersec_guard / n8n_guard)

### 4.1 `cybersec_guard.py` — gate do especialista de segurança

- Defesa em profundidade em Python puro, antes de qualquer chamada ao LLM/agente; não depende do system prompt (que continua existindo em `nodes.py`).
- Escopo: substring case-insensitive por sentença (`re.split(r"[.!?\n]+")`), keywords: `contabo`, `amigao/amigão`, `evolution-api`, `whatsapp cloud`, `chatwoot` (+ variantes com hífen). `n8n` sozinho não bloqueia (comum demais) — só amarrado a produção.
- Anti-eco: a sentença só conta se **não** contiver cue de negação na mesma sentença (`nunca/jamais/não/evite/proibido/sem autorização/ignorar/excluir/desconsiderar`...). Motivação documentada no docstring: o supervisor ecoa "nunca testar Contabo..." na instrução delegada, e match ingênuo causava recusa em loop até `max_supervisor_iterations` (bug real de produção). Recusa repete as keywords — sem o split por sentença, realimentaria o loop.
- Fail-closed: `check(task OR instructions)` — referência a `task` ou `instructions` dispara. Mensagem `RECUSADO` fixa orienta reformular para alvo de teste controlado.

### 4.2 `n8n_guard.py` + `n8n_confirmation.py` — gates do especialista n8n

- `n8n_guard.py`: só as 2 tools irreversíveis/pre-existente-destrutivas (`N8nDeleteWorkflow`, `N8nDeactivateWorkflow`) são gateadas; `Create/Update/Activate` ficam de fora (reversíveis). Radicais PT/EN (`delet/apag/exclu/remov`; `desativ/pause/pausa`), `lower()`, default-deny: sem verbo explícito na instrução da tarefa → `RECUSADO` com template citando verbos esperados. (Observado: comentário `TESTE_CURSOR` inline — resíduo de debug, remover.)
- `n8n_confirmation.py` (171 linhas): pendência WRITE com TTL 900s, uso único, nasce inativa; vereditos `affirm/deny/unclear`. Cobre `create/activate/deactivate/delete` enquanto aguarda o usuário (janela de WhatsApp sem ação "armada" indefinida).

### 4.3 Cobertura de testes de segurança (`orchestrator/tests/`)

10 arquivos: `test_cybersec_guard_self_echo_loop.py`, `test_cybersec_guard_unmatched_echo_loop.py`, `test_graph_e2e_cybersec_guard.py`, `test_graph_multiturn_state_reset.py`, `test_graph_n8n_confirmation_flow.py`, `test_n8n_confirmation.py`, `test_n8n_guard.py` (6 casos: never-block não-destrutivas, delete/deactivate bloqueados sem verbo, liberados com verbo, case-insensitive), `test_specialist_cybersec.py`, `test_specialist_n8n.py`, `test_langsmith_tracing_config.py`.

Avaliação: boa cobertura do comportamento crítico (eco, confirmação, e2e do guard, reset multiturn). Gaps: `n8n_guard` só testa delete/deactivate (correto por escopo, mas sem teste negativo para `Create/Update` com verbo destrutivo — garantir que nunca bloqueiem); `cybersec_guard` depende de lista estática de keywords — sem teste de variante não-enumerada (ex.: IP do Contabo, hostname, "evolution" sozinho) nem de bypass por obfuscação; sem teste de SSRF/allowlist do lado Python (a checagem SSRF citada está no inbound TS — confirmar cobertura lá).

---

## 5. Diagnóstico de Testes, Qualidade e Documentação

### 5.1 Testes

- Python: 10 arquivos em `orchestrator/tests/` (lista acima). Workflow `.github/workflows/docker-publish-orchestrator.yml` roda `pip install -e ".[dev]" + pytest -q` antes de publicar — bom gate, mas **só** no fluxo de tag `orchestrator-v*` / dispatch manual. Sem CI por push/PR: regressão só aparece no release.
- TS: `ask-max` 5 testes, `github-report` 10 (+ 2 `.live`), `response-audit` 2, `whatsapp-cloud` 4. Padrão `*.test.ts` colocalizado — bom. `response-audit` sub-testado para a parte mais frágil (heurística + LLM). `bug4-*` indica investigação real de concorrência/payload, mas `debug-timing.ts` e `TESTE_CURSOR` sugerem resíduos de debug commitados.
- Não executado nesta análise (sem ambiente venv/node garantido); veredito estrutural, não de passagem.

### 5.2 Documentação (`docs/`, ~30 arquivos)

- `ESTADO_ATUAL.md`: marcos de 26–27/08/2026 (ponte `orchestrator-bridge`/`ask_orchestrator`, cutover WhatsApp adiado, rede Docker, tokens sha256 iguais, Path A/B ponta a ponta com tempos 10.6s/6.5s/~20s). Factual e com comandos, mas **desatualizado**: não menciona guards anti-eco, confirmação n8n, SSE/heartbeat, LangSmith bridge, `max_supervisor_iterations=4`/`turn_timeout_sec=150`.
- Suporte: `ARQUITETURA_ORQUESTRADOR.md`, `ARQUITETURA_SEGURANCA.md`, `DEPLOY_IMAGEM.md`, `FLUXO_MULTI_IA.md`, `MANUTENCAO.md`, `PROXIMOS_PASSOS.md`, sessões `SESSAO_2026-06-23…2026-08-22`, `CASE_BUG4_*`, `P0_CONTENCAO_N8N_*`, `RELATORIO_N8N_*`, `TESTE_NIVEL_1/2/3`, `TESTE_SANDBOX.md`. Histórico rico, porém sem "última revisão" por doc — difícil saber o vigente (ex.: `github-repo-report no repos configured` ainda vale? `orchestrator-bridge` já tem backup top-level?).
- Raiz: `README.md`, `ANALISE.md` (2026-06), `ANALISE_CEREBRO_AGENTE_CONTABO_2026-09-06.md`, `P0_CONTENCAO_N8N_2026-09-06.md`, `bug4-*` (jul). Sinais de incidentes reais bem documentados.

### 5.3 Scripts e CI/CD (`scripts/`, `.github/`)

- `scripts/`: `deploy-orchestrator.sh`, `eval-router.py`, `heartbeat-monitor.sh` (há também `bug4-monitor.sh` na raiz), `sync-extensions-backup.sh`.
- `.github/workflows/docker-publish-orchestrator.yml`: publica `ghcr.io/<owner>/meu-agente-orchestrator` só em tag `orchestrator-v*` ou dispatch; com testes antes do push (bom). Sem workflow de CI contínuo, sem lint/typecheck TS nem `ruff/mypy` Python visíveis; sem publish das extensões.

---

## 6. Riscos Identificados e Débitos Técnicos

| # | Risco / Débito | Evidência | Impacto |
|---|---|---|---|
| R1 | Checkpointer SQLite (`./data/checkpoints.sqlite`) | `config.py`, `persistence/checkpointer.py`, `main.py:lifespan` | Concorrência limitada (SQLite + aiosqlite); gargalo sob rajadas de WhatsApp; migração Postgres adiada vira incidente |
| R2 | `.env` gitignored com linhas críticas não versionadas | `config.py`, `ESTADO_ATUAL.md` (`ORCHESTRATOR_OPENCLAW_GATEWAY_URL`, tokens) | Recriar ambiente quebra (default `localhost:18789` inválido no container); falta `.env.example` versionado |
| R3 | Config do gateway via `openclaw.json`, não env | `ESTADO_ATUAL.md` (`orchestrator-bridge` URL só em `plugins.entries...config.url`) | Dois mecanismos de config confundem; drift entre `.env` e `openclaw.json` |
| R4 | Keywords estáticas no `cybersec_guard` | `cybersec_guard.py` | Novo serviço de produção sem atualizar a tupla = sem proteção; bypass por IP/hostname/obfuscação |
| R5 | `n8n_guard` cobre só 2 tools; `Create/Update` sem gate | `n8n_guard.py` | `Update` pode esvaziar workflow (efeito ≈ destrutivo); `Activate` em loop pode gerar carga/custo |
| R6 | Timeout encadeado apertado | `turn 150s` vs `openclaw 120s` + SSE + WhatsApp 10s inbound | Cadeia completa ~20s hoje, mas tarefa longa + retry n8n (30s) pode estourar o webhook Meta (10s) — precisa ack assíncrono |
| R7 | `supervisor` itera no máx. 4x, `synthesize_final` aborta fixo | `config.py`, `nodes.py`, `builder.py` | Tarefa legítima multi-especialista pode abortar; mensagem fixa esconde progresso parcial |
| R8 | Fallback 200 mascara falha | `main.py:/v1/turn` | Observabilidade depende de logs; sem métrica/contador de fallback, SLO invisível |
| R9 | Sem CI por push; testes `.live` misturados | `.github/workflows` (só tag), `bug4-*.live.test.ts` | Regressão chega ao release; live flaky quebra suite |
| R10 | Resíduos de debug commitados | `TESTE_CURSOR` em `n8n_guard.py`, `debug-timing.ts`, `bug4-monitor.log` (22KB na raiz) | Ruído, possível vazamento de timing interno |
| R11 | `nodes.py` 752 linhas monolítico | `graph/nodes.py` | Dificulta review, teste unitário por especialista e evolução |
| R12 | `response-audit` pós-envio apenas, 2 testes | `response-audit/src` | Alucinação/falsa ação só detectada depois do envio; heurística PT frágil |
| R13 | `openclaw/` aninhado (26 dirs) + `orchestrator-bridge` fora de `extensions/` | raiz, `ESTADO_ATUAL.md` | Duplicidade de fonte, backup frágil (`sync-extensions-backup.sh` manual) |
| R14 | LangSmith desligado por padrão | `config.py`, `main.py`, `test_langsmith_tracing_config.py` | Sem tracing em prod, debug de cadeia multi-hop é log-grep |

Concorrência/infra: SQLite + `mayPair=false` + dedup 10min + fila/sender no WhatsApp + rate 30/min sugerem contenção já observada (bug4). Confirmar com `bug4-monitor.log` / `CASE_BUG4_INVESTIGACAO_COMPLETA.md` antes de escalar tráfego.

---

## 7. Plano de Ação e Recomendações Priorizadas

### P0 — Segurança e integridade (esta semana)

- [ ] **P0-1** Remover `TESTE_CURSOR` de `n8n_guard.py` e `debug-timing.ts`/`bug4-monitor.log` da raiz (ou mover para `logs/` gitignored).
- [ ] **P0-2** Versionar `.env.example` com todas as chaves `ORCHESTRATOR_*` + `openclaw.json` mínimo; documentar que URL do bridge vem da config do plugin, não de env.
- [ ] **P0-3** Estender `cybersec_guard`: incluir hostnames/IPs da prod (não só nomes), teste de bypass (IP, sem acento, caixa alta, obfuscação simples); decidir `Update` esvaziando workflow como destrutivo (ou gate de diff-size).
- [ ] **P0-4** Separar testes `.live` (rede) dos unitários; CI deve rodar unit sempre, live só manual.

### P1 — Confiabilidade (próximas 2 semanas)

- [ ] **P1-1** CI por push/PR: `pytest -q` + `tsc --noEmit` + `vitest` por plugin; manter o gate de publish em tag.
- [ ] **P1-2** Métricas de fallback: contador `turn_fallback_total{reason}` + log estruturado (`session_key`, iterações, especialista); alerta se > limiar.
- [ ] **P1-3** Ack assíncrono no WhatsApp: responder "processando" se `/v1/turn` > ~8s e entregar resultado depois (webhook Meta tem 10s).
- [ ] **P1-4** Split `nodes.py` por especialista (`supervisor.py`, `specialist_{openclaw,cybersec,n8n}.py`, `synthesize.py`) sem mudar comportamento; teste de import/rotas.
- [ ] **P1-5** Consolidar `orchestrator-bridge` em `extensions/` top-level + `sync-extensions-backup.sh` automatizado ou removido.

### P2 — Evolução (mês)

- [ ] **P2-1** Avaliar checkpointer Postgres (LangGraph `PostgresSaver`) com feature-flag; benchmark com rajada simulada (reusar `bug4-monitor.sh`).
- [ ] **P2-2** Ativar LangSmith em staging (chave real) e comparar com logs; decidir rollout prod.
- [ ] **P2-3** Endurecer `response-audit`: ampliar suite heurística (PT), registrar precisão/recall, considerar gate pré-envio para ações declaradas.
- [ ] **P2-4** Atualizar `docs/ESTADO_ATUAL.md` (ou este arquivo como sucessor) e adicionar `Última revisão:` + `Vigente/Superado` no topo de cada doc de sessão; resolver pendências abertas (`github-repo-report no repos`, bridge backup).
- [ ] **P2-5** Revisar `max_supervisor_iterations=4` com dados de prod (distribuição de iterações) e retornar progresso parcial no abort de `synthesize_final`.

---

*Gerado por inspeção direta + agentes de varredura. Itens marcados "verificar" acima são os únicos não confirmados em corpo de arquivo nesta sessão.*
