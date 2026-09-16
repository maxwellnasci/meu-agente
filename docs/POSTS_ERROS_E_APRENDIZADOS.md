# Erros Reais, Causas Raiz e Aprendizados — `meu-agente`

> Este documento consolida três incidentes reais já investigados e corrigidos no
> projeto `meu-agente`, na forma de (1) um dossiê técnico profundo de cada um,
> (2) um template oficial de post-mortem para uso em futuros incidentes, e
> (3) três rascunhos completos de posts para LinkedIn, prontos para revisão e
> publicação.
>
> Fontes primárias: `docs/RESOLUCAO_BUG_COMA_ETERNO.md`,
> `docs/CASE_BUG4_INVESTIGACAO_COMPLETA.md`, `P0_CONTENCAO_N8N_2026-09-06.md`,
> `ANALISE_CEREBRO_AGENTE_CONTABO_2026-09-06.md`.
>
> **Antes de publicar:** os posts abaixo foram escritos para não expor hosts,
> tokens, números de telefone, nomes de clientes ou topologia de rede real.
> Revise novamente antes de publicar — troque qualquer detalhe que ainda
> pareça específico demais do ambiente de produção real.

---

## Parte 1 — Dossiê Técnico dos Erros

### Caso 1 — "Coma Eterno": SQLite síncrono congelando o Event Loop

**Sistema afetado:** Gateway Node.js (OpenClaw), canal WhatsApp.
**Período:** 15–17/07/2026 (investigação de 3 dias).

#### Sintoma

O gateway parava de responder a webhooks do WhatsApp de forma intermitente:

- Travamentos de **zero CPU e zero rede** — não um timeout comum, um silêncio
  total em todo o sistema (gateway e sandbox).
- Nenhuma exceção, nenhum crash registrado em log.
- O `healthcheck` do Docker às vezes continuava respondendo `200 OK` no
  processo pai, mesmo com os plugins efetivamente mortos — o container nunca
  era reiniciado automaticamente.
- Mensagens do WhatsApp se acumulavam em retentativas, sem resposta.
- O primeiro caso real (15/07, 22:23) travou por 3+ minutos, recuperável só
  via `docker compose restart` manual.

#### Diagnóstico e ferramental

Logging convencional não capturava nada — o processo não morria, apenas
parava de reagir. Foi necessário construir observabilidade nova, baseada no
**Método do Disjuntor** (isolar cada etapa de um pipeline suspeito, testando
uma por vez, fora do harness completo do agente):

1. **Diagnostic Report nativo do Node**, habilitado via flags no
   `docker-compose.yml`:

   ```yaml
   command:
     - "node"
     - "--report-on-signal"
     - "--report-directory=/home/node/.openclaw/logs"
     - "dist/index.js"
     - "gateway"
   ```

2. **Heartbeat monitor externo** (`heartbeat-monitor.sh`), rodando fora do
   container, como um cão de guarda independente: pinga `/healthz` a cada 5s
   (timeout de 3s); depois de 3 falhas seguidas, dispara `SIGUSR2` direto no
   processo Node. O sinal, interceptado pelas flags do passo 1, força o V8 a
   ejetar um dump completo de call stack, memória e estado das threads.

3. **Reprodução controlada**: em vez de esperar o bug acontecer em produção,
   a equipe simulou um *lock* de 120 segundos no arquivo `openclaw.sqlite`
   para forçar a mesma condição sob observação.

A simulação revelou a mecânica exata via log de diagnóstico:

```
[diagnostic] liveness warning: reasons=event_loop_delay ... eventLoopDelayMaxMs=30064.8
```

#### Causa raiz real

O gateway usa o módulo experimental nativo `node:sqlite`, classe
`DatabaseSync`. Ao contrário de drivers assíncronos convencionais,
`DatabaseSync` executa **de forma síncrona na própria thread** — não há
event loop entre a chamada e o retorno.

Ao abrir as conexões (`src/state/openclaw-state-db.ts`), o código configurava:

