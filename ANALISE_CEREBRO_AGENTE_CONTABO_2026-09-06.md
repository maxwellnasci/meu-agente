# Análise do "cérebro" do agente + incidente n8n de 05/09/2026

> **Modo estritamente somente-leitura.** Nada foi alterado: sem edição de código,
> config, containers, workflows n8n, banco ou dados. No Contabo só rodei comandos
> de inspeção (`docker ps/inspect/logs`, `psql ... SELECT`, leitura de arquivos de
> config). Nenhum segredo é reproduzido aqui — só nomes de variáveis, contratos e
> hosts que já estão no código versionado.
>
> Data da análise: 2026-09-06. Incidente: 2026-09-05, ~20h–20h35 BRT
> (23:11–23:35 UTC nos logs).

---

## 1. Conclusão executiva (a causa mais provável do incidente)

O incidente **não** foi um bug isolado. Foi a soma de **quatro defeitos estruturais**
que já existiam e se alinharam numa conversa real:

1. **O orquestrador (o "cérebro") não tem memória de conversa nenhuma na prática.**
   Cada mensagem do WhatsApp entra como um `POST /v1/turn` independente. O
   `fresh_turn_input()` zera todo o estado por-tarefa e **nenhum nó do grafo lê o
   histórico de mensagens** — o `supervisor`, o especialista e o `synthesize_final`
   enxergam apenas **a última frase do usuário**, isolada. O histórico até é
   persistido no checkpointer SQLite (li 52 mensagens da conversa), mas fica
   **inerte** — ninguém consome.

2. **"Pergunta indireta = pedido de ação" + ambiguidade de "apagar".** O supervisor
   é instruído a tratar frases curtas como comandos. A mensagem **"Me avisa quando
   apagar"** — 4 palavras, sem contexto — foi interpretada como *"crie uma automação
   que me avisa quando o sistema for **desligado**/reiniciado"* ("apagar" ≡
   "desligar" em PT). Resultado: o especialista n8n **criou e ativou** o workflow
   `Z4NOaIGb6558Dmz3` "Notificação de Desligamento/Reinicialização" (webhook
   `shutdown-event` → set → e-mail), em produção, sem confirmação.

3. **Nenhuma ação é confirmada e "criar" não passa por guard nenhum.** O
   `n8n_guard` só bloqueia `delete`/`deactivate`. `create`/`update`/`activate`
   passam sempre. Não há passo de confirmação humana para nada.

4. **O pedido de apagar nunca virou uma ação de apagar.** A mensagem "pode apagar
   esse fluxo que vc acabou de criar" foi classificada como **conversa** (`rota
   general`, sem despachar especialista) — o `synthesize_final` respondeu *"Claro!
   Vou apagar o fluxo"* como **texto puro, sem executar nada** (não há `DELETE` em
   nenhum log). Mesmo se tivesse despachado, o especialista não tinha o ID do
   workflow (sem histórico) e teria só listado.

**Sequência reconstruída (evidências na seção 6):**

| Hora (UTC) | Mensagem do usuário | O que o cérebro fez | Efeito real no n8n |
|---|---|---|---|
| 23:18 | "Eu queria um fluxo de n8n básico para testar…" | despacha n8n → `POST /workflows` | cria `pEVM1SI5Pxavc0JM` "Fluxo Básico de Teste" (webhook+set, **inativo**) |
| 23:21 | "…**pode apagar esse fluxo** que vc acabou de criar" | `rota general`, **não despacha** | **nada** — respondeu "Vou apagar" sem apagar |
| 23:22 | "**Me avisa quando apagar**" | despacha n8n → `POST /workflows` + `/activate` | **cria e ATIVA** `Z4NOaIGb6558Dmz3` "Notificação de Desligamento/Reinicialização" |
| 23:23:57 | *(usuário recebe "Desculpa, tive um problema…")* | turn levou 94 s; **cliente WhatsApp desistiu aos 95 s** | workflow **já tinha sido criado e ativado** — ação fantasma |
| 23:24–23:35 | "Vc criou algum fluxo?", "esse último oq faz", "como eu uso isso" | `rota general` / lista; **sem contexto** | agente responde "não consegui identificar 'esse último'" / genérico |

O workflow indevido **`Z4NOaIGb6558Dmz3` continua ATIVO hoje** (0 execuções, é
webhook — fica só à espera). O `pEVM1SI5Pxavc0JM` continua inativo. **Nenhum
workflow foi deletado.**

> Causa-raiz única, em uma frase: **o cérebro é stateless por mensagem, trata
> qualquer frase como ordem, cria sem confirmar e não tem como resolver
> referências do tipo "esse fluxo" — então "me avisa quando apagar" virou um
> workflow ativo de produção, e todas as mensagens seguintes começaram do zero.**

---

## 2. Como funciona o "cérebro" hoje

### 2.1 Componentes

| Componente | Papel | Onde roda |
|---|---|---|
| **OpenClaw gateway** (`openclaw:local-sandboxed-v3`) | Runtime de canais + sandbox de execução. Recebe o webhook do WhatsApp. | Contabo, container `openclaw-openclaw-gateway-1` |
| **Plugin `whatsapp-cloud`** (extensão própria) | Valida assinatura Meta, autoriza remetente, **e faz o handoff direto pro orquestrador** | dentro do gateway |
| **Orquestrador** (Python, LangGraph + FastAPI) | O "cérebro": supervisor + enxame de especialistas + síntese da resposta | Contabo, container `meu-agente-orchestrator-orchestrator-1` |
| **Especialistas** | `openclaw` (código, delega ao gateway), `cybersec` (delega ao gateway c/ prompt hardened), `n8n` (tool-calling REST **dentro do próprio nó**) | dentro do orquestrador |
| **n8n** (`n8nio/n8n:latest`, **v2.9.4**) + Postgres 15 | Instância de automação em produção (`n8n.mxos.com.br`) | Contabo, containers `n8n` / `n8n-postgres` |
| **OpenRouter** (`deepseek/deepseek-chat`) | LLM do supervisor, do especialista n8n e da síntese | externo |
| **LangSmith** (projeto `orchestrator-portfolio`) | Tracing — **está ativo** (chave configurada, confirmado no log de startup) | externo |

### 2.2 O grafo (LangGraph)

```
START → supervisor ──cond──> specialist_openclaw ─┐
          │  (fila pending_specialists)            │
          │                    specialist_cybersec ┤─cond─> próximo especialista | volta ao supervisor
          │                    specialist_n8n ─────┘
          └──(fila vazia)──> synthesize_final → END
```

- `supervisor_node` (`graph/nodes.py:225`): chama o LLM com `bind_tools([DispatchSpecialist])`.
  Cada `DispatchSpecialist` vira um item na fila `pending_specialists`. Se o LLM não
  chama tool → `rota general` → resposta direta.
- `specialist_n8n_node` (`graph/nodes.py:455`): loop ReAct manual, máx.
  `_N8N_MAX_STEPS = 6`. LLM com 8 tools n8n → cada tool-call executa de verdade via
  `N8nClient` (REST contra `n8n.mxos.com.br/api/v1`). **Não há "agente n8n" — o
  tool-calling roda no próprio orquestrador.**
- `synthesize_final_node` (`graph/nodes.py:550`): compõe a resposta ao usuário a
  partir do `internal_scratchpad` dos especialistas.
- Trava de loop: `max_supervisor_iterations = 4`. Ao estourar, aborta com mensagem
  fixa ("essa tarefa ficou complexa demais…").

### 2.3 Modelos e timeouts (config.py + deploy)

| Parâmetro | Valor | Observação |
|---|---|---|
| `router_model` / `general_model` | `deepseek/deepseek-chat` (via OpenRouter) | sem fallback de provider |
| `turn_timeout_sec` | **150 s** | limite do grafo inteiro em `/v1/turn` |
| `openclaw_request_timeout_sec` | 120 s | chamada ao gateway |
| `n8n_request_timeout_sec` | 30 s | por request REST ao n8n |
| `max_supervisor_iterations` | 4 | |
| `_N8N_MAX_STEPS` | 6 | loop do especialista n8n |
| **Timeout do cliente WhatsApp→orquestrador** | **95 s** (`orchestrator-client.ts`) | **menor que os 150 s do orquestrador — ver §6** |

---

## 3. Caminho real de uma mensagem (com evidências do Contabo)

```
[1] WhatsApp (usuário 55 41 8444-5755)
      │  Meta Graph API → webhook POST /webhook/whatsapp-cloud (assinado HMAC)
      ▼
