# Etapa P0 — Contencao do incidente n8n de 05/09

> Base: `ANALISE_CEREBRO_AGENTE_CONTABO_2026-09-06.md`, secao **Revisao
> independente** (R2.2, R4/Etapa 2, R6 "P0 — hoje").
> Data de execucao: 2026-09-06. Escopo estrito: **so** contencao. Nao inclui
> memoria de conversa, autenticacao em `/v1/turn`, poda de checkpointer nem
> os demais itens das Etapas 1+ do plano.

---

## 1. Resultado de hoje (resumo)

| Item | Estado |
|---|---|
| Workflow `Z4NOaIGb6558Dmz3` ("Notificacao de Desligamento/Reinicializacao") | **DESATIVADO** em producao, **nao excluido**. Ja estava `active=false` quando esta etapa comecou (desativado em 2026-09-06 ~10:42 UTC, provavelmente acao manual do Max pela UI do n8n). Confirmado por 3 fontes independentes. |
| Gate de confirmacao no orquestrador (criar/ativar/desativar/excluir) | **Implementado** em `orchestrator/`, com testes. Nao deployado ainda. |
| Criar nunca ativa no mesmo turno | Garantido pelo gate (uma proposta de escrita por turno; ativar tem confirmacao propria). |
| Leitura/listagem (`N8nListWorkflows`, `N8nGetWorkflow`) e `N8nTriggerWebhook` | Inalterados — continuam passando direto. |

---

## 2. Estado do workflow `Z4NOaIGb6558Dmz3` (evidencia)

Coletado em 2026-09-06 ~11:00 UTC, somente-leitura (um `GET` na API, `SELECT`
no Postgres, um `GET` no webhook publico):

**API REST do n8n** (`GET /api/v1/workflows/Z4NOaIGb6558Dmz3`):
```
id:        Z4NOaIGb6558Dmz3
name:      Notificação de Desligamento/Reinicialização
active:    false
createdAt: 2026-09-05T23:22:38.084Z
updatedAt: 2026-09-06T10:42:41.638Z
nodes:     Webhook Trigger (n8n-nodes-base.webhook)
           -> Formatar Detalhes (n8n-nodes-base.set)
           -> Enviar Email (n8n-nodes-base.emailSend)
```

**Postgres de producao** (`SELECT ... FROM workflow_entity WHERE id=...`):
```
Z4NOaIGb6558Dmz3 | active = f | createdAt 2026-09-05 23:22:38.084+00 | updatedAt 2026-09-06 10:42:41.638+00
```
Nao aparece na lista de workflows `active=true` (6 ativos hoje, nenhum e este).
Total: 19 workflows, 6 ativos.

**Execucoes**: `SELECT count(*) FROM execution_entity WHERE "workflowId"=...` -> **0**
(nunca rodou, desde a criacao).

**Webhook publico**: `GET https://n8n.mxos.com.br/webhook/shutdown-event` -> **404**
(nao roteavel — coerente com o workflow inativo).

**Observacao (residual, nao bloqueante):** existe uma linha "orfa" em
`webhook_entity` para este workflow, com path malformado
`Z4NOaIGb6558Dmz3/webhook%20trigger/shutdown-event` (formato de webhook de
teste, nao de producao). Como o workflow esta inativo e o path nao e
`shutdown-event`, ela e inerte (o 404 acima confirma). **Nao foi tocada** —
limpeza de tabela interna do n8n esta fora do escopo P0. Registrada no backlog.

**Decisao sobre exclusao:** a etapa pediu explicitamente "sem excluir". O
workflow permanece no cadastro, apenas inativo. Excluir de vez (recomendacao
R2.2 / Etapa 0.1 do plano) fica como decisao humana a parte.

`pEVM1SI5Pxavc0JM` ("Fluxo Basico de Teste"): continua **inativo**, intocado.

---

## 3. O que foi implementado no orquestrador

### 3.1 Gate de confirmacao de acoes n8n

Novo modulo `orchestrator/src/orchestrator/graph/n8n_confirmation.py` +
integracao em `graph/nodes.py` e `graph/state.py`.

Antes de **criar, ativar, desativar ou excluir** um workflow, o orquestrador
agora exige uma confirmacao do usuario que e:

- **explicita** — o usuario precisa responder afirmativamente ("sim", "pode",
  "confirmo"...) num **turno posterior** ao da proposta. O classificador
  (`classify_confirmation_reply`) e deliberadamente estrito: so aceita
  mensagens curtas e inequivocas; "sim, mas muda o nome" -> `unclear` (lado
  seguro). Negacao e checada antes da afirmacao.
- **persistente** — a pendencia vive em `GraphState.n8n_pending_confirmation`,
  que sobrevive ao `fresh_turn_input` (reducer `merge_pending_confirmation`:
  `None` = nao mexe, `dict` = grava, `"clear"` = apaga) e e gravada pelo
  checkpointer SQLite. Aguenta restart do orquestrador.
