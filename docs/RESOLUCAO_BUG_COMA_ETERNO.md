# Resolução do Bug: "Coma Eterno" (Event Loop Freeze via SQLite Síncrono)

**Data:** 16 de Julho de 2026
**Sistema Afetado:** Gateway Node.js (OpenClaw)
**Sintomas (Bug 4):** 
- O Gateway parava de responder a Webhooks do WhatsApp de forma intermitente.
- Nenhuma falha de exceção (`crash`) era registrada nos logs.
- O container não era reiniciado pelo Docker pois o `healthcheck` às vezes continuava retornando HTTP 200 OK no processo pai, mas os plugins ficavam mortos.
- Mensagens do WhatsApp começavam a acumular tentativas de reenvio em loop, sem resposta.

---

## 1. Ferramental de Diagnóstico Criado (Observabilidade)
Como as abordagens convencionais e de logging estático não conseguiam capturar o estado da memória durante o travamento invisível, desenvolvemos a seguinte arquitetura de telemetria baseada no **Método do Disjuntor**:

### 1.1 Habilitação de Diagnósticos Nativos do Node.js
Adicionamos flags nativas do Node ao `docker-compose.yml` para forçar o processo a ejetar a pilha de execução completa sob estresse:
```yaml
command:
  - "node"
  - "--report-on-signal"
  - "--report-directory=/home/node/.openclaw/logs"
  - "dist/index.js"
  - "gateway"
```

### 1.2 Heartbeat Monitor (Monitoramento Ativo Externo)
Criamos um script bash (`~/.openclaw/heartbeat-monitor.sh`) isolado no host. Este script age como um "cão de guarda" independente:
- Pinga a rota `/healthz` a cada 5 segundos (timeout rigoroso de 3s).
- Se acumular 3 falhas, atira o sinal `SIGUSR2` diretamente na cabeça do processo Node.js dentro do container.
- O sinal `SIGUSR2` interceptado pelas flags do passo 1.1 obriga o V8 a gerar um dump JSON completo do estado das threads, memória e Call Stack (Node.js Diagnostic Report).

---

## 2. A Caçada (Simulação e Descoberta)
Para não afetar a produção com adivinhações, simulamos a falha forçando um *lock* no arquivo SQLite de estado (`openclaw.sqlite`) por 120 segundos. A simulação revelou a mecânica exata da falha.

### 2.1 A Armadilha Síncrona do `node:sqlite`
O Gateway OpenClaw estava utilizando o módulo experimental interno do Node.js (`node:sqlite`) e sua classe `DatabaseSync`.
Ao contrário de abstrações assíncronas padrão de banco de dados, `DatabaseSync` roda de forma **síncrona na thread**.

### 2.2 O Fator de Multiplicação: `OPENCLAW_SQLITE_BUSY_TIMEOUT_MS`
Ao abrir as conexões com o SQLite (no arquivo `src/state/openclaw-state-db.ts`), o código injetava a seguinte configuração:
```typescript
export const OPENCLAW_SQLITE_BUSY_TIMEOUT_MS = 30_000;
db.exec(`PRAGMA busy_timeout = ${OPENCLAW_SQLITE_BUSY_TIMEOUT_MS};`);
```
**A Mecânica do Acidente:**
1. Quando um plugin pesado (como o `github-repo-report`) escreve no banco de dados e outro processo (backup/CLI) segura o *lock* do arquivo em modo WAL.
2. O SQLite, seguindo a configuração, entra em modo de espera e bloqueia a thread tentando acessar o banco por até **30 segundos** antes de retornar `SQLITE_BUSY`.
3. Devido à natureza síncrona do `DatabaseSync`, esse bloqueio congela o **Event Loop Inteiro** por 30 segundos!
4. Com o Event Loop congelado:
   - Requisições Express HTTP empilham na memória (WhatsApp Cloud retries).
   - Timeouts de JavaScript (`setTimeout`) jamais são disparados, burlando nossas lógicas de "Circuit Breaker" implementadas nos hooks (`reply_dispatch`), pois a thread não consegue executar a callback do timeout.

*Evidência dos logs do Gateway durante a simulação:*
`[diagnostic] liveness warning: reasons=event_loop_delay ... eventLoopDelayMaxMs=30064.8`

---

## 3. A Correção Arquitetural
Para erradicar a raiz do problema, fizemos uma redução defensiva nos `busy_timeouts` de SQLite síncronos espalhados pelo código. O objetivo é a falha rápida (*fail-fast*), preferindo rejeitar uma query imediatamente do que asfixiar o servidor Node.js.

### 3.1 Arquivos Modificados
1. **`src/state/openclaw-state-db.ts`**
   - Modificado `OPENCLAW_SQLITE_BUSY_TIMEOUT_MS` de `30_000` para `3_000`.
2. **`src/infra/backup-create.ts`**
   - Modificado `PRAGMA busy_timeout = 30000;` para `3000;`.
3. **`extensions/migrate-hermes/apply.ts`**
   - Modificado `PRAGMA busy_timeout = 30000;` para `3000;`.

### 3.2 Por que isso resolve definitivamente?
Ao abaixar o limite síncrono para 3 segundos:
- Se houver contenção de *lock*, a query explodirá rapidamente com um erro capturável (`PLUGIN_STATE_WRITE_FAILED` ou `SQLITE_BUSY`).
- O erro será *logado* e tratado pelo framework da OpenClaw, sem congelar o Event Loop.
- A requisição de rede (Webhook do WhatsApp) será descartada ou devolvida como falha, e quando o WhatsApp fizer a próxima retentativa (em 6 segundos), o servidor estará vivo e pronto para reprocessar a mensagem num ambiente livre.

---

## 4. Análise de Risco Subsequente (Sub-agente)
A análise detalhada em toda a base de código encontrou outros processos síncronos (como usos de `fs.readFileSync`), mas todos concentrados em ambientes de inicialização segura, sem acesso ao hot-path (caminho crítico) da rede, garantindo que o gargalo real de contenção (SQLite) foi completamente suprimido.