[2] OpenClaw gateway  ·  plugin whatsapp-cloud
      │  extensions/whatsapp-cloud/src/inbound.ts
      │   - authorizeWhatsAppCloudSender (allowlist)
      │   - route = channelRuntime.routing.resolveAgentRoute(...)
      │       → route.sessionKey = "agent:main:direct:554184445755"
      │   - callOrchestratorTurn({ sessionKey, text, from })   ← HANDOFF DIRETO
      │     (NÃO passa pelo agente "main"/Amigão; o pipeline do agente é ignorado
      │      para este canal — a persona "Amigão" e a tool ask_orchestrator ficam
      │      fora do caminho)
      ▼
[3] Orquestrador  ·  POST /v1/turn   (sem autenticação)
      │  main.py:82  · config = { thread_id: session_key }
      │  graph_input = fresh_turn_input(text)   ← zera TUDO menos `messages`
      ▼
[4] supervisor_node  → LLM (OpenRouter deepseek-chat) + DispatchSpecialist
      │  prompt = SÓ a última HumanMessage + scratchpad (vazio no início do turn)
      ▼
[5] fila pending_specialists → specialist_n8n_node (quando é tarefa de automação)
      │  loop ReAct: LLM escolhe tool → _run_n8n_tool → check_destructive_n8n_action
      │  → N8nClient.<método>
      ▼
[6] n8n REST  ·  https://n8n.mxos.com.br/api/v1/workflows[...]
      │  header X-N8N-API-KEY  ·  via nginx-proxy-manager → container n8n:5678
      ▼
[7] volta: scratchpad → supervisor (reavalia) → synthesize_final → LLM
      │  reply_text
      ▼
[8] /v1/turn responde 200 { reply_text }
      │  (se o grafo falha/estoura 150 s → 200 com "Desculpa, tive um problema…")
      ▼
[9] inbound.ts → sendWhatsAppCloudReply → Meta Graph API → usuário
      │  SE callOrchestratorTurn lançou (timeout de 95 s OU orquestrador fora do ar):
      │  usuário recebe ORCHESTRATOR_UNREACHABLE_FALLBACK_TEXT
      │  ("Desculpa, tive um problema para processar sua mensagem agora…")
```

**Provas coletadas no Contabo:**

- Handoff direto confirmado — log do gateway:
  `2026-09-05T23:23:57 [whatsapp-cloud] Orchestrator turn failed for 554184445755:
  Failed to reach Orchestrator at http://meu-agente-orchestrator-orchestrator-1:8000/v1/turn`
  (o texto e o remetente são exatamente os de `inbound.ts`).
- Caller do `/v1/turn` = `172.22.0.2` = **o próprio gateway** (`docker network
  inspect openclaw_default`). Confirma que o agente não é intermediário.
- `openclaw.json`: `bindings: [{ match:{channel:"whatsapp-cloud"}, agentId:"main" }]`
  e `plugins.entries.orchestrator-bridge.config.url =
  http://meu-agente-orchestrator-orchestrator-1:8000/v1/turn`. A binding pro agente
  "main" ainda existe, mas o `inbound.ts` curto-circuita antes de o agente rodar.
- `ORCHESTRATOR_URL=http://meu-agente-orchestrator-orchestrator-1:8000` no env do
  gateway.

> **Divergência resolvida:** o `ANALISE_ATUAL.md` (02/09) diz que o cutover
> WhatsApp→orquestrador *"foi decidido mas não implementado"* e que o canal ainda
> entrega ao agente `main`. **Isso está desatualizado.** A imagem do gateway em
> produção (buildada 2026-08-26) **já roda o `inbound.ts` com o handoff direto** —
> a "cópia-backup à frente da produção" mencionada no doc, na verdade, **é** a
> produção. Existem duas pontes pro orquestrador no código (o `inbound.ts` direto
> e a tool `ask_orchestrator` do plugin `orchestrator-bridge`); **a que está no
> caminho do WhatsApp é a direta**, e ela não tem persona nem memória própria.

---

## 4. Estado da implantação no Contabo (somente-leitura)

`docker ps` (host `158.220.125.233`, uptime 62 dias):

| Container | Imagem | Estado | Portas |
|---|---|---|---|
| `meu-agente-orchestrator-orchestrator-1` | `meu-agente-orchestrator:local` (criada **2026-08-26 01:48**) | Up 11 dias, **sem healthcheck**, `restart: unless-stopped`, RestartCount 0, **1 worker uvicorn** | `127.0.0.1:8000->8000` |
| `openclaw-openclaw-gateway-1` | `openclaw:local-sandboxed-v3` | Up 11 dias (healthy) | `0.0.0.0:3978->3978`, `127.0.0.1:18789->18789` |
| `openclaw-openclaw-cli-1` | `openclaw:local-sandboxed-v3` | Up 11 dias (healthy) | — |
| `openclaw-sbx-agent-cybersec-2fb5be1b` | `openclaw-sandbox:bookworm-slim` | Up 11 dias | — (sandbox do especialista cybersec) |
| `n8n` | `n8nio/n8n:latest` → **v2.9.4** (started 2026-07-26) | Up 5 semanas | `0.0.0.0:5678->5678` |
| `n8n-postgres` | `postgres:15-alpine` | Up 2 meses (healthy) | `5432` (interno) |
| `nginx-app-1` | `jc21/nginx-proxy-manager` | Up 2 meses | `80/81/443` |
| `mxos-login-web` | `nginx:alpine` | Up 2 meses | `0.0.0.0:9090->80` |

Observações relevantes (sem expor segredos):

- Env do orquestrador **presente e completo**: `ORCHESTRATOR_N8N_URL`,
  `ORCHESTRATOR_N8N_API_KEY`, `ORCHESTRATOR_OPENROUTER_API_KEY`,
  `ORCHESTRATOR_OPENCLAW_GATEWAY_URL/TOKEN`, `ORCHESTRATOR_LANGCHAIN_API_KEY`,
  `ORCHESTRATOR_LANGCHAIN_TRACING_V2`, `ORCHESTRATOR_LANGCHAIN_PROJECT`. Ou seja:
  **a criação de workflow funciona de fato** e **há tracing no LangSmith**.
- A imagem em produção é **anterior** ao commit `8ab3802` (o `n8n_guard.py`
  deployado **não** tem o comentário `# TESTE_CURSOR`). Funcionalmente idêntico ao
  master para o que importa aqui.
- Porta `3978` (MS Teams) e `5678` (n8n) em `0.0.0.0` — exposição de LAN
  desnecessária (já era backlog P1).
- Orquestrador **sem healthcheck e com 1 worker** — um hang não se auto-recupera
  (já era backlog P2). RestartCount 0 desde 26/08 → nunca reiniciou sozinho.

---

## 5. Onde e como o estado de conversa é persistido

### 5.1 O que existe

| Item | Valor real observado |
|---|---|
| **thread_id / session_key** | `agent:main:direct:554184445755` — derivado de `route.sessionKey` (prefixo do agente + tipo + **número de telefone em claro**) |
| **Checkpointer** | `AsyncSqliteSaver` (LangGraph), arquivo `/app/data/checkpoints.sqlite` (montado de `/root/meu-agente-orchestrator/data/`) |
| Tabelas | `checkpoints`, `writes` |
| Volume da conversa do Max | **133 checkpoints**, **52 mensagens** acumuladas num único thread; DB 8 MB + WAL 4 MB |
| Threads no DB | 1 real (`agent:main:direct:554184445755`) + ~11 de teste (`deploy-smoke-test-*`, `eval-router-*`, etc.) |
| **TTL / poda** | **nenhuma** — cresce indefinidamente |
| Reset por reinício | o checkpointer sobrevive a restart (arquivo em volume). O estado por-tarefa é resetado **a cada mensagem** por `fresh_turn_input()`, não por reinício |
| Mapeamento remetente→conversa | 1 número de telefone ⇒ 1 thread_id estável ⇒ 1 histórico |

