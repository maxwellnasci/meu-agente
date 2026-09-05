# Relatório — O projeto consegue criar fluxos no n8n após a atualização recente?

> Diagnóstico **estritamente somente leitura**. Data: 2026-09-05.
> Nenhum código, configuração, dependência, servidor ou instância de n8n foi
> alterado. Não foi feita nenhuma chamada de rede contra a instância de
> produção. Segredos (`ORCHESTRATOR_N8N_API_KEY`, `ORCHESTRATOR_OPENROUTER_API_KEY`,
> `ORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN`) não são expostos — só nomes de variáveis,
> contratos e o host já presente no código versionado (`n8n.mxos.com.br`).

---

## 1. Conclusão (resposta direta)

**"Pode com ajustes / a confirmar na implantação."**

- **Capacidade declarada:** SIM. O orquestrador tem a tool `N8nCreateWorkflow`
  mapeada 1:1 para `POST /api/v1/workflows` da API pública do n8n, sem nenhum
  guard bloqueando criação.
- **Capacidade configurada localmente:** SIM. `orchestrator/.env` contém
  `ORCHESTRATOR_N8N_URL` e `ORCHESTRATOR_N8N_API_KEY` preenchidos, e existe um
  teste de integração real (`test_create_and_delete_workflow_against_real_n8n_instance`)
  que — segundo o registro do projeto — passou contra a produção em 2026-08-21
  (criou, confirmou, deletou e reconfirmou o sumiço de um workflow descartável).