```typescript
export const OPENCLAW_SQLITE_BUSY_TIMEOUT_MS = 30_000;
db.exec(`PRAGMA busy_timeout = ${OPENCLAW_SQLITE_BUSY_TIMEOUT_MS};`);
```

Mecânica do acidente:

1. Um turno de WhatsApp faz **múltiplas escritas sequenciais** no mesmo
   `openclaw.sqlite` compartilhado (fila de entrada, fila de entrega
   write-ahead, auditoria de plugin).
2. Se outro processo segura um lock de escrita no banco (modo WAL) —
   candidatos identificados mas nunca confirmados ao vivo: o container
   `openclaw-cli`, um checkpoint de WAL, um processo de backup —, o SQLite
   entra em espera respeitando o `busy_timeout` configurado: até
   **30 segundos** por chamada, antes de sequer retornar `SQLITE_BUSY`.
3. Como `DatabaseSync` é síncrono, esse bloqueio **congela o Event Loop
   inteiro** do processo Node — não apenas a query, o processo completo.
4. Com o Event Loop parado: requisições HTTP do Express se empilham em
   memória (retentativas do WhatsApp Cloud); e, criticamente, `setTimeout`
   nunca dispara — o que também **inutilizava as lógicas de circuit breaker**
   que já existiam nos hooks (`reply_dispatch`), porque a própria thread que
   executaria o timeout está bloqueada.
5. Cada escrita subsequente do mesmo turno empilha o bloqueio: na reprodução
   controlada, duas escritas reais (`sendDurableMessageBatch` +
   `pluginStateRegister`) geraram 30080ms + 30087ms = **60+ segundos**
   medidos de congelamento total, batendo com todos os sintomas observados
   (zero CPU, zero TCP, blocos parciais de resposta seguidos de silêncio,
   tabela de auditoria vazia).

#### Correção

Princípio aplicado: **fail-fast**. Preferir rejeitar uma query imediatamente
a asfixiar o servidor inteiro por até 30 segundos.

```diff
- export const OPENCLAW_SQLITE_BUSY_TIMEOUT_MS = 30_000;
+ export const OPENCLAW_SQLITE_BUSY_TIMEOUT_MS = 3_000;
```

Aplicado de forma consistente (com valores específicos por sensibilidade de
call site, de 0 a 3000ms) em três arquivos:

- `src/state/openclaw-state-db.ts`
- `src/infra/backup-create.ts`
- `extensions/migrate-hermes/apply.ts`

Com o timeout reduzido, sob a mesma contenção real medida em produção, o pior
caso de congelamento cai de ~60s para ~6s (3010ms + 3009ms) — uma redução de
~10x. A contenção do SQLite em si não desaparece (é inerente à escrita
concorrente em SQLite), mas o bloqueio passa a ser curto o bastante para não
parecer um travamento permanente: o erro é logado, tratado pelo framework, e
a próxima retentativa do WhatsApp (6s depois) encontra o servidor livre.

**Uma armadilha real no próprio deploy da correção:** a primeira tentativa de
levar o fix para produção usou `docker compose restart`/`up` sem rebuild
prévio — o que **não troca a imagem em uso**. Um grep direto no bundle
rodando *dentro do container* confirmou `busy_timeout = 30000` ainda
presente, 3h30 depois do commit do fix estar "deployado". Produção rodou, ao
vivo, com a condição exata do bug, sem que ninguém percebesse, até que uma
auditoria pediu para verificar o binário real em execução — não o
repositório.

#### Lição de engenharia

> Nunca coloque uma primitiva **síncrona** (I/O de disco, lock de banco,
> `readFileSync` fora do boot) no caminho crítico de um processo Node.js de
> request único — ela bloqueia literalmente tudo, não apenas a operação que a
> chamou, e nenhum `setTimeout`/circuit-breaker em JavaScript sobrevive a
> isso porque a própria thread que os executaria está presa. Prefira
> fail-fast (timeout curto + erro tratável) a fail-safe-mas-lento
> (timeout longo "pra garantir"): um erro rápido e recuperável na próxima
> retentativa é sempre melhor que um travamento indistinguível de um processo
> morto. E: `docker compose restart` não é deploy — sempre confirme a
> correção *dentro da imagem que está rodando de fato*, não no repositório.