### 5.2 O problema central: o histórico é gravado mas **nunca lido**

`fresh_turn_input()` (`graph/state.py:80`) — comentário do próprio código:

> *"Só `messages` deve mesmo persistir entre chamadas (é o que dá memória de
> conversa de verdade, via o reducer `add_messages`) — todo o resto aqui é escopo
> 'por tarefa' e precisa começar do zero a cada chamada."*

A **intenção** estava certa. Mas:

- `supervisor_node` monta o prompt com `extract_task_description(state["messages"])`,
  que **retorna só a última `HumanMessage`** (`nodes.py:205-218`). Mais o
  `internal_scratchpad`, que o `fresh_turn_input` **acabou de zerar**.
- `synthesize_final_node` faz **o mesmo**: só a última `HumanMessage` + scratchpad.
- Os especialistas recebem apenas `job["instructions"]` (texto que o **supervisor**
  gerou, também sem histórico).
- **Nenhum nó** passa `state["messages"]` (a lista completa) para o LLM.

Resultado: as 52 mensagens no checkpoint **não influenciam nenhuma decisão nem
nenhuma resposta**. O cérebro é, na prática, **stateless por mensagem** — apesar de
ter um banco de conversa cheio. É por isso que "esse último", "esse fluxo que vc
acabou de criar" e "como eu uso isso" **sempre falham**.

### 5.3 Efeito colateral que já foi corrigido (e por que o resto ficou pra trás)

O `fresh_turn_input` nasceu de um bug real de 24/08: sem reset, `iteration_count`
acumulava entre mensagens e a conversa **travava permanentemente** depois de ~5
mensagens. A correção (resetar tudo menos `messages`) resolveu o *travamento* —
mas ninguém voltou pra **ligar o `messages` na entrada do supervisor/síntese**.
Ficou meio-caminho: não trava mais, mas também não lembra de nada.

---

## 6. Reconstrução do incidente de 05/09 (fatos × hipóteses)

### 6.1 Fatos comprovados (logs + banco)

**Logs do orquestrador (`docker logs`, UTC):**

```
23:11:26  supervisor rodada 1, nenhum especialista (rota=general)      → synthesize (it=1)
23:18:35  supervisor rodada 1, despacha ['n8n']
23:18:48  POST https://n8n.mxos.com.br/api/v1/workflows  200            ← CRIA workflow
23:18:53  specialist_n8n_node concluido 13200ms sucesso=True, 1 acao    → synthesize (it=2)
23:21:49  supervisor rodada 1, nenhum especialista (rota=general)       → synthesize (it=1)   ← "pode apagar esse fluxo"
23:22:23  supervisor rodada 1, despacha ['n8n']
23:22:38  POST .../api/v1/workflows  200                                ← CRIA workflow
23:23:03  POST .../api/v1/workflows/Z4NOaIGb6558Dmz3/activate  200      ← ATIVA workflow
23:23:27  specialist_n8n_node concluido 57029ms sucesso=True, 2 acoes
23:23:57  synthesize_final concluido (it=2)                             ← 94 s depois do início
23:24:36  supervisor rodada 1, nenhum especialista (rota=general)       ← "Vc criou algum fluxo?"
23:25:44  supervisor rodada 1, despacha ['n8n']
23:25:53  GET .../api/v1/workflows?limit=50&active=true  200            ← só LISTA
23:26:09  specialist_n8n_node concluido, 1 acao                         → rota general → synthesize
23:27:26  rota general
23:28:31  despacha ['n8n'] → 23:28:52 GET .../workflows?active=true → só lista → rota general
23:32:47  rota general (lento, ~40 s)
23:35:17  rota general
```

**Log do gateway (única linha de 05/09):**

```
23:23:57.246  [whatsapp-cloud] Orchestrator turn failed for 554184445755:
              Failed to reach Orchestrator at http://meu-agente-orchestrator-orchestrator-1:8000/v1/turn
```

**Banco do n8n (`SELECT` em `workflow_entity`, filtro `createdAt/updatedAt > 2026-09-04`):**

```
pEVM1SI5Pxavc0JM | active=f | 2026-09-05 23:18:47 | "Fluxo Básico de Teste"
Z4NOaIGb6558Dmz3 | active=t | 2026-09-05 23:22:38 | "Notificação de Desligamento/Reinicialização"
```

- `Z4NOaIGb6558Dmz3`: nós = `webhook` → `set` → `emailSend`; webhook path
  `shutdown-event`; **0 execuções**; **ainda ativo hoje**.
- `pEVM1SI5Pxavc0JM`: nós = `webhook` → `set`; inativo.
- **Nenhum `DELETE` em nenhum log. Nenhum workflow foi apagado.**
- Total no n8n hoje: **7 ativos, 12 inativos** (inclui 2 duplicatas "Enviar E-mail
  de Teste" de sessões de agosto, não relacionadas).

**Conversa (52 mensagens lidas do checkpoint) — trecho do incidente, em ordem:**

1. User: *"Eu queria um fluxo de n8n básico para testar o que vc consegui fazer"*
   → AI: *"Criei um fluxo básico… Webhook Trigger… Set Node… ainda inativo"*
   **(= criação de `pEVM1SI5Pxavc0JM`, 23:18)**
2. User: *"Legal só queria saber o que vc pode fazer **pode apagar esse fluxo que
   vc acabou de criar**"* → AI: *"Claro! Vou apagar o fluxo que foi criado…"*
   **(rota general às 23:21 — NENHUMA ação; resposta é só texto)**
3. User: *"**Me avisa quando apagar**"* → AI: *"Pronto! Configurei o sistema para
   te avisar sempre que o computador for desligado ou reiniciado… webhook
   `shutdown-event`… O sistema já está ativo e monitorando."*
   **(= criação + ativação de `Z4NOaIGb6558Dmz3`, 23:22–23:23)**
4. User: *"Vc criou algum fluxo?"* → AI (rota general, sem contexto): *"Sim! Vou te
   ajudar a criar um fluxo ou processo personalizado. O conceito de 'fluxo' pode se
   aplicar a diferentes contextos…"* **(perda total de contexto)**
5. User: *"Quero saber se vc criou algum fluxo no n8n e ativou ele confirma aqui"*
   → AI: lista workflows ativos, cita *"o mais recente é **Notificação de
   Desligamento/Reinicialização** (criado em 2026-09-05)"* **(via GET, não via
   memória)**
6. User: *"Então esse último oq faz na prática"* → AI: *"não consegui identificar
   exatamente o que é 'esse último'…"*
7. User: *"Último fluxo que falou o mais recente notificação de desligamento"* →
   AI: explica o `Z4NOaIGb6558Dmz3` corretamente **(porque a frase agora contém o
   nome — deu pra listar e achar)**
8. User: *"Como eu uso na prática isso hoje"* → AI: *"o primeiro passo é entender
   exatamente o que 'isso' se refere…"*

### 6.2 Mecanismo do "criou outro fluxo indevidamente"

`fresh_turn_input` zera o scratchpad; nenhum nó lê o histórico. O supervisor do
turn das 23:22 recebeu **literalmente "Me avisa quando apagar"** e nada mais.

- `_SUPERVISOR_SYSTEM_PROMPT`: *"'você consegue criar X?', 'seria possível X?' SÃO
  pedidos pra executar X"* + *"o pedido já descreve UMA automação específica →
  despache"*.
- "**apagar**" fora de contexto ≡ **"desligar"** (PT-BR). "Me avisa quando [algo]"
  ≡ "crie uma notificação para quando [algo] acontecer".
- O supervisor sintetizou uma instrução do tipo *"criar automação que notifica
  quando o sistema for desligado/reiniciado"* e despachou o especialista n8n.
- O especialista construiu `webhook(shutdown-event) → set → emailSend`, chamou
  `create_workflow` **e** `activate_workflow`. `check_destructive_n8n_action` **não
  se aplica a `create`/`activate`** → passou direto.
- O `synthesize_final` respondeu como se fosse exatamente o que o usuário pediu.