- **vinculada a acao e ao workflow** — a pendencia guarda `tool_name`,
  `action`, `workflow_id` (ou `name`, no caso de create) e os `args` exatos.
  A execucao confirmada usa **exatamente** esses valores.
- **com expiracao** — `expires_at = created_at + n8n_confirmation_ttl_sec`
  (config nova, default **900 s / 15 min**). Passado o prazo, a pendencia e
  descartada e o usuario recebe um aviso; nada e executado.
- **de uso unico** — cada pendencia tem um `token` aleatorio (uuid4). O
  `supervisor` so despacha a execucao apos bater a resposta afirmativa contra
  uma pendencia valida, gravando o `token` em `n8n_confirmed_token` (campo
  por-turno). O `specialist_n8n_node` revalida o token contra a pendencia
  persistida e, ao executar, seta `n8n_pending_confirmation = "clear"`.
  Repetir o "sim" nao re-executa nada.

### 3.2 Fluxo (exemplo: "cria um workflow X")

```
Turno 1  "cria um workflow chamado X"
  supervisor -> despacha n8n
  n8n LLM -> chama N8nCreateWorkflow(...)
  gate -> NAO executa; monta pendencia {action:create, args, token, expira em 15min}
  n8n_node -> grava pendencia no estado, encerra o loop, pede confirmacao
  resposta ao usuario: "Confirma que quer criar o workflow X? (sim/nao)"
  --> workflow NAO foi criado

Turno 2  "sim"
  supervisor (deterministico, sem LLM) -> classify("sim")=affirm + pendencia valida
                                       -> despacha n8n com n8n_confirmed_token
  n8n_node (caminho confirmado, sem LLM) -> revalida token -> executa create_workflow()
                                         -> workflow criado INATIVO
                                         -> n8n_pending_confirmation = "clear"

Turno 3  "sim" de novo  ->  pendencia ja consumida  ->  nada acontece
```

Ativar segue o mesmo ciclo, com **confirmacao propria**: "criar" nunca
arrasta um "ativar" no mesmo turno (o gate so deixa **uma** proposta de
escrita por turno; a criacao ja deixa o workflow inativo).

### 3.3 Recusa / expiracao

- `"nao"` / `"cancela"` -> `supervisor` limpa a pendencia, nada e executado,
  responde confirmando o cancelamento.
- pendencia expirada quando o "sim" chega -> `supervisor` a descarta,
  responde que expirou; usuario refaz o pedido se quiser.

### 3.4 Guardas antigos

- `n8n_guard.check_destructive_n8n_action` (verbo explicito p/ delete/deactivate)
  **continua rodando** como camada extra, agora tambem no caminho de execucao
  confirmada (o texto da acao confirmada sempre carrega o verbo, entao nunca
  bloqueia uma confirmacao legitima).
- `cybersec_guard` — inalterado (nunca esteve no caminho do n8n).

### 3.5 Arquivos alterados

| Arquivo | Mudanca |
|---|---|
| `orchestrator/src/orchestrator/graph/n8n_confirmation.py` | **novo** — gate, builder de pendencia, validade, classificador de resposta |
| `orchestrator/src/orchestrator/graph/nodes.py` | `_run_n8n_tool` (gate antes de escrita), `specialist_n8n_node` (caminho confirmado + captura de proposta), `supervisor_node` (resolucao affirm/deny/expirada), `_N8N_SYSTEM_PROMPT` (regra de confirmacao) |
| `orchestrator/src/orchestrator/graph/state.py` | `n8n_confirmed_token` (por-turno) + docstrings de `GraphState`/`fresh_turn_input`/reducer; preserva o `n8n_pending_confirmation` + `merge_pending_confirmation` que ja estavam no working tree |
| `orchestrator/src/orchestrator/config.py` | `n8n_confirmation_ttl_sec` (default 900) |
| `orchestrator/tests/test_specialist_n8n.py` | atualizados os testes que codificavam o comportamento antigo (create/delete executavam direto) + novos casos de confirmacao |
| `orchestrator/tests/test_n8n_confirmation.py` | **novo** — unidade do modulo |
| `orchestrator/tests/test_graph_n8n_confirmation_flow.py` | **novo** — fluxo multi-turn ponta a ponta pelo grafo real |

> Nota sobre `state.py`: a copia no working tree (pre-existente a esta etapa)
> ja tinha o campo `n8n_pending_confirmation` + reducer, mas tambem havia
> **removido ~64 linhas de comentarios de projeto** do arquivo. Esta etapa
> preservou a mudanca funcional e re-documentou os pontos que o gate precisa;
> os demais comentarios removidos **nao foram restaurados** (fora do escopo) —
> vale revisar se a remocao foi intencional.

---

## 4. Testes

Rodados com `.venv/bin/python -m pytest` em `orchestrator/`:

```
87 passed
```

Relevantes a esta etapa:

- `tests/test_n8n_confirmation.py` — classificador (affirm/deny/unclear,
  incl. "nao pode" != "pode", "sim mas muda o nome" = unclear), validade
  (fresco / expirado / malformado), builder (vinculo acao+workflow, tokens
  unicos).