---

### Caso 2 — "Apagar" interpretado como "desligar": execução autônoma indevida em produção

**Sistema afetado:** Orquestrador LangGraph (o "cérebro" do agente),
especialista de automação n8n.
**Data do incidente:** 05/09/2026, ~23:11–23:35 UTC.
**Contenção P0:** 06/09/2026.

#### Sintoma

O usuário enviou uma mensagem curta e ambígua no WhatsApp — "Me avisa quando
apagar" — sem intenção real de criar automação alguma (o contexto real era
sobre apagar um fluxo de teste que ele mesmo tinha pedido para criar minutos
antes). O agente respondeu como se tivesse entendido perfeitamente:

> "Pronto! Configurei o sistema para te avisar sempre que o computador for
> desligado ou reiniciado… webhook `shutdown-event`… O sistema já está ativo
> e monitorando."

Na prática, **um workflow real foi criado e ativado em produção** no n8n —
`Notificação de Desligamento/Reinicialização`, com `Webhook Trigger → Set →
Enviar Email`, escutando um endpoint público de "shutdown" — sem que o
usuário tivesse pedido isso, e sem qualquer confirmação prévia.

Para piorar, o pedido de apagar o fluxo original — dado dois turnos antes —
**nunca foi executado**: o agente respondeu "Claro! Vou apagar o fluxo" em
texto puro, mas a mensagem foi roteada como "conversa" e nenhuma ação de
delete rodou. O usuário saiu da conversa acreditando que tinha apagado um
fluxo e criado zero automações novas; na realidade, era o oposto exato.

#### Diagnóstico

A reconstrução do incidente cruzou três fontes independentes, apenas leitura
(sem alterar nada em produção): logs do orquestrador, logs do gateway
WhatsApp, e uma consulta `SELECT` na tabela `workflow_entity` do Postgres do
n8n. As três fontes bateram entre si e permitiram remontar a timeline exata:

| Hora (UTC) | Mensagem do usuário | O que o agente fez | Efeito real no n8n |
|---|---|---|---|
| 23:18 | "Eu queria um fluxo de n8n básico para testar…" | despacha especialista n8n → `POST /workflows` | cria fluxo de teste (**inativo**) |
| 23:21 | "…pode apagar esse fluxo que vc acabou de criar" | roteado como conversa, **não despacha** | **nada** — respondeu "Vou apagar" sem apagar |
| 23:22 | "Me avisa quando apagar" | despacha especialista n8n → `POST /workflows` + `/activate` | **cria e ativa** o workflow de "notificação de desligamento" |
| 23:23:57 | *(usuário recebe "Desculpa, tive um problema…")* | turno levou 94s; cliente WhatsApp desistiu aos 95s | workflow **já criado e ativado** — ação fantasma |
| 23:24–23:35 | "Vc criou algum fluxo?", "esse último oq faz" | roteado como conversa, sem contexto | respostas genéricas, sem memória do que aconteceu |

#### Causa raiz real

Não foi um bug isolado — foram **quatro defeitos estruturais** pré-existentes
que se alinharam numa única conversa real:

1. **O orquestrador é stateless por mensagem, na prática.** Cada mensagem
   chega como um `POST /v1/turn` independente, e uma função
   `fresh_turn_input()` zera todo o estado por-tarefa a cada chamada. A
   *intenção* do design estava certa — só `messages` deveria persistir entre
   chamadas, via o histórico do checkpointer LangGraph — mas nenhum nó do
   grafo de fato lia esse histórico: `supervisor_node` e
   `synthesize_final_node` montavam o prompt usando só a **última frase** do
   usuário. O histórico ficava gravado no SQLite (52 mensagens persistidas),
   mas completamente inerte — ninguém consumia.
2. **Ambiguidade semântica não tratada.** Fora de contexto, "apagar" em PT-BR
   pode significar tanto "excluir algo" quanto "[o sistema] desligar/apagar
   as luzes". Combinado com um prompt de supervisor que instrui tratar
   frases curtas e indiretas como comandos diretos de execução, "me avisa
   quando apagar" foi sintetizado como "crie uma automação que notifica
   quando o sistema for desligado ou reiniciado".