- **Impacto da "atualização recente":** NENHUM sobre a criação de fluxos. A
  mudança recente no caminho do n8n (commit `8ab3802`, "Orquestra: Tarefa #22
  aprovada") **adicionou apenas uma linha de comentário** em
  `orchestrator/src/orchestrator/graph/n8n_guard.py:37`
  (`# TESTE_CURSOR: validando conexão e edição em tempo real`). É inerte —
  não altera lógica, contrato, endpoint nem autenticação.
- **O que NÃO consigo confirmar sem sair do modo somente-leitura / sem acesso
  ao servidor Contabo:** (a) se o container do orquestrador em produção tem hoje
  as mesmas variáveis de ambiente e uma API key **ainda válida**; (b) se a
  instância de n8n sofreu um upgrade de versão de fato e, se sim, se a API key
  (inserida manualmente via JWT) sobreviveu a migrações; (c) a versão/compat da
  API pública ao vivo; (d) disponibilidade do modelo do OpenRouter que roda o
  loop do especialista.

---

## 2. Escopo e método

Arquivos lidos (todos sob `orchestrator/src/orchestrator/`, salvo indicado):

| Arquivo | Papel |
|---|---|
| `clients/n8n_client.py` | Client HTTP puro para a API REST pública do n8n |
| `schemas/n8n_tools.py` | 8 tool schemas expostos ao LLM do especialista |
| `graph/n8n_guard.py` | Guard determinístico de ação destrutiva no n8n |
| `graph/cybersec_guard.py` | Guard de infra de produção (especialista cybersec) |
| `graph/nodes.py` | `specialist_n8n_node`, `_run_n8n_tool`, prompts do supervisor/especialistas |
| `graph/builder.py` | Montagem do StateGraph (roteamento do enxame) |
| `schemas/routing.py` | `SpecialistName`, `DispatchSpecialist` |
| `config.py` | `Settings` (`ORCHESTRATOR_*`) |
| `main.py` | Endpoints FastAPI `/v1/turn`, `/tasks/stream` |
| `tests/test_specialist_n8n.py`, `tests/test_n8n_guard.py` | Contratos e regressões |
| `orchestrator/.env` (só nomes de chave), `docker-compose.yml`, `Dockerfile` | Implantação |
| `ANALISE_ATUAL.md`, `CURSOR_INTEGRATION.md`, `docs/ESTADO_ATUAL.md`, memórias do projeto | Contexto da "atualização recente" |

Não executado: nenhum `pytest`, nenhum `curl`/HTTP contra `n8n.mxos.com.br`,
nenhum acesso SSH ao Contabo.

---

## 3. Como a integração n8n está implementada

### 3.1 Caminho de execução (criar um fluxo)

```
POST /v1/turn  (sem autenticação)         main.py
   │  fresh_turn_input(text)  → limpa estado por-tarefa
   ▼
supervisor_node                            nodes.py:225
   │  ChatOpenAI via OpenRouter (settings.router_model = "deepseek/deepseek-chat")
   │  bind_tools([DispatchSpecialist])
   │  → enfileira {"specialist": "n8n", "instructions": "..."} em pending_specialists
   ▼
specialist_n8n_node                        nodes.py:455
   │  loop ReAct manual, máx _N8N_MAX_STEPS = 6
   │  ChatOpenAI(router_model).bind_tools(_N8N_TOOLS)  (8 tools)
   │  para cada tool_call → _run_n8n_tool(...)         nodes.py:410
   │      ├─ check_destructive_n8n_action(name, instructions)   ← guard
   │      └─ N8nCreateWorkflow → client.create_workflow(name, nodes, connections)
   ▼
N8nClient.create_workflow                  n8n_client.py:68
   POST {base_url}/api/v1/workflows
   headers: Accept: application/json, X-N8N-API-KEY: <key>
   body: {"name", "nodes", "connections", "settings": {}}
```

Pontos relevantes:

- **Não há "agente n8n" por trás.** Diferente de `specialist_openclaw` /
  `specialist_cybersec` (que delegam a um agent do gateway via
  `/v1/chat/completions`), o tool-calling do n8n roda **dentro do nó do
  orquestrador**, contra a API REST crua. Depende de: (1) o LLM do OpenRouter
  responder; (2) a API do n8n aceitar o request.
- **`create_workflow` sempre envia `settings: {}`** (n8n_client.py:69). O corpo
  tem exatamente `name`, `nodes`, `connections`, `settings` — não envia `active`
  (campo read-only na API pública; enviá-lo causaria 400 em versões recentes).
  Isso está **alinhado ao schema documentado** da API pública.
- **Retry:** `tenacity`, 3 tentativas, **só** em `httpx.ConnectError` /
  `ConnectTimeout` (conexão nunca estabelecida → seguro repetir mesmo em
  POST/DELETE). Timeout de leitura **não** dispara retry — evita duplicar
  efeito colateral. Timeout: `settings.n8n_request_timeout_sec = 30`.
- **Erros HTTP/rede** viram `{"error": "..."}` e voltam como `ToolMessage` para
  o LLM decidir o próximo passo — não estouram o nó (nodes.py:449-452).
- **Fallback do `/v1/turn`:** qualquer falha/timeout (`turn_timeout_sec = 150`)
  vira HTTP 200 com _"Desculpa, tive um problema..."_. Ou seja: se a criação
  falhar, o usuário do WhatsApp recebe uma mensagem genérica, não o erro real
  (comportamento já observado no bug do trigger — memória `project_n8n_specialist_trigger_fix`).

### 3.2 System prompt do especialista (`_N8N_SYSTEM_PROMPT`, nodes.py:61)

Contém 3 regras técnicas que aumentam a chance de a criação **ativável** dar
certo:

- **REGRA DE CAUTELA:** só edita/desativa/deleta/dispara workflow pré-existente
  se a instrução pedir explicitamente. Criar é liberado.
- **REGRA DE TRIGGER:** primeiro node precisa ser um *trigger* real
  (`scheduleTrigger`, `webhook`, `rssFeedReadTrigger`...) e não a variante
  "action", senão a ativação falha com _"must have at least one trigger node"_
  ou 400. (Foi exatamente o bug corrigido no commit `59bfeba`.)
- **REGRA DO BÁSICO:** pedido vago ("cria algo simples") ⇒ trigger real + ação
  simples, nunca `noOp → noOp` sem trigger.

### 3.3 Supervisor (`_SUPERVISOR_SYSTEM_PROMPT`, nodes.py:148)

- "Pergunta indireta = pedido" ("você consegue criar X?" ⇒ despacha, não só
  descreve) — corrigido no commit `1dd1fa0`.
- Descreve o especialista n8n como capaz de "**cria**, edita, deleta,
  ativa/desativa e dispara execução de workflows".
- Recomenda cautela **só** para mexer em workflows que já existiam antes da
  tarefa. **Criar não é desencorajado.**

---

## 4. Operações suportadas: declarada × configurada × verificada ao vivo

| Operação | Tool / método | Endpoint real | Guard bloqueia? | Declarada | Configurada (.env local) | Verificada ao vivo (registro do projeto) |
|---|---|---|---|---|---|---|
| Listar | `N8nListWorkflows` → `list_workflows` | `GET /api/v1/workflows` | Não | ✅ | ✅ | ✅ (2026-08-20/21) |
| Consultar | `N8nGetWorkflow` → `get_workflow` | `GET /api/v1/workflows/{id}` | Não | ✅ | ✅ | ✅ |
| **Criar** | `N8nCreateWorkflow` → `create_workflow` | `POST /api/v1/workflows` | **Não** | ✅ | ✅ | ✅ (create+delete isolado, 2026-08-21) |
| Atualizar | `N8nUpdateWorkflow` → `update_workflow` | `PUT /api/v1/workflows/{id}` | Não | ✅ | ✅ | ⚠️ não há registro de teste dedicado |
| Deletar | `N8nDeleteWorkflow` → `delete_workflow` | `DELETE /api/v1/workflows/{id}` | **Sim** (sem verbo explícito) | ✅ | ✅ | ✅ (parte do teste create+delete) |
| Ativar | `N8nActivateWorkflow` → `activate_workflow` | `POST /api/v1/workflows/{id}/activate` | Não | ✅ | ✅ | ⚠️ falhou 2x no teste ao vivo por bug de trigger (corrigido no prompt, `59bfeba`); não há registro de ativação bem-sucedida ponta a ponta |
| Desativar | `N8nDeactivateWorkflow` → `deactivate_workflow` | `POST /api/v1/workflows/{id}/deactivate` | **Sim** (sem verbo explícito) | ✅ | ✅ | ⚠️ não testado ao vivo |
| Executar | `N8nTriggerWebhook` → `trigger_webhook` | `POST /webhook/{path}` ou `/webhook-test/{path}` | Não | ✅ | ✅ | ⚠️ não testado ao vivo |

Observações:

- **Não existe** "executar workflow por ID" na API pública do n8n
  (confirmado no código lendo o `openapi.yml` real dentro do container —
  n8n_client.py:15-21). Disparo de execução só via URL de webhook de um node
  Webhook do próprio workflow. `N8nTriggerWebhook` reflete essa limitação real.
- **Update** e **ativação bem-sucedida** são os pontos com menor cobertura de
  evidência. Criar (o que a pergunta cobre) é o mais bem verificado, mas a
  última verificação ao vivo é de **~15 dias antes** desta análise.

---

## 5. Configuração, endpoint, autenticação e versão/API

### 5.1 Configuração (`config.py` + `orchestrator/.env`)

- `Settings` usa prefixo `ORCHESTRATOR_` e lê `.env`.
- Chaves relevantes **presentes e preenchidas** em `orchestrator/.env`
  (valores não inspecionados):
  `ORCHESTRATOR_N8N_URL`, `ORCHESTRATOR_N8N_API_KEY`,
  `ORCHESTRATOR_OPENROUTER_API_KEY`, `ORCHESTRATOR_OPENCLAW_GATEWAY_URL`,
  `ORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN`.
- `.env` tem permissão `-rw-------` (0600) e `.gitignore` cobre o padrão — não
  está versionado neste checkout.
- **Ressalva de implantação:** `docker-compose.yml` monta `.env` com
  `required: false`. Se o `.env` do host de produção não tiver as duas chaves
  n8n, o client sobe **sem** `X-N8N-API-KEY` (n8n_client.py:37-41 só injeta o
  header se `self._api_key` for truthy) e todo request devolve **401**. Não
  consigo inspecionar o `.env` do Contabo em modo somente-leitura sem acesso ao
  servidor.

### 5.2 Endpoint e autenticação

- Base URL: `settings.n8n_url` (host `n8n.mxos.com.br`, já presente em
  comentários do código versionado; via Nginx Proxy Manager → container n8n
  porta interna 5678).
- Prefixo fixo: `/api/v1` (n8n_client.py:22).
- Auth: header `X-N8N-API-KEY` (n8n_client.py:40) — esquema correto da API
  pública do n8n.
- Segundo a memória do projeto, a API key foi **inserida manualmente** na
  tabela `user_api_keys` do Postgres do n8n (não havia UI/CLI disponível sem a
  senha de login), assinada como JWT HS256 com `jwtSecret` derivado da
  `encryptionKey` do container. **Esse é o ponto frágil frente a um upgrade:**
  uma migração de schema ou mudança na derivação do segredo entre versões pode
  invalidar a key → 401 silencioso (mascarado pelo fallback do `/v1/turn`).

### 5.3 Versão / compatibilidade da API

- O código-fonte referencia a spec `openapi.yml` real (n8n_client.py:15) e a
  memória registra "v2.9.4" para essa spec (isso é a **versão do documento
  OpenAPI**, não a versão do n8n; a versão do n8n em si não está registrada no
  repo — `v2026.6.9` que aparece nos docs é do **OpenClaw**, não do n8n).
- **Não há no repositório nenhuma evidência de que a instância de n8n foi
  atualizada.** A "atualização recente" rastreável nos commits é a **integração
  Orquestra↔Cursor** (`CURSOR_INTEGRATION.md`, commit `2894e35`) e o commit
  automático `8ab3802` gerado por essa ferramenta — que só adicionou um
  comentário. Se houve um upgrade do servidor n8n, ele aconteceu fora deste
  repo e eu não tenho como confirmá-lo aqui.
- **Julgamento sobre o contrato do client:** o corpo enviado em `create`/
  `update` (`name`/`nodes`/`connections`/`settings`, sem `active`, sem
  propriedades extras) é conservador e compatível com o schema da API pública
  do n8n em versões 1.x recentes. O risco de quebra por upgrade está muito mais
  na **autenticação** (key manual) e na **habilitação da Public API**
  (`N8N_PUBLIC_API_DISABLED`) do que no formato do payload.

---

## 6. Guards: como tratam criação e alteração

### 6.1 `n8n_guard.py` — `check_destructive_n8n_action(tool_name, instructions)`

- Escopo **deliberadamente mínimo**: só intercepta `N8nDeleteWorkflow` e
  `N8nDeactivateWorkflow`.
- Para essas, exige que a **instrução original da tarefa** contenha um radical
  de verbo autorizador (`delet`/`apag`/`exclu`/`remov` para delete;
  `desativ`/`pause`/`pausa` para deactivate). Sem isso → retorna `RECUSADO:...`
  que vira `ToolMessage` e a tool **não é executada** (nodes.py:423-425).
- **`N8nCreateWorkflow`, `N8nUpdateWorkflow`, `N8nActivateWorkflow`,
  `N8nTriggerWebhook` passam sempre** — o guard retorna `None` para elas
  (n8n_guard.py:38-39; teste `test_non_destructive_tools_are_never_blocked`).
- Justificativa no próprio módulo: create/update/activate são reversíveis
  (dá para editar de novo ou desativar). O objetivo é só fechar a janela de
  "o LLM decide sozinho apagar/parar algo que ninguém pediu".
- **Limitação conhecida (já registrada em `ANALISE_ATUAL.md`, risco R11):** os
  cues de deactivate não cobrem "desliga", "para", "tira do ar" — essas frases
  passariam pelo guard. Não afeta *criar*, mas afeta a robustez geral.
- A linha `# TESTE_CURSOR: ...` (n8n_guard.py:37) é só um comentário no corpo
  da função — **sem efeito** sobre a lógica. Higiene pendente (remoção),
  não bug.

### 6.2 `cybersec_guard.py` — `check_production_infra_block(instructions)`

- **Não é chamado no caminho do n8n.** É aplicado apenas em
  `specialist_cybersec_node` (bloqueia o especialista de segurança de
  escanear/pentestear a infra de produção própria — Contabo, Amigão, n8n,
  chatwoot, evolution-api, WhatsApp Cloud).
- A palavra `n8n` **sozinha não está** na lista `_PRODUCTION_INFRA_KEYWORDS`
  (comentário em cybersec_guard.py:74: "nome de ferramenta genérica" — só
  bloqueia quando aparece junto de termo que amarra à produção própria).
- Efeito prático: criar um fluxo no n8n via `specialist_n8n` **não passa por
  nenhuma verificação do `cybersec_guard`**. O risco que o `cybersec_guard`
  cobre é o inverso — impedir que o *especialista de segurança* ataque a
  própria instância de n8n.

### 6.3 Bloqueios, riscos e pré-requisitos

**Bloqueios que impediriam a criação:**

| # | Bloqueio | Onde | Como detectar |
|---|---|---|---|
| B1 | `.env` de produção sem `ORCHESTRATOR_N8N_URL`/`_API_KEY` | container do orquestrador | `docker exec <orch> env \| grep -c ORCHESTRATOR_N8N` (2 = ok) |
| B2 | API key inválida/revogada (upgrade do n8n, migração, rotação) | tabela `user_api_keys` do n8n | `GET /api/v1/workflows?limit=1` → 401 vs 200 |
| B3 | Public API do n8n desabilitada | env do container n8n (`N8N_PUBLIC_API_DISABLED`) | qualquer `/api/v1/*` → 404/403 |
| B4 | Modelo do OpenRouter (`deepseek/deepseek-chat`) indisponível / sem crédito | loop do especialista | `[n8n] ERRO: falha ao invocar o LLM...` no `docker logs` |
| B5 | Supervisor não despacha (classifica como conversa) | `supervisor_node` | rota `general` no stream / sem `[n8n]` no scratchpad |
| B6 | Rede: orquestrador não resolve o host do n8n | container / DNS | `httpx.ConnectError` após 3 retries |

**Riscos (não bloqueiam, mas degradam):**

- Falha silenciosa: erro real do n8n é mascarado pelo fallback do `/v1/turn`
  ("tive um problema"). Para diagnosticar é preciso `docker logs` do
  orquestrador (linha `specialist_n8n_node: concluido em ...ms, sucesso=...`)
  ou o scratchpad via `/tasks/stream`.
- Workflow criado nasce **inativo**; a etapa de **ativação** tem histórico de
  falhar (regra de trigger). Criar ≠ ativar.
- `/v1/turn` e `/tasks/stream` **sem autenticação** (risco R1 do
  `ANALISE_ATUAL.md`): qualquer processo em localhost/LAN do host dispara o
  grafo e, portanto, cria workflows reais no n8n de produção.
- `_N8N_MAX_STEPS = 6`: workflows com muitos nós / muitas correções de trigger
  podem estourar o limite e reportar erro sem concluir.

**Pré-requisitos para uma criação bem-sucedida:**

1. `.env` do container em produção com as 2 chaves n8n + chave OpenRouter com crédito.
2. API key do n8n válida (sobreviveu a qualquer upgrade).
3. Public API do n8n habilitada.
4. Conectividade orquestrador → `n8n.mxos.com.br` (ou nome de serviço interno).
5. Instrução que o supervisor classifique como pedido de ação concreta.

---

## 7. Teste seguro proposto (NÃO executado — não cria nenhum workflow)

Ordem do menos ao mais invasivo. **Parar no primeiro passo que falhar** e
tratar a causa. Nenhum passo cria, edita, ativa, desativa ou deleta workflow.

### Passo 0 — Confirmar o estado da implantação (sem tocar no n8n)
```
docker ps --filter name=orchestrator
docker exec <orchestrator> sh -lc 'env | grep -o "ORCHESTRATOR_N8N_URL\|ORCHESTRATOR_N8N_API_KEY\|ORCHESTRATOR_OPENROUTER_API_KEY" | sort -u'
```
Esperado: as 3 variáveis presentes (só os nomes; não imprimir valores).

### Passo 1 — Health do orquestrador
```
curl -s http://127.0.0.1:8000/health
```
Esperado: `{"status":"ok"}`.

### Passo 2 — Rodar só a suíte de testes offline do n8n (mocks, sem rede)
```
cd orchestrator && .venv/bin/python -m pytest tests/test_n8n_guard.py tests/test_specialist_n8n.py -q \
  -k "not real_n8n_instance"
```
Esperado: todos passam. Confirma que o contrato de tool-calling e os guards
não regrediram com a "atualização recente".

### Passo 3 — Checagem de autenticação/versão da API pública (somente leitura)
> Isto **lê** o n8n de produção (1 request GET idempotente, sem efeito
> colateral). Executar **somente com autorização explícita do Max** — a
> instância é infra de produção.
```
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "X-N8N-API-KEY: $ORCHESTRATOR_N8N_API_KEY" \
  "$ORCHESTRATOR_N8N_URL/api/v1/workflows?limit=1"
```
- `200` → auth ok, Public API habilitada, API v1 compatível. **Criar deve funcionar.**
- `401` → API key inválida (provável efeito de upgrade / rotação) → bloqueio B2.
- `404`/`403` → Public API desabilitada → bloqueio B3.
- erro de conexão → bloqueio B6.

### Passo 4 — Teste de integração real do repo, restrito a criar+deletar isolado
> Já existe e é seguro: nome único via `uuid4`, cria → confirma → **deleta** →
> reconfirma sumiço. Não toca em nenhum workflow existente. Ainda assim,
> **rodar só com autorização do Max** por ser contra produção.
```
cd orchestrator && .venv/bin/python -m pytest \
  tests/test_specialist_n8n.py::test_create_and_delete_workflow_against_real_n8n_instance -q
```
Esperado: passa. É a prova ponta a ponta de que o `N8nClient` cria de verdade
contra a instância atual.

### Passo 5 (opcional) — Fluxo completo pelo grafo, em modo consulta
Enviar a `/tasks/stream` uma instrução **explicitamente somente-leitura**
(ex.: _"liste os workflows existentes no n8n e me diga quantos estão ativos,
sem criar, editar nem alterar nada"_) e observar no stream se aparece
`[n8n] ...` no scratchpad com a listagem. Valida supervisor → despacho →
especialista → `list_workflows` sem nenhum efeito colateral.

**Só depois** de 0–5 verdes, um teste de criação real (com um workflow
descartável e um plano de exclusão imediata) seria de baixo risco — mas isso
está **fora do escopo** deste relatório e não deve ser feito sem pedido
explícito.

---

## 8. Limitações desta verificação

- Modo somente-leitura + sem acesso ao host Contabo: não inspecionei o `.env`
  nem os containers em produção, nem a tabela `user_api_keys` do n8n.
- Nenhuma chamada de rede contra `n8n.mxos.com.br` foi feita — a compatibilidade
  "ao vivo" (versão, auth, Public API habilitada) é **inferida do código e dos
  registros do projeto**, não medida agora.
- A última evidência de criação real bem-sucedida é de **2026-08-21** (~15 dias
  antes desta análise); qualquer mudança de infra depois disso não está coberta.
- "Atualização recente" foi interpretada como a integração Orquestra↔Cursor /
  commit `8ab3802` (a única rastreável no repo). Se o Max se refere a um
  **upgrade da instância de n8n**, esse evento não está registrado no
  repositório e a resposta para ele é **"não posso confirmar"** até rodar o
  Passo 3.
- Não avaliei o especialista de automação em Python (fora do escopo n8n).

---

## 9. Evidências (referências de código)

- `orchestrator/src/orchestrator/clients/n8n_client.py:68` — `create_workflow`, `POST /api/v1/workflows`, corpo `{name,nodes,connections,settings}`.
- `orchestrator/src/orchestrator/clients/n8n_client.py:15-22` — comentário confirmando ausência de "executar workflow por ID" na API pública; prefixo `/api/v1`.
- `orchestrator/src/orchestrator/graph/n8n_guard.py:19-22` — só `N8nDeleteWorkflow`/`N8nDeactivateWorkflow` são cues destrutivos; create/update/activate liberados.
- `orchestrator/src/orchestrator/graph/n8n_guard.py:37` — comentário `TESTE_CURSOR` (inerte, higiene pendente).
- `orchestrator/src/orchestrator/graph/nodes.py:423-448` — `_run_n8n_tool`: guard antes de executar; despacho para cada método do client.
- `orchestrator/src/orchestrator/graph/nodes.py:61-99` — `_N8N_SYSTEM_PROMPT` (regras de cautela / trigger / básico).
- `orchestrator/src/orchestrator/graph/cybersec_guard.py:65-76` — `n8n` sozinho fora das keywords de infra; guard só no caminho cybersec.
- `orchestrator/src/orchestrator/config.py:24-29` — `n8n_url`/`n8n_api_key`/`n8n_request_timeout_sec`.
- `orchestrator/src/orchestrator/main.py:82-109` — `/v1/turn` sem auth, fallback HTTP 200 mascara erro.
- `orchestrator/tests/test_specialist_n8n.py:158-189` — teste de integração real create+delete (skip sem credenciais).
- `orchestrator/tests/test_n8n_guard.py:5-8` — `N8nCreateWorkflow` nunca bloqueado.
- `git show 8ab3802` — "Tarefa #22 aprovada": 1 arquivo, 1 linha (+comentário) em `n8n_guard.py`.
- `ANALISE_ATUAL.md` (2026-09-02), riscos R1/R11 e item de higiene 6; memórias `project_orchestrator_n8n_specialist_criado`, `project_n8n_specialist_trigger_fix`.