O nome do workflow ("Notificação de Desligamento/Reinicialização") bate com o tema
recorrente do projeto (Kali desligando e derrubando o Amigão) — o LLM
provavelmente puxou isso do próprio texto que gerou, não de contexto real.

### 6.3 Mecanismo da "ação fantasma" (usuário viu erro, mas o workflow foi criado)

- Turn iniciou ~23:22:23. Especialista n8n levou **57 s** no loop ReAct
  (`concluido em 57029ms`), síntese terminou **23:23:57** (94 s no total).
- O cliente `callOrchestratorTurn` usa `AbortSignal.timeout(95_000)` — **95 s**
  (`extensions/whatsapp-cloud/src/orchestrator-client.ts:14`). Abortou **23:23:57**,
  ~1 s **antes** de o orquestrador terminar.
- O `catch` do cliente transforma qualquer falha (timeout **ou** conexão) na mesma
  mensagem `"Failed to reach Orchestrator at <url>"` → usuário recebeu
  *"Desculpa, tive um problema para processar sua mensagem agora. Tenta de novo em
  instantes."*
- Mas o `POST /workflows` (23:22:38) e o `/activate` (23:23:03) **já tinham
  retornado 200**. **O efeito colateral aconteceu; a confirmação, não.**
- O comentário no `orchestrator-client.ts` ainda diz *"orchestrator default 90s"* —
  **desatualizado**: o `turn_timeout_sec` real é **150 s**. O cliente (95 s)
  desiste bem antes, garantindo que qualquer tarefa n8n mais longa que ~90 s vire
  "erro" na tela **com a ação já feita**.

### 6.4 Hipóteses (sem log que comprove 100%)

- **[Hipótese]** A instrução exata que o supervisor gerou para o especialista n8n
  no turn das 23:22. Não é logada. **→ recuperável no LangSmith** (projeto
  `orchestrator-portfolio`, traces de 05/09 23:22 UTC). Não acessei o LangSmith
  (fora do escopo somente-leitura local).
- **[Hipótese]** Se o turn das 23:21 ("pode apagar") tivesse despachado o
  especialista n8n, ele teria deletado? **Provavelmente não** — sem o ID no
  `job["instructions"]` e com a "REGRA DE CAUTELA" do prompt, o comportamento
  esperado é listar/descrever. Mas é inferência do código, não teste.
- **[Fato, não hipótese]** O `pEVM1SI5Pxavc0JM` das 23:18 é o "fluxo original" que
  o usuário pediu para apagar. O `Z4NOaIGb6558Dmz3` das 23:22 é a "criação
  indevida".

---

## 7. Lógica atual de interpretar / CRUD de workflows n8n

### 7.1 Tools expostas ao LLM do especialista (`schemas/n8n_tools.py`)

| Tool | Método `N8nClient` | Endpoint | Guard? |
|---|---|---|---|
| `N8nListWorkflows` | `list_workflows` | `GET /api/v1/workflows` | não |
| `N8nGetWorkflow` | `get_workflow` | `GET /api/v1/workflows/{id}` | não |
| `N8nCreateWorkflow` | `create_workflow` | `POST /api/v1/workflows` | **não** |
| `N8nUpdateWorkflow` | `update_workflow` | `PUT /api/v1/workflows/{id}` | não |
| `N8nDeleteWorkflow` | `delete_workflow` | `DELETE /api/v1/workflows/{id}` | **sim** |
| `N8nActivateWorkflow` | `activate_workflow` | `POST .../{id}/activate` | não |
| `N8nDeactivateWorkflow` | `deactivate_workflow` | `POST .../{id}/deactivate` | **sim** |
| `N8nTriggerWebhook` | `trigger_webhook` | `POST /webhook(-test)/{path}` | não |

### 7.2 Como o agente identifica um fluxo-alvo

**Ele não identifica de forma confiável.** O único caminho é:

1. o `job["instructions"]` (gerado pelo supervisor, sem histórico) conter um nome
   ou ID; **ou**
2. o especialista chamar `N8nListWorkflows`/`N8nGetWorkflow` no próprio turn e
   casar por nome.