3. **Nenhuma ação de escrita passava por confirmação humana.** O único guard
   existente (`n8n_guard.check_destructive_n8n_action`) intercepta apenas
   `delete` e `deactivate` — `create`, `update` e `activate` passavam
   sempre, sem qualquer aprovação.
4. **O guard de delete verificava o texto errado.** Ele recebia a instrução
   *parafraseada pelo supervisor*, não a frase original do usuário — então
   mesmo se o pedido de apagar tivesse sido roteado corretamente, uma
   paráfrase sem o radical de verbo esperado (`apag`/`delet`/`exclu`/`remov`)
   teria bloqueado um delete legítimo.

Um quinto fator amplificou o dano sem ser causa: o timeout do cliente
WhatsApp→orquestrador (95s) era **menor** que o timeout total do grafo
(150s) — então qualquer tarefa de automação um pouco mais longa virava
"erro" na tela do usuário mesmo quando a ação já tinha sido executada com
sucesso no backend. O usuário via uma mensagem de falha genérica enquanto o
workflow já estava ativo em produção.

#### Correção

A contenção teve duas partes, separadas por urgência:

**Imediata (mesmo dia, sem deploy):** o workflow indevido foi desativado
diretamente no n8n (não excluído — decisão de manter o registro para
auditoria), confirmado por três fontes independentes (API REST, Postgres,
teste do webhook público retornando 404).

**Estrutural (P0, dia seguinte):** um novo módulo de confirmação —
`orchestrator/graph/n8n_confirmation.py` — passou a interceptar as quatro
ações de escrita (`create`, `activate`, `deactivate`, `delete`) antes de
qualquer execução real:

```python
# Fluxo resumido do gate de confirmação
# Turno 1: "cria um workflow chamado X"
#   -> especialista monta a chamada, mas o gate NÃO executa
#   -> grava uma pendência {action, args, token, expira em 15min}
#   -> responde: "Confirma que quer criar o workflow X? (sim/não)"
#   -> workflow NÃO foi criado

# Turno 2: "sim"
#   -> classificador determinístico (sem LLM) valida a resposta como afirmação
#   -> token bate com a pendência ainda válida -> executa de verdade
#   -> pendência é consumida (token de uso único)

# Turno 3: "sim" de novo
#   -> pendência já consumida -> nada acontece
```

Características do gate, deliberadamente conservadoras:

- **Confirmação explícita e determinística** — o classificador de resposta
  não depende do LLM respeitar instrução nenhuma; roda como código puro no
  `supervisor`, e frases ambíguas ("sim, mas muda o nome") caem no lado
  seguro (`unclear`, não executa).
- **Persistente e com TTL** — a pendência sobrevive a um restart do processo
  (gravada no checkpointer), mas expira em 15 minutos por padrão.
- **Uso único** — cada pendência tem um token aleatório; repetir "sim" depois
  de consumido não re-executa nada.
- **Uma proposta de escrita por turno** — fecha exatamente o mecanismo do
  incidente original: criar nunca arrasta uma ativação no mesmo turno sem
  passar por confirmação própria.

Validado com 87 testes (incluindo um fluxo multi-turno real pelo grafo
completo: bloqueio sem confirmação → pendência → confirmação → execução única
→ repetição inerte → negação cancela → expiração descarta).

**O que essa correção deliberadamente não resolve ainda** (registrado como
backlog, não escondido): o orquestrador continua sem ler o histórico de
conversa para resolver referências como "esse fluxo" ou "o último" — o gate
protege contra a *execução* indevida, mas o usuário ainda precisa nomear o
alvo explicitamente para desativar ou excluir algo.

#### Lição de engenharia