- `tests/test_graph_n8n_confirmation_flow.py` — pelo grafo real, multi-turn:
  1. escrita sem confirmacao **bloqueada** -> vira pendencia; "sim" cria
     **uma** vez; "sim" de novo nao re-cria (uso unico).
  2. "nao" cancela sem executar.
  3. pendencia **expirada** nao executa no "sim".
  4. **leitura preservada** — `N8nListWorkflows` roda direto, sem pendencia.
  5. **ativar exige confirmacao propria** depois de criar.
- `tests/test_specialist_n8n.py` — node isolado: create/deactivate viram
  proposta (nao executam); execucao confirmada via token roda 1x e limpa a
  pendencia; token que nao bate / pendencia expirada -> nada executa;
  `_run_n8n_tool` preserva reads e executa escrita so com `bypass_confirmation`.
- `tests/test_n8n_guard.py`, `tests/test_graph_multiturn_state_reset.py`,
  `tests/test_graph_e2e_cybersec_guard.py` — continuam passando (sem regressao).

Lint (`ruff`) nos arquivos alterados: limpo, exceto 1 `BLE001` **pre-existente**
em `nodes.py` (o `except Exception` do loop ReAct do n8n, nao introduzido aqui).

---

## 5. Decisoes de seguranca

1. **Confirmacao no `supervisor` (deterministica) + gate no `_run_n8n_tool`
   (deterministico).** Nenhuma das duas depende do LLM respeitar o prompt. Um
   falso "sim" e a direcao perigosa -> classificador enviesado para `unclear`.
2. **Gate cobre exatamente as 4 acoes da etapa** (create/activate/deactivate/
   delete). `trigger_webhook` e leitura ficaram de fora de proposito
   (`trigger_webhook` -> backlog).
3. **Uma proposta de escrita por turno.** Fecha "criar + ativar no mesmo
   turno" (o mecanismo exato do incidente) sem heuristica lexica.
4. **A pendencia NAO e honrada por caminho implicito.** Only o par
   `supervisor detecta affirm` + `token bate na pendencia` executa. Se o LLM,
   num turno "unclear", re-propuser a mesma acao, ele cria uma **nova**
   pendencia (novo token) — nunca reaproveita a antiga sem novo "sim".
5. **Nao baixei `turn_timeout_sec`** (R4/0.2: baixar aumentaria o risco de
   acao fantasma). O alinhamento de timeout cliente/grafo (Etapa 0.2) e um
   ajuste na extensao `whatsapp-cloud` (Node), **fora deste repo** — fica no
   backlog abaixo.
6. **PII / segredos:** nenhuma credencial nova no chat/codigo; a evidencia do
   workflow usa so campos nao-sensiveis (id, nome, active, datas).

---

## 6. Riscos restantes / backlog (proximas etapas)

Nesta ordem (segue o plano da analise, secao 11 + R6):

- **P0.2 (fora deste repo)** — alinhar timeout: subir
  `ORCHESTRATOR_TURN_TIMEOUT_MS` da extensao `whatsapp-cloud` para >= 160 s
  (hoje 95 s < 150 s do grafo -> "acao fantasma"). 1 linha em
  `extensions/whatsapp-cloud/src/orchestrator-client.ts`.
- **P0 evidencia** — ler LangSmith (projeto `orchestrator-portfolio`, traces
  05/09 23:18-23:35 UTC) para fechar RC2/RC3 (instrucao exata que o supervisor
  gerou para "me avisa quando apagar").
- **Deploy** — esta mudanca ainda nao esta em producao. Buildar imagem +
  `docker compose up -d` no Contabo (ver `docs/DEPLOY_IMAGEM.md`).
- **Etapa 1 — memoria de conversa**: o supervisor/sintese ainda so leem a
  ultima frase. "esse fluxo / o ultimo / isso" continua sem resolver. Sem
  isso, o gate protege contra o *erro*, mas o usuario ainda precisa nomear o
  workflow explicitamente para desativar/excluir.
- **Etapa 2.1 completa** — hoje a confirmacao e "sim/nao" simples; falta o
  handshake ecoar tambem o **path publico do webhook** quando a acao criar/
  ativar um node `webhook` (R2.2).
- **Acao fantasma server-side** (R3.4): se o grafo e cancelado por timeout
  entre a deteccao do affirm e o `clear`, o proximo "sim" pode re-executar.
  Mitigar junto da Etapa 5.2 (reconciliacao) — precisa de sinal client->server
  de "turno anterior abortado".
- **`trigger_webhook`** — nao passa pelo gate. Avaliar se disparo de execucao
  em producao tambem deve confirmar.
- **`webhook_entity` orfa** de `Z4NOaIGb6558Dmz3` (secao 2) — limpar quando
  (e se) o workflow for excluido.
- **Etapa 6.1** — auth em `/v1/turn` **e** `/tasks/stream` + binding de
  `session_key` (R3.1). Fora do escopo P0.
- **`state.py`** — decidir sobre os ~64 comentarios de projeto removidos na
  copia pre-existente do working tree.