Como o supervisor não vê o histórico, referências anafóricas ("esse fluxo", "o que
você criou agora", "o último") **não chegam como ID nenhum** ao especialista. Nos
turns das 23:25 e 23:28 o especialista fez exatamente isso — `GET
?active=true` — e só conseguiu *descrever*, nunca *agir sobre* o alvo.

### 7.3 "Apagar isso" é ambíguo e **induz criação**

Três problemas somados:

- **Sem contexto:** "apagar isso" não tem "isso". O supervisor não resolve o
  referente.
- **Semântica de "apagar":** sem objeto, "apagar" ≡ "desligar" — foi o que
  aconteceu ("me avisa quando apagar" → notificação de desligamento).
- **Viés a agir:** o prompt manda tratar frase curta como comando; e "criar" é a
  ação default mais provável de um especialista de automação sem alvo claro. O
  `n8n_guard` fecha a porta de deletar/desativar por engano, **mas deixa a de
  criar escancarada** — então o erro se manifesta como *workflow a mais*, nunca
  como *workflow a menos*.

### 7.4 `_N8N_SYSTEM_PROMPT` (regras técnicas, `nodes.py:61`)

- **REGRA DE CAUTELA:** só edita/desativa/deleta/dispara workflow **pré-existente**
  se a instrução pedir explicitamente. **Criar é liberado sem ressalva.**
- **REGRA DE TRIGGER:** primeiro nó tem de ser trigger real (`scheduleTrigger`,
  `webhook`…) senão a ativação falha. (No incidente funcionou: `webhook` é trigger
  válido, `/activate` deu 200.)
- **REGRA DO BÁSICO:** pedido vago ⇒ trigger real + ação simples.

---

## 8. Guardas: `n8n_guard` e `cybersec_guard`

### 8.1 `n8n_guard.check_destructive_n8n_action(tool_name, instructions)` (`graph/n8n_guard.py`)

- Só intercepta **`N8nDeleteWorkflow`** e **`N8nDeactivateWorkflow`**.
- Exige que `instructions` contenha um radical de verbo:
  - delete → `delet` / `apag` / `exclu` / `remov`
  - deactivate → `desativ` / `pause` / `pausa`
- Sem o verbo → retorna `RECUSADO: …`, vira `ToolMessage`, **a tool não roda**.
- **`instructions` é o `job["instructions"]` — o texto do *supervisor*, não a
  mensagem crua do usuário.** Se o usuário diz "apaga o fluxo X" mas o supervisor
  parafraseia sem o verbo, o guard **bloquearia um delete legítimo**; se
  parafraseia como "create…", o guard é **irrelevante**.
- **Não há:** lista de alvos permitidos, exigência de ID, confirmação humana,
  proteção contra `create`/`update`/`activate`, cobertura de "desliga/para/tira do
  ar" (R11 já conhecido).
- Não houve bloqueio no incidente porque **nenhum delete/deactivate foi tentado**.

### 8.2 `cybersec_guard.check_production_infra_block(instructions)` (`graph/cybersec_guard.py`)

- **Não roda no caminho do n8n.** Só em `specialist_cybersec_node`.
- Bloqueia instruções que miram infra de produção própria (`contabo`, `amigao`,
  `evolution-api`, `whatsapp cloud`, `chatwoot`) — checagem por sentença, ignorando
  sentenças com negação ("nunca testar o Contabo").
- **`n8n` sozinho não está na lista** (`cybersec_guard.py:74` — "nome genérico
  demais"). Criar/alterar workflow via `specialist_n8n` **não passa por esse
  guard**. O que ele protege é o inverso: impedir o especialista de *segurança* de
  atacar a própria instância de n8n.
- Efeito colateral observado nos logs (30/08, não no incidente): quando o
  especialista cybersec É acionado e o gateway devolve 500, o usuário recebe um
  `500: {"error":{"message":"internal error"}}` cru na resposta.

### 8.3 Resumo: proteções reais hoje

| Proteção | Existe? |
|---|---|
| Confirmação humana antes de qualquer ação n8n | ❌ |
| Allowlist de workflows que o agente pode tocar | ❌ |
| Bloqueio de `create` acidental | ❌ |
| Bloqueio de `delete`/`deactivate` sem verbo explícito | ✅ (mas checa a paráfrase do supervisor) |
| Exigir ID/nome do alvo antes de deletar | ❌ |
| Auth em `/v1/turn` | ❌ |
| Distinção "workflow criado pelo agente" × "pré-existente do usuário" | ⚠️ só no prompt, não no código |
| Trilha de auditoria por ação (quem/quando/entrada/saída) | ⚠️ parcial (logs INFO, sem corpo de mensagem; LangSmith) |

---

## 9. Capacidades e limitações reais do agente hoje

### 9.1 Comprovado que funciona (evidência ao vivo)

- **Conversa WhatsApp** ponta a ponta (Meta → gateway → orquestrador → resposta).
- **n8n: listar, consultar, criar, ativar** — todos vistos com `200` nos logs de
  05/09 (`POST /workflows`, `POST /workflows/{id}/activate`, `GET
  /workflows?active=true`).
- **Roteamento supervisor → especialista n8n**.
- **Persistência** do histórico no SQLite (grava; não usa).
- **Tracing LangSmith** ativo.
- **Especialista de código (`openclaw`)**: validado em sessões anteriores (Path
  A/B de 27/08), não exercitado no incidente.

### 9.2 Limitações práticas (algumas comprovadas no incidente)

| Limitação | Status |
|---|---|
| **Sem memória de conversa** (histórico gravado, nunca lido) | **comprovado** (§5.2, §6) |
| Referência "esse fluxo / o último / isso" não resolve | **comprovado** (§6.1 msgs 4,6,8) |
| Ação fantasma: efeito n8n acontece, usuário recebe "tive um problema" | **comprovado** (§6.3) |
| Timeout do cliente (95 s) < timeout do orquestrador (150 s) | **comprovado** (código + logs) |
| "Criar" sem confirmação e sem guard | **comprovado** |
| `update`/`deactivate`/`trigger_webhook` — sem teste ao vivo bem-sucedido registrado | não comprovado |
| Orquestração multi-especialista (2+ especialistas, scratchpad entre eles) | nunca rodou em produção |
| Especialista cybersec via WhatsApp: gateway devolveu 500 (30/08) | falha observada |
| Sem RAG / base de conhecimento — responde "de cabeça" sobre o n8n do cliente | conhecido (R2) |
| Sem auth em `/v1/turn`; qualquer processo no host/LAN dispara o grafo | conhecido (R1) |
| Sem healthcheck / 1 worker / sem alerta de queda | conhecido (R7) |
| PII (telefone) em claro como thread_id; corpo de mensagem no SQLite | conhecido (R3) |
| Sem poda do checkpointer (cresce sem limite) | conhecido (P4) |
| Sem fallback de provider (só `deepseek/deepseek-chat` via OpenRouter) | conhecido (R12) |

---

## 10. Causas-raiz consolidadas

| # | Causa-raiz | Arquivo/evidência | Contribuição para o incidente |
|---|---|---|---|
| **RC1** | Grafo não lê o histórico de mensagens; só a última frase | `nodes.py:205-218`, `state.py:80` | supervisor não sabe qual é "esse fluxo"; toda mensagem começa do zero |
| **RC2** | "Pergunta indireta = comando" sem porta de saída para pedir esclarecimento | `_SUPERVISOR_SYSTEM_PROMPT` `nodes.py:148` | "Me avisa quando apagar" virou ordem de criar |
| **RC3** | "Apagar" sem objeto ≡ "desligar" + viés a criar | comportamento LLM + prompt | escolha do workflow "Notificação de Desligamento" |
| **RC4** | `create`/`update`/`activate` sem nenhum guard nem confirmação | `n8n_guard.py:19-22` | workflow ativado em produção sem ninguém aprovar |
| **RC5** | Timeout do cliente (95 s) < grafo (150 s); erro genérico mascara sucesso | `orchestrator-client.ts:14`, logs 23:23:57 | usuário achou que falhou; workflow ficou lá |
| **RC6** | Guard de delete checa a paráfrase do supervisor, não o texto do usuário; não cobre "desliga/para" | `n8n_guard.py:32-44` | fragiliza o único guard que existe |
| **RC7** | Pedido de deletar classificado como "conversa" → nenhuma ação, mas resposta afirmativa ("vou apagar") | log 23:21 `rota=general` + msg 2 | usuário achou que apagou; nada foi apagado |
| **RC8** | Sem trilha de auditoria consultável por ação (corpo, alvo, decisão) | logs INFO sem payload | reconstrução dependeu de correlacionar 3 fontes + LangSmith |

---

## 11. Plano de correção — por etapas, priorizado

> Nenhuma correção foi aplicada. Ordem = maior redução de risco por menor esforço.

### Etapa 0 — Contenção imediata (minutos, sem deploy)

0.1. **Decidir o destino do `Z4NOaIGb6558Dmz3`** ("Notificação de
Desligamento/Reinicialização", ativo, 0 execuções). Ele é inofensivo (webhook
ocioso), mas é lixo de produção criado por engano. Recomendo **desativar e
deletar manualmente pelo n8n** (ação humana, fora do agente). Idem avaliar
`pEVM1SI5Pxavc0JM` (inativo).

0.2. **Alinhar os timeouts** (config, 1 linha cada): subir
`ORCHESTRATOR_TURN_TIMEOUT_MS` do cliente para **>= 160 s** (acima dos 150 s do
grafo) **ou** baixar `turn_timeout_sec` do orquestrador para ~85 s. Sem isso, toda
tarefa n8n longa continua virando "ação fantasma".

### Etapa 1 — Memória de contexto confiável (a correção de maior impacto)

1.1. No `supervisor_node` e no `synthesize_final_node`, **passar as últimas N
mensagens** de `state["messages"]` para o LLM (não só `extract_task_description`).
Começar com N=10–20; o `add_messages` já mantém a lista.

1.2. Ao despachar um especialista, **incluir no `job["instructions"]` um resumo
das ações n8n recentes desta conversa** (nome + ID dos workflows criados/alterados
nos últimos turns). Fonte possível: um campo novo persistido (ver 1.3) ou uma
chamada `N8nListWorkflows` no início do turn de automação.

1.3. **Persistir um "registro de ações desta conversa"** fora do escopo
por-tarefa (não zerado pelo `fresh_turn_input`): lista append-only de
`{turn, tool, workflow_id, workflow_name, resultado}`. Vira a base tanto do
contexto (1.2) quanto da auditoria (Etapa 5) e do "apagar isso" (Etapa 4).

1.4. Teste de regressão: conversa de 3 turns — cria fluxo / "qual fluxo você
criou?" / "apaga ele" — tem de resolver o ID sem o usuário repetir o nome.

### Etapa 2 — Confirmação de ações que mudam produção

2.1. **Handshake de confirmação** para `create`, `update`, `activate`, `delete`,
`deactivate`, `trigger_webhook`: o especialista **descreve o que vai fazer** (nome,
nós, trigger, se vai ativar) e a resposta ao usuário termina com *"Confirma? (sim/
não)"*. Só executa no turn seguinte se o usuário confirmar. Requer estado
"ação pendente de confirmação" persistido por thread (encaixa no 1.3).

2.2. Enquanto 2.1 não existe: **nunca ativar no mesmo turn da criação**. Criar
sempre inativo, e a ativação vira um pedido explícito separado. (Hoje a criação +
ativação aconteceram juntas, sem respiro.)

2.3. `activate`/`create` deixam de ser "sempre liberados": passam pelo mesmo gate
de confirmação. Não precisa de verbo — precisa de **eco confirmado pelo usuário**.

### Etapa 3 — Endurecer os guards

3.1. `n8n_guard`: passar **as duas** strings (mensagem crua do usuário **e**
`job["instructions"]`) para `check_destructive_n8n_action`, igual o
`cybersec_guard` já faz com as duas fontes.

3.2. Ampliar cues de deactivate: `deslig`, `para`, `parar`, `tira do ar`,
`tirar do ar`, `stop`. (R11.)

3.3. **Guard novo de "intenção de remoção vira criação"**: se a mensagem do
usuário contém radical de remoção (`apag`/`delet`/`exclu`/`remov`/`tir`) **e** o
especialista tenta `N8nCreateWorkflow` no mesmo turn → **bloquear e devolver ao
supervisor** com "o usuário pediu para remover algo, não para criar; peça o
workflow-alvo". Cobre exatamente o "me avisa quando apagar" → cria.

3.4. Exigir `workflow_id` **não-nulo e existente** (via `get_workflow`) antes de
`delete`/`deactivate`/`update`.

### Etapa 4 — Resolver referência a workflow ("apagar isso")

4.1. Com o histórico (Etapa 1) + registro de ações (1.3), o supervisor resolve
"esse fluxo / o último / o que você acabou de criar" para um **ID concreto** antes
de despachar.

4.2. Se a referência for **ambígua** (0 ou 2+ candidatos), o supervisor **não
despacha** — responde pedindo esclarecimento com a lista de candidatos ("Você quer
dizer o *Fluxo Básico de Teste* (id …) ou o *Notificação…* (id …)?").

4.3. Prompt do supervisor: adicionar exceção explícita — *"pedido de remoção/
alteração sem alvo identificável ⇒ pergunte qual, NÃO crie nada"*.

### Etapa 5 — Auditoria e recuperação de falha

5.1. **Trilha de auditoria por turno** (tabela dedicada ou LangSmith
estruturado): `thread_id`, timestamp, texto do usuário, decisão do supervisor,
instrução gerada, especialista, cada tool-call n8n (nome + args + status +
workflow_id), resposta final, guards disparados. Retenção definida.

5.2. **Reconciliação de ação fantasma**: quando o cliente WhatsApp aborta por
timeout, **não** mandar só "tive um problema". Registrar o `session_key` numa fila
de "turns órfãos" e, no próximo turn, o supervisor abre com *"No seu pedido
anterior eu cheguei a executar: [ações]. Quer manter, ajustar ou desfazer?"*.

5.3. `synthesize_final` **nunca** deve afirmar que fez algo (`"Vou apagar"`,
`"criei"`, `"ativei"`) se o `internal_scratchpad` não tiver a ação correspondente
com `sucesso=True`. Regra dura no prompt + verificação no código
(cross-check scratchpad × verbos de ação na resposta — reaproveitar a heurística
do plugin `response-audit`).

5.4. Alerta operacional: notificar o Max (via `ask-max` / WhatsApp) sempre que um
`create`/`activate`/`delete` real acontecer em produção — pelo menos até 2.1
existir.

### Etapa 6 — Higiene de plataforma (já em backlog, revalidado por este incidente)

6.1. Auth em `/v1/turn` (Bearer + rate limit + `max_length`). (R1/P1.)
6.2. Healthcheck do orquestrador no compose + `--workers 2` ou restart confiável. (P2.)
6.3. Poda do checkpointer / TTL por `thread_id`; migrar para Postgres. (P4.)
6.4. Hash do telefone como `thread_id`; parar de logar/gravar corpo de mensagem em claro. (LGPD.)
6.5. Reconciliar `ANALISE_ATUAL.md` / `ESTADO_ATUAL.md`: **o cutover
WhatsApp→orquestrador está em produção** desde ~26/08, sem persona e sem memória.
6.6. Portas `3978` e `5678` em `127.0.0.1`.
6.7. Remover comentário `# TESTE_CURSOR` (só no master; a imagem de produção nem tem).

### Ordem sugerida de execução

**0 → 1 → 2 → 3 → 5 → 4 → 6.** As Etapas 0–2 sozinhas já teriam evitado o
incidente inteiro: com memória (1), o "esse fluxo" resolve; com confirmação (2), o
"me avisa quando apagar" teria virado *"Você quer que eu crie uma automação de
notificação de desligamento? (sim/não)"* em vez de um workflow ativo.

---

## 12. Anexos

### 12.1 Comandos usados no Contabo (todos somente-leitura)

```
ssh contabo 'uptime; docker ps'
docker inspect -f ... meu-agente-orchestrator-orchestrator-1
docker exec meu-agente-orchestrator-orchestrator-1 sh -lc 'env | sed "s/=.*/=<redacted>/"'
docker exec n8n n8n --version ; n8n list:workflow
docker exec n8n-postgres psql -U n8n -d n8n -c 'SELECT ... FROM workflow_entity/webhook_entity/execution_entity'   (só SELECT)
docker logs --timestamps meu-agente-orchestrator-orchestrator-1
docker logs --timestamps openclaw-openclaw-gateway-1 | grep 2026-09-05
docker network inspect openclaw_default
docker exec meu-agente-orchestrator-orchestrator-1 python -c '<decodifica checkpoints.sqlite com o serializer do LangGraph, só leitura>'
cat /root/meu-agente-orchestrator/docker-compose.yml
docker exec openclaw-openclaw-gateway-1 cat /home/node/.openclaw/openclaw.json   (parseado, tokens redigidos)
```

### 12.2 Arquivos-fonte lidos (local)

`orchestrator/src/orchestrator/`: `main.py`, `config.py`, `graph/{state,builder,nodes,n8n_guard,cybersec_guard}.py`,
`clients/{n8n_client,openclaw_client}.py`, `schemas/{requests,n8n_tools}.py`.
`extensions/whatsapp-cloud/src/{inbound,orchestrator-client,channel}.ts`.
`openclaw/extensions/orchestrator-bridge/src/{ask-orchestrator-tool,plugin,config}.ts`.
Docs: `ANALISE_ATUAL.md`, `RELATORIO_N8N_CRIACAO_FLUXOS_2026-09-05.md`, `docs/ESTADO_ATUAL.md`.

### 12.3 Limitações desta investigação

- **Não acessei o LangSmith.** As instruções exatas que o supervisor gerou para o
  especialista n8n (a "tradução" de "me avisa quando apagar") estão nos traces do
  projeto `orchestrator-portfolio`, 05/09 ~23:18–23:35 UTC. É a peça que fecharia
  a §6.2 de hipótese para fato.
- Os logs do orquestrador e do gateway **não gravam o corpo das mensagens** — o
  texto do usuário foi reconstruído do `checkpoints.sqlite` (52 mensagens); os
  horários vieram dos logs; as ações n8n do Postgres. As três fontes são
  consistentes entre si.
- Não executei nada que altere estado (sem `pytest`, sem `curl` de escrita, sem
  `docker restart`, sem tocar em workflow).
- `n8n list:workflow` não expõe a coluna `active`; o estado ativo/inativo veio de
  `SELECT active FROM workflow_entity`.
- O conteúdo das 52 mensagens abrange **vários dias** no mesmo thread; só o bloco
  de 05/09 23:11–23:35 é o incidente.

### 12.4 Estado atual dos dois workflows do incidente (05/09)

| ID | Nome | Criado | Ativo hoje | Nós | Execuções |
|---|---|---|---|---|---|
| `pEVM1SI5Pxavc0JM` | Fluxo Básico de Teste | 2026-09-05 23:18:47 UTC | não | `webhook` → `set` | — |
| `Z4NOaIGb6558Dmz3` | Notificação de Desligamento/Reinicialização | 2026-09-05 23:22:38 UTC | **sim** | `webhook`(shutdown-event) → `set` → `emailSend` | **0** |

---

## Revisão independente

> Data: 2026-09-06. Modo estritamente somente-leitura: revalidei o relatório
> contra o código local (master), o histórico git e spot-checks read-only no
> Contabo (logs do orquestrador/gateway, `SELECT` no Postgres do n8n,
> decodificação read-only do `checkpoints.sqlite`). Nada foi alterado.

### R1. Método e o que foi re-verificado (e com que resultado)

| Afirmação do relatório | Verificação | Resultado |
|---|---|---|
| `extract_task_description` retorna só a última `HumanMessage` (`nodes.py:205-218`) | li o código | ✅ confirmado |
| `fresh_turn_input` zera tudo menos `messages` (`state.py:80-110`) | li o código | ✅ confirmado |
| `supervisor_node`/`synthesize_final_node` montam o prompt só com última frase + scratchpad (que acabou de ser zerado) (`nodes.py:252-260`, `559-567`) | li o código | ✅ confirmado |
| Especialistas recebem só `job["instructions"]` (texto do supervisor, sem histórico) | `nodes.py:337`, `490`, `511` | ✅ confirmado |
| `n8n_guard` só intercepta `N8nDeleteWorkflow`/`N8nDeactivateWorkflow`; recebe `job["instructions"]`, não o texto do usuário | `n8n_guard.py:19-44`, `nodes.py:511` | ✅ confirmado |
| `create`/`update`/`activate`/`trigger_webhook` sem guard nenhum | `n8n_guard.py:38-40`, `_run_n8n_tool` | ✅ confirmado |
| Prompt do supervisor: "pergunta indireta é pedido de ação" (`nodes.py:153-163`) | li o código | ✅ confirmado (texto literal bate) |
| REGRA DE CAUTELA libera criar sem ressalva (`nodes.py:67-72`) | li o código | ✅ confirmado |
| Timeouts: cliente 95 s (`orchestrator-client.ts:14`), grafo 150 s (`config.py:58`), n8n 30 s, OpenClaw 120 s, `max_supervisor_iterations=4`, `_N8N_MAX_STEPS=6` | li o código | ✅ confirmado; o comentário "default 90s" no cliente é mesmo desatualizado (o valor real é 150) |
| `/v1/turn` sem autenticação; falha vira HTTP 200 com fallback (`main.py:82-109`) | li o código | ✅ confirmado (não há dependency de auth nem middleware) |
| Handoff direto WhatsApp→orquestrador no `inbound.ts`, sem passar pelo agente `main` | `inbound.ts:103-118` | ✅ confirmado |
| Código em produção == master no que importa: único diff pós-26/08 no `orchestrator/src` é o commit `8ab3802` (1 linha de comentário); extensão `whatsapp-cloud` inalterada desde 26/08 | `git log`/`git show` | ✅ confirmado |
| Linhas de log do n8n (`POST /workflows 200` etc.) vêm mesmo dos logs do orquestrador | `docker logs` no Contabo | ✅ confirmado — são linhas `INFO httpx: HTTP Request: ...` (httpx loga em INFO com o `logging.basicConfig` do `main.py`); timestamps batem exatamente com os do relatório |
| Estado dos workflows no n8n (IDs, nomes, `active`, `createdAt`, 0 execuções) | `SELECT` no Postgres do n8n | ✅ confirmado, valores idênticos aos do relatório |
| 133 checkpoints na thread real | decode read-only do `checkpoints.sqlite` | ✅ confirmado (133) |
| Gateway teve exatamente 1 linha de log em 05/09 (a do "Orchestrator turn failed") | `docker logs` do gateway | ✅ confirmado |
| Cutover em produção: primeira mensagem real da thread | decode read-only do checkpoint | **✅ confirmado e agora com data exata: 2026-08-26 01:21 UTC** (ver R2.1) |
| `# TESTE_CURSOR` só no master, ausente na imagem de produção | `git log -S` (introduzido em `8ab3802`, 31/08) | ✅ confirmado (produção é anterior) |

As referências de linha do relatório estão corretas em todas as que confirmei.

### R2. Correções de interpretação

**R2.1 — Cutover: "desde ~26/08" pode ser afirmado com data exata.** O
primeiro checkpoint da thread `agent:main:direct:554184445755` é de
**2026-08-26 01:21:04 UTC**. Ou seja: o handoff direto já estava vivo na
madrugada do dia 26/08 — *antes* do build da imagem atual (01:48), o que mostra
que o gateway já rodava o handoff com imagem anterior e o volume de dados
sobreviveu aos recreates. A correção do relatório sobre os docs
(`ANALISE_ATUAL.md`/`ESTADO_ATUAL.md` dizendo "decidido, não implementado")
está **certa**; só convém registrar que a checagem "ao vivo" registrada nos
docs em 26/08 ou estava errada ou descreve um momento anterior à ativação.

**R2.2 — "Inofensivo (webhook ocioso)" está incorreto.** Um workflow **ativo**
com trigger `webhook` expõe uma **URL pública e não autenticada**
(`https://n8n.mxos.com.br/webhook/shutdown-event`) que qualquer pessoa que
conheça/descubra o path pode disparar quantas vezes quiser (hoje executa
`set`→`emailSend`; como o SMTP do n8n aparentemente não está configurado, o
impacto é baixo — mas a superfície é remota, anônima e em produção). Isso
muda a Etapa 0.1: **desativar o `Z4NOaIGb6558Dmz3` não é "avaliar", é fazer
agora** (ação humana no n8n, 1 clique). E tem consequência sistêmica: cada
"criar + ativar" do especialista com um node `webhook` cria uma **nova
superfície pública** em produção — a confirmação da Etapa 2 deve exibir o
path público ao usuário, e "nunca ativar no turn da criação" (2.2) ganha
peso também por isso.

**R2.3 — Corrida de timeout: mesma segunda, não "1 s antes".** O cliente
abortou às `23:23:57.246` e o `synthesize_final` logou "concluido" às
`23:23:57` (logs com granularidade de 1 s). É uma corrida no mesmo segundo;
o mecanismo descrito no relatório está correto, mas a diferença exata é
indeterminável com essa granularidade.

**R2.4 — RC7 fica como pergunta aberta.** O relatório registra o fato
("pode apagar esse fluxo" → `rota general`, sem despachar) mas não explica
**por que** o supervisor não despachou — "apaga esse fluxo que vc acabou de
criar" descreve algo concreto, e pelo próprio `_SUPERVISOR_SYSTEM_PROMPT`
deveria despachar. A assimetria é instrutiva e reforça o relatório: a
direção perigosa (criar, 23:22) **despachou** e a benigna (apagar, 23:21)
**não** — ou seja, confiar na classificação do supervisor como controle de
segurança é insuficiente nos dois sentidos; o handshake da Etapa 2 é o
controle que de fato fecha o risco.

**R2.5 — "Apagar ≡ desligar" é hipótese, não fato (enquadramento).** A §6.4
marca corretamente como hipótese a instrução exata gerada pelo supervisor no
turn das 23:22 (não logada), mas a §1 (executiva) e a §6.2 a apresentam de
forma assertiva. A hipótese é plausível (o nome do workflow criado a
corrobora), mas a cadeia causal RC2/RC3 só vira fato com o trace do
LangSmith. **Recomendo ler o LangSmith (projeto `orchestrator-portfolio`,
traces de 05/09 23:18–23:35 UTC) antes de implementar as Etapas 1–3** — custo
quase zero, e converte duas causas-raiz de "mais provável" em "comprovado",
alinhado à disciplina do projeto (sem evidência, sem fix).

**R2.6 — "Qualquer processo no host/LAN" (§9.2) é impreciso sobre o raio do
sem-auth.** A porta do orquestrador está em `127.0.0.1:8000` no host — não é
alcançável da internet aberta. O alcance real é: processos do host + containers
na rede docker compartilhada (o gateway comprovou com o caller `172.22.0.2`).
O risco de auth é mesmo P1, mas o argumento correto é escalada lateral
(container comprometido → CRUD de workflows de produção), não "LAN".

### R3. Lacunas de segurança não cobertas (ou subestimadas) no plano

**R3.1 — `/v1/turn` aceita `session_key` arbitrário.** Além da ausência de
auth, o endpoint aceita qualquer `thread_id`: um chamador sem credencial pode
**ler/escrever a thread de outro usuário** (injetar mensagens na memória
alheia — relevante quando a Etapa 1 passar a ler histórico nas decisões!) e
**disparar o grafo com as credenciais n8n/OpenRouter do orquestrador**. A
Etapa 6.1 deve incluir: auth em `/v1/turn` **e** `/tasks/stream` + vínculo do
`session_key` a uma identidade autenticada + rate limit. Também vale
identificar quais containers compartilham a rede do orquestrador (o relatório
só confirmou o gateway) — define o raio real da exposição.

**R3.2 — PII para o LangSmith (terceiro externo).** O tracing ativo envia o
conteúdo das mensagens (e das instruções do supervisor) para a LangSmith. O
plano trata PII só no armazenamento local (6.4). Decidir redação de conteúdo
ou desativação do tracing junto com o item LGPD — inclusive porque o relatório
usa o próprio LangSmith como fonte de evidência.

**R3.3 — R10 ficou fora do plano.** O `ANALISE_ATUAL.md` lista como risco
médio "token do gateway vazou; `.env` no histórico git do Contabo" (R10). O
plano de higiene (Etapa 6) não o inclui. Adicionar à 6.x.

**R3.4 — Ação fantasma server-side (variante não descrita).** Se o grafo
estoura os 150 s, o `asyncio.wait_for` **cancela a tarefa**: efeitos já
aplicados permanecem (ex.: create feito, activate não), o checkpoint pode não
ser gravado e o turn seguinte começa de estado mais velho. É a mesma classe da
ação fantasma do incidente, mas pelo lado do servidor. A reconciliação (5.2)
cobre o sintoma; registrar a variante explicitamente na implementação.

### R4. Recomendações: efetividade e risco de regressão

**Etapa 0 — correta, com dois ajustes.**
- 0.1: desativar **já** (ver R2.2 — superfície pública, não lixo inerte).
- 0.2: **não usar a alternativa "baixar `turn_timeout_sec` para ~85 s"** — ela
  *aumenta* o risco de ação fantasma (cancela o grafo no meio do loop ReAct,
  entre `create` e `activate`, sem checkpoint). Subir o cliente para ≥160 s é
  a direção certa (o bridge `orchestrator-bridge` já usa 160 s por padrão,
  `config.ts:11` — alinhar os dois). Com o 5.2, qualquer corrida residual vira
  reconciliação explícita em vez de erro mudo.

**Etapa 1 (memória) — ataca a causa certa, é a de maior impacto. Três cuidados:**
- **Latência/custo:** injetar N=10–20 mensagens em *toda* chamada do supervisor
  e da síntese num orçamento de 95–150 s que o incidente já mostrou estourar é
  a receita para transformar mais turns em erro fantasma. Fazer 0.2 **antes**
  de 1.1, e considerar um resumo rolante (rolling summary) além da janela de
  mensagens; medir p95 do turn após o deploy.
- **Armadilha do `fresh_turn_input`:** o "registro de ações" (1.3) e o "ação
  pendente de confirmação" (2.1) são campos novos do `GraphState` — se entrarem
  no reset do `fresh_turn_input` (como todos os campos não-`messages`), nascem
  mortos. Precisam ser **excluídos do reset e usar um reducer próprio**. Sem
  isso, o fix repete o bug de 24/08 às avessas (campo sempre vazio em vez de
  sempre acumulado).
- **Chave de thread dividida:** o bridge `ask_orchestrator` usa
  `orchestrator-bridge:<sender>` como `session_key` (`ask-orchestrator-tool.ts:67`),
  thread **diferente** da do WhatsApp (`agent:main:direct:<fone>`). A memória
  continuará cindida por porta de entrada se a Etapa 1 não decidir uma chave
  canônica por usuário (ou, conscientemente, manter separadas — mas precisa
  ser decisão, não acidente). O plano não menciona.

**Etapa 2 (confirmação) — a defesa mais forte do plano.** Cuidados de design:
uma pendência por thread por vez, o pedido de confirmação deve ecoar nome +
path público do workflow, pendência com expiração, e o "sim" da resposta não
pode ser capturado pela regra "pergunta indireta = comando" como um novo
pedido de criação. 2.2 é mitigação parcial (evita ativação indevida, não
criação indevida) — o relatório sabe disso; correta como interim.

**Etapa 3 — 3.1/3.2/3.4 sólidas e baratas. 3.3 tem alto risco de falso
positivo.** O guard proposto ("radical de remoção na mensagem + tentativa de
`N8nCreateWorkflow` → bloquear") dispara em pedidos legítimos como *"cria um
fluxo que apaga emails velhos todo dia"* — a mensagem contém "apag", o
especialista cria, e o guard bloqueia um pedido correto. Como está escrito,
gera regressão de UX e um loop com o supervisor. Alternativa: não bloquear
por léxico — transformar em **pedido de confirmação** (casa com a Etapa 2:
mostrar "entendi que você quer criar X; confirma?") ou registrar a exceção
para o supervisor reavaliar com a pergunta explícita "o usuário pediu criar
ou remover?". O handshake da Etapa 2 já pega esse caso sem heurística.

**Etapa 5 — 5.1/5.3/5.4 boas. 5.2 precisa do mecanismo de detecção.** O
orquestrador **não sabe** que o cliente abortou: para ele o turn terminou
(200 numa conexão que depois caiu). Quem tem o sinal é o `inbound.ts` — o
próximo turn precisa enviar algo como `previous_aborted: true`, e o orquestrador
cruzar com o registro de ações (1.3). Sem esse sinal client→server, a fila de
"turns órfãos" não é detectável server-side.

**Etapa 6 — ajustes pontuais:** 6.1 cobrir `/tasks/stream` + binding de
session_key (R3.1); incluir R10 (R3.3) e o item LangSmith-PII (R3.2). 6.2:
o endpoint `/health` **já existe** (`main.py:77`) — falta só o `HEALTHCHECK`
no compose, como o relatório diz. 6.4 (hash do telefone): os 133 checkpoints
existentes ficarão órfãos — precisa migração de chave ou aceitar reset de
memória; decidir antes.

**Ordem sugerida:** a do relatório (0 → 1 → 2 → 3 → 5 → 4 → 6) é razoável,
com três ajustes: (a) leitura do LangSmith antes da Etapa 3 (R2.5); (b) 2.2
junto da Etapa 0 (uma linha, mitiga já a ativação indevida); (c) Etapa 2
antes de detalhar a 3.3 — o handshake torna o guard léxico em grande parte
desnecessário.

### R5. Veredito

O relatório é **fiel ao código e à implantação** (todas as afirmações centrais
conferidas — ver R1), distingue corretamente fato de hipótese nas seções 6.1/
6.4 (com a ressalva de enquadramento da R2.5), e o plano de correção **reduz
de fato** os dois riscos-alvo: perda de contexto (Etapa 1 + 5.2) e criar/apagar
workflows errados (Etapa 2 + 4 + 3.1/3.2/3.4). As quatro causas estruturais
(stateless por mensagem, pergunta-indireta, create sem guard, corrida de
timeout) estão comprovadas no código e nos logs, não são conjectura.

**Correções a incorporar antes da implementação:** desativar o
`Z4NOaIGb6558Dmz3` imediatamente (superfície pública, R2.2); não baixar o
`turn_timeout_sec` (R4/0.2); reformular a 3.3 como confirmação e não bloqueio
léxico (R4/Etapa 3); definir o mecanismo client-side do 5.2; excluir os novos
campos persistentes do reset do `fresh_turn_input`; cobrir `/tasks/stream` +
binding de session_key na 6.1; incluir R10 e LangSmith-PII na higiene; e ler
o LangSmith antes da Etapa 3.

### R6. Prioridades consolidadas (revisadas)

| Prioridade | Ação |
|---|---|
| **P0 — hoje** | Desativar (e depois deletar) `Z4NOaIGb6558Dmz3` pela UI do n8n (humano). Subir `ORCHESTRATOR_TURN_TIMEOUT_MS` do cliente para ≥160 s (não mexer nos 150 s do grafo). |
| **P0 — evidência** | Ler LangSmith (05/09 23:18–23:35 UTC): instrução exata do supervisor no turn 23:22 → fecha RC2/RC3. |
| **P1** | 2.2 "nunca ativar no turn da criação" (1 linha) → depois 2.1 handshake completo. |
| **P1** | Etapa 1 (histórico no supervisor/síntese + registro de ações com reducer, fora do `fresh_turn_input`), com 0.2 antes e medição de latência. |
| **P1** | 6.1: auth em `/v1/turn` **e** `/tasks/stream` + binding session_key↔identidade + rate limit. |
| **P2** | 5.x auditoria/reconciliação (com sinal client-side do abort); 3.1/3.2/3.4; Etapa 4 (resolução de "esse fluxo"). |
| **P2** | 6.4 hash do telefone + migração dos checkpoints; item LangSmith-PII; R10 (rotação de token, limpeza de `.env` no git do Contabo). |
| **P3** | 6.3 poda/Postgres; 6.6 portas 3978/5678 em 127.0.0.1; 6.5 reconciliar docs; 6.7 remover `# TESTE_CURSOR` do master. |