> Um agente autônomo que executa ações reais (criar/ativar recursos em
> produção) precisa tratar **ambiguidade de linguagem natural como sinal de
> parar, não de agir**. "Interpretar a intenção mais provável" é o
> comportamento certo para responder uma pergunta; é o comportamento errado
> para decidir se aperta o botão de criar algo em produção. A defesa correta
> não é "melhorar o prompt para entender melhor" — é adicionar uma camada de
> confirmação **determinística, fora do alcance do próprio LLM**, especificamente
> para o subconjunto de ações que mudam estado externo. E: um guard que
> analisa uma paráfrase gerada por IA, em vez do texto original do usuário,
> protege menos do que parece.

---

### Caso 3 — `clearTimeout` prematuro: corpo de resposta HTTP sem proteção de timeout

**Sistema afetado:** extensão `github-repo-report` (ferramenta que busca e
resume um repositório GitHub), parte da mesma investigação do Bug 4 (Caso 1).
**Data:** 15/07/2026, descoberto durante a implementação inicial da tool.

#### Sintoma

Durante o desenvolvimento da tool `github_repo_report`, um reteste real
travou uma conversa por **4+ minutos**, com a rede completamente zerada — sem
erro, sem timeout disparando, sem resposta.

#### Diagnóstico

O pipeline da tool (fetch do tarball → escrita em disco → extração → resumo)
foi isolado e testado fora do harness do agente inteiro, sem LLM — a mesma
técnica de disjuntores usada no Caso 1. As 4 etapas, testadas isoladamente,
completavam em menos de 1 segundo cada. Isso restringiu a busca para o código
de fetch em si.

#### Causa raiz real

O código de download do tarball do GitHub configurava um timeout de rede,
mas o cancelava (`clearTimeout`) no momento errado do ciclo de vida da
requisição:

```typescript
// Padrão com o bug (simplificado)
const timeout = setTimeout(() => controller.abort(), timeoutMs);
const response = await fetch(url, { signal: controller.signal });
clearTimeout(timeout); // <- cancela o timeout já ao receber os HEADERS
const body = await response.arrayBuffer(); // <- leitura do corpo/stream, SEM proteção nenhuma
```

`fetch` resolve sua Promise no momento em que os **cabeçalhos HTTP** chegam —
antes do corpo da resposta ter sido lido. Cancelar o timeout imediatamente
após esse `await` deixa a leitura efetiva do corpo (que pode ser um stream
grande, como um tarball) **sem proteção de timeout nenhuma**. Se a conexão
travar, atrasar, ou o servidor remoto parar de enviar dados no meio do
stream, não existe mecanismo algum para interromper — a leitura fica
pendurada indefinidamente.

#### Correção

Mover o `clearTimeout` para um bloco `finally` que envolve **toda** a
operação — fetch, leitura do corpo, escrita em disco e extração — não apenas
a obtenção dos cabeçalhos:

```diff
- const timeout = setTimeout(() => controller.abort(), timeoutMs);
- const response = await fetch(url, { signal: controller.signal });
- clearTimeout(timeout);
- const body = await response.arrayBuffer();
+ const timeout = setTimeout(() => controller.abort(), timeoutMs);
+ try {
+   const response = await fetch(url, { signal: controller.signal });
+   const body = await response.arrayBuffer();
+   // ... escrita em disco, extração ...
+ } finally {
+   clearTimeout(timeout);
+ }
```

Dois outros bugs reais foram encontrados na mesma investigação, no mesmo
espírito de "o caminho feliz funciona, o caminho de borda trava":

- **KV store rejeitando `ref: undefined` explícito.** A auditoria de cada
  chamada da tool gravava um objeto com um campo `ref` opcional que, quando
  ausente, era serializado como `undefined` literal em vez de omitido — e o
  KV store de plugin rejeita esse valor, fazendo a gravação de auditoria
  falhar silenciosamente. Corrigido com uma função que remove qualquer campo
  `undefined` antes de gravar. Notável: o design "nunca bloqueia a resposta
  ao usuário por causa de uma falha de auditoria" se provou correto na
  prática — o usuário nunca percebeu essa falha, só a auditoria ficou
  incompleta.
- **`configSchema` ausente no manifest do plugin.** Um erro de deploy —
  não de lógica — que derrubou o gateway em crash loop assim que a imagem
  foi publicada, exigindo rollback imediato (~1 minuto de downtime real)
  antes do fix ser aplicado e revalidado.

#### Lição de engenharia

> `fetch` resolve ao receber os cabeçalhos, não ao terminar de receber o
> corpo. Qualquer timeout/`AbortController` associado a uma requisição
> precisa envolver o **ciclo de vida completo** da operação — inclusive
> leitura de stream, escrita em disco e qualquer processamento subsequente —
> não apenas o `await` que resolve a Promise inicial do `fetch`. Um
> `clearTimeout` posicionado no lugar errado não causa um bug visível no
> caminho feliz (download rápido, conexão estável); ele só aparece sob
> condições de rede adversas, exatamente o cenário para o qual o timeout
> existia.

---

## Parte 2 — Template Oficial de Post-Mortem

Salve como `docs/POSTMORTEM_TEMPLATE.md` e copie para um novo arquivo
(`docs/POSTMORTEM_AAAA-MM-DD_titulo-curto.md`) a cada novo incidente real —
não edite o template em si.

```markdown
# Post-Mortem: [Título curto e descritivo do incidente]

**Data do incidente:** AAAA-MM-DD HH:MM (fuso horário)
**Data deste documento:** AAAA-MM-DD
**Autor(es):**
**Severidade:** [P0 crítico em produção / P1 alto impacto / P2 degradação / P3 menor]
**Status:** [Em investigação / Corrigido, não deployado / Corrigido e validado em produção]

---

## 1. Resumo executivo

Duas ou três frases: o que aconteceu, qual foi o impacto real (não o
potencial), e se já está corrigido. Quem só ler esta seção precisa saber o
essencial.

## 2. Impacto

- **Usuários/sistemas afetados:**
- **Duração:**
- **Dados perdidos ou corrompidos?**
- **Ações indevidas executadas em produção?** (se sim, listar exatamente
  quais, com timestamp e evidência)

## 3. Sintoma observado

Descrição objetiva do que foi visto — logs, comportamento, mensagens de
erro (ou ausência notável de erro). Evite já misturar diagnóstico aqui;
apenas o que foi *observado*.

## 4. Linha do tempo

Tabela ou lista cronológica com timestamps reais (de logs, não estimados),
desde o primeiro sinal até a contenção.

| Hora | Evento |
|---|---|
| | |

## 5. Diagnóstico e ferramental usado

Como a investigação foi conduzida: ferramentas construídas ou usadas
(scripts, sinais, dumps, queries), hipóteses levantadas, e — importante —
**hipóteses refutadas e por quê**. Uma hipótese plausível de leitura de
código que não sobreviveu a um teste real é informação valiosa, não ruído;
mantenha-a registrada.

## 6. Causa raiz real

A causa raiz confirmada por evidência (reprodução controlada, grep no
artefato real em execução, teste ao vivo) — não apenas a mais plausível na
leitura do código. Se restar alguma incerteza honesta (ex.: "o mecanismo foi
confirmado, mas não há prova direta de que foi exatamente isso que aconteceu
no incidente original"), declare isso explicitamente em vez de omitir.

## 7. Correção aplicada

Trecho de código/diff da correção real. Se houve mais de uma correção
(ex.: o bug principal + um bug secundário descoberto durante a
investigação), documente ambos separadamente.

```diff
[diff real aqui]
```

## 8. Validação

Como se sabe que a correção funciona de verdade:
- Testes automatizados (quantos passaram, algum teste novo com contraprova?)
- Confirmação de que o artefato correto está de fato rodando em produção
  (não apenas commitado) — imagem/hash/grep no binário vivo
- Teste sob carga real / reprodução controlada pós-fix

## 9. Lição de engenharia

Uma ou duas frases generalizáveis — o tipo de erro que se quer nunca mais
repetir neste projeto, não apenas "o bug X foi corrigido". Deve fazer
sentido para alguém que nunca leu o resto do documento.

## 10. O que fica em aberto (backlog)

Riscos residuais, correções estruturais que essa contenção não cobre, ou
decisões humanas pendentes. Não force um "está tudo resolvido" se não
estiver.
```

---

## Parte 3 — Posts para LinkedIn

> Os três posts abaixo estão prontos para revisão final e publicação. Nomes
> de host, números de telefone, tokens e topologia de rede real foram
> deliberadamente omitidos ou generalizados.

### Post 1 — O dia em que um SQLite síncrono congelou nosso gateway Node.js e enganou o Docker Healthcheck

---

Zero CPU. Zero rede. Nenhum erro no log. E o healthcheck do Docker dizendo
"tudo bem" o tempo todo.

Foi assim que nosso gateway de WhatsApp começou a travar, de forma
intermitente, sem deixar rastro nenhum — nenhuma exception, nenhum crash,
nenhum restart automático do container, porque o processo pai continuava
respondendo `200 OK` no healthcheck enquanto os plugins, silenciosamente,
estavam mortos.

O primeiro instinto é sempre procurar um erro. Mas quando não existe erro
nenhum para achar, o problema é outro nível: o **próprio event loop do
Node.js estava congelado**.

Para investigar isso sem esperar o bug acontecer de novo em produção,
construímos um pipeline de observabilidade novo:

→ Habilitamos o Diagnostic Report nativo do V8 (`--report-on-signal`)
→ Criamos um heartbeat monitor externo, rodando fora do container, que
checa `/healthz` a cada 5 segundos
→ Depois de 3 falhas seguidas, esse monitor dispara um sinal `SIGUSR2`
direto no processo — forçando o Node a ejetar um dump completo de memória,
threads e call stack no exato momento do travamento

O dump revelou a causa: `eventLoopDelayMaxMs=30064.8`. Trinta segundos de
delay no event loop. Um número que não existe por acidente.

A causa raiz: usávamos o módulo nativo `node:sqlite` (`DatabaseSync`) — que,
diferente de drivers assíncronos, roda **de forma síncrona na thread
principal**. E tínhamos configurado `PRAGMA busy_timeout = 30000` — ou seja,
sob contenção de escrita (outro processo segurando um lock no banco), cada
query ficava até 30 segundos **bloqueando o processo inteiro**, não apenas a
query.

Com o event loop parado, nem os nossos próprios `setTimeout` de circuit
breaker conseguiam disparar — porque a thread que os executaria estava presa
esperando o SQLite.

A correção não foi eliminar a contenção (isso é inerente a escrita
concorrente em SQLite) — foi **abraçar o fail-fast**: reduzir o timeout de
30s para 3s. Se vai falhar, que falhe rápido, gere um erro tratável, e deixe
o sistema vivo para a próxima tentativa.

**Lição que ficou:** um processo Node.js de request único não sobrevive a
nenhuma operação síncrona bloqueante no caminho crítico — nenhum
circuit-breaker em JavaScript resiste a isso, porque a própria thread que o
executaria está presa. E: sempre confirme uma correção *dentro do binário
que está rodando de fato* — tivemos uma correção corretamente commitada que
não estava, de fato, na imagem em produção, porque um restart sem rebuild
não troca a imagem.

#NodeJS #Observabilidade #EngenhariaDeConfiabilidade #SRE #Debugging #SQLite #Backend

---

### Post 2 — Quando a IA entendeu "apagar" como "desligar": o risco de agentes stateless em produção

---

"Me avisa quando apagar."

Quatro palavras. Foi o suficiente para nosso agente autônomo criar e
**ativar** um workflow real de automação em produção — sem que ninguém
tivesse pedido isso.

O que realmente aconteceu: o usuário tinha pedido, minutos antes, para
apagar um fluxo de teste que ele mesmo criou. O agente respondeu "Claro! Vou
apagar" — mas não apagou nada (a mensagem foi roteada como conversa, não
como ação). Confuso com a falta de retorno, o usuário mandou "Me avisa
quando apagar" — e, fora de contexto, "apagar" também pode significar
"desligar" em português. O agente interpretou como um pedido para criar uma
notificação de desligamento do sistema. E criou. E ativou. Em produção. Sem
perguntar.

Investigando a causa raiz, achamos não um bug — quatro problemas estruturais
empilhados:

1. Nosso orquestrador guardava o histórico da conversa num banco, mas
**nunca o lia** de volta. Cada mensagem chegava como um evento isolado — o
"cérebro" era, na prática, sem memória, mesmo tendo memória disponível.
2. O prompt do supervisor instruía tratar frases indiretas e curtas como
comandos diretos de execução — sem nenhuma saída para "pedir esclarecimento"
quando o alvo da ação é ambíguo.
3. Ações de criar e ativar recursos não passavam por **nenhum** guard ou
confirmação — só delete e desativação tinham proteção.
4. O único guard que existia checava o texto já reescrito pela IA, não a
frase original do usuário — uma camada de segurança auditando a própria
saída do sistema que deveria proteger.

A correção não foi "melhorar o prompt". Foi adicionar uma camada de
confirmação **determinística**, fora do alcance do LLM: antes de criar,
ativar, desativar ou excluir qualquer coisa, o agente agora precisa de um
"sim" explícito do usuário, num turno seguinte, validado por código — não
por instrução de prompt. Com token de uso único, expiração de 15 minutos, e
sem execução em turnos ambíguos.

**Lição que ficou:** ambiguidade de linguagem natural deve ser tratada como
sinal para *parar*, não para *agir com a interpretação mais provável* —
principalmente quando a ação em questão muda estado real em produção.
"Entender a intenção" é o comportamento certo para responder uma pergunta.
É o comportamento errado para decidir se aperta o botão.

#IA #LLM #SegurancaDeIA #HumanInTheLoop #Agentes #EngenhariaDeSoftware #AIRisk

---

### Post 3 — O perigo do `clearTimeout` prematuro em streams HTTP

---

Uma conversa travou por mais de 4 minutos. Rede completamente zerada. Nenhum
timeout disparou — mesmo tendo um timeout configurado.

O código parecia correto:

```typescript
const timeout = setTimeout(() => controller.abort(), timeoutMs);
const response = await fetch(url, { signal: controller.signal });
clearTimeout(timeout);
const body = await response.arrayBuffer();
```

O bug está numa premissa errada sobre quando o `fetch` termina.

`fetch` resolve sua Promise quando os **cabeçalhos HTTP chegam** — não
quando o corpo da resposta termina de ser lido. No código acima, o
`clearTimeout` roda logo depois desse `await`, ou seja: **antes** da
operação que realmente pode travar (ler um corpo grande, como um tarball, de
uma conexão instável).

Resultado: o timeout que deveria proteger a operação inteira só protegia a
primeira metade dela. Se a conexão degradasse durante a leitura do corpo, não
havia mecanismo nenhum de cancelamento — o processo simplesmente esperava
para sempre.

A correção foi mover o `clearTimeout` para um `finally` que envolve o
**ciclo de vida completo** da operação — fetch, leitura de stream, escrita
em disco, extração — não apenas a resolução inicial da Promise:

```typescript
const timeout = setTimeout(() => controller.abort(), timeoutMs);
try {
  const response = await fetch(url, { signal: controller.signal });
  const body = await response.arrayBuffer();
  // ... processamento subsequente ...
} finally {
  clearTimeout(timeout);
}
```

Achamos esse bug porque isolamos o pipeline inteiro em etapas — fetch,
escrita, extração, resumo — testando cada uma isoladamente, fora do
sistema completo, sem depender de reproduzir o incidente inteiro ao vivo.
Cada etapa isolada rodava em menos de 1 segundo; foi o teste do fetch
completo, sob condições reais de rede, que expôs a falha.

**Lição que ficou:** qualquer `AbortController`/timeout de rede precisa
proteger o ciclo de vida completo de uma operação assíncrona — não apenas o
primeiro `await`. Esse tipo de bug nunca aparece no caminho feliz (download
rápido, conexão estável) — só aparece exatamente na condição adversa para a
qual o timeout foi criado, o que o torna fácil de escrever e difícil de
notar em code review.

#NodeJS #Backend #HTTP #Resiliencia #EngenhariaDeSoftware #Debugging #TypeScript
