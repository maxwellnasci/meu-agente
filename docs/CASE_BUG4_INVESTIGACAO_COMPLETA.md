# Case Bug 4 — Investigação Completa (15–17/07/2026)

Documento consolidado da investigação de 3 dias que começou com um travamento
indefinido do WhatsApp ao usar a tool `github_repo_report` e terminou com essa
mesma tool funcionando de ponta a ponta em produção. Escrito para ser lido
sozinho, sem precisar abrir os `SESSAO_2026-07-*.md` originais — mas cada
seção linka de volta pra eles quando o detalhe bruto importar.

## 1. Resumo executivo

**O que era o Bug 4:** ao usar a tool `github_repo_report` (busca e resume um
repositório GitHub) num turno real do WhatsApp, o processo do agente
travava — sem erro, sem resposta, sem recuperação — exigindo
`docker compose restart` manual para voltar ao normal. O primeiro caso real
(15/07, 22:23) travou por 3+ minutos com **zero CPU e zero rede** em
qualquer lugar do sistema (gateway, sandbox), um padrão bem mais grave que um
timeout comum: nem um watchdog em JavaScript conseguiria se recuperar
sozinho, porque a suspeita apontava para o próprio event loop do Node
congelado.

**Status final:** o mecanismo técnico mais provável (contenção síncrona de
escrita no SQLite compartilhado) foi confirmado por reprodução controlada,
corrigido, deployado de verdade em produção e testado sob carga real do
WhatsApp múltiplas vezes sem nenhum sinal de recorrência. Dois outros bugs
reais — descobertos *durante* a investigação, não parte do sintoma original —
também foram corrigidos e confirmados. Hoje (17/07, à noite) a tool está
conectada em produção, com a configuração correta, e um `tool.call` real foi
capturado ao vivo no WhatsApp do usuário, entregando um relatório estruturado
de verdade.

**Ressalva honesta, mantida do início ao fim deste documento:** a causa exata
do incidente original de 15/07 — quem especificamente segurava o lock do
SQLite naquele momento exato — nunca foi capturada com evidência ao vivo no
instante em que aconteceu. O mecanismo identificado é o candidato mais forte,
consistente com todos os sintomas observados (zero CPU, zero rede, silêncio
total, sem erro visível, recuperável só por restart), reproduzido de forma
controlada múltiplas vezes, e a correção aplicada elimina esse mecanismo onde
quer que ele apareça — mas não há uma prova retroativa de que foi exatamente
isso que aconteceu às 22:23 do dia 15/07. Essa distinção entre "mecanismo
confirmado e corrigido" e "causa exata do incidente histórico provada" é
central para este case e reaparece na seção 7.

## 2. Linha do tempo da investigação

### Dia 1 (15/07) — descoberta do sintoma, 3 bugs de implementação, primeira ocorrência do Bug 4

A tool `github_repo_report` foi desenhada e implementada do zero nesta
sessão: schema fechado (`{repo: enum, ref?}`), execução 100% no processo do
gateway (nunca no sandbox Docker), política de aprovação por repo
(`registerTrustedToolPolicy`), auditoria via hook `agent_end`. Três bugs reais
de implementação apareceram e foram corrigidos ao longo do dia:

- **Bug de deploy — `configSchema` ausente:** o manifest do plugin sem esse
  campo obrigatório derrubou o gateway em crash loop assim que a imagem foi
  deployada. Rollback imediato pra imagem anterior (~1min de downtime real),
  fix aplicado e validado antes do rebuild seguinte.
- **Bug de auditoria — `ref: undefined` quebrava a gravação:** o KV store de
  plugin rejeita campos `undefined` explícitos; a auditoria de cada chamada
  falhava silenciosamente (sem travar a resposta ao usuário — o design
  "nunca bloqueia" aguentou até sob essa falha real). Fix: função que remove
  qualquer campo `undefined` antes de gravar.
- **Bug de timeout — corpo HTTP sem proteção:** o `clearTimeout` do fetch do
  tarball do GitHub rodava logo após os cabeçalhos chegarem, deixando a
  leitura do corpo sem timeout. No reteste, uma conversa real travou 4+
  minutos com rede zerada. Fix: mover o `clearTimeout` pro `finally` que
  envolve a operação inteira (fetch + leitura do corpo + escrita + extração).

**Primeira ocorrência do Bug 4 propriamente dito:** depois de resolver uma
pendência de ambiente (Node do host sem suporte nativo a TypeScript — builds
locais via `pnpm build` não funcionam, mas `docker build`/`docker compose
build` funcionam normalmente porque rodam com o Node oficial dentro do
container) e uma regressão à parte (Docker CLI ausente numa imagem
buildada sem o `--build-arg` certo), a tool foi reconectada e testada com
"analisa o mox" — e travou de verdade: 3+ minutos sem nenhuma atividade,
CPU ociosa em todos os containers, zero conexão TCP `ESTABLISHED` em lugar
nenhum. Recuperado com `docker compose restart`; tool revertida de novo.

**Primeira hipótese avaliada e refutada (com evidência, não só leitura de
código):** o DeepSeek propôs que a extração do tarball (`tar.x()`, zlib
nativo) ignorava o `AbortSignal` num tarball truncado. Lendo o código-fonte
real da dependência (`@openclaw/fs-safe/archive.js`), a proteção proposta
**já existia** uma camada abaixo — aplicá-la de novo seria redundante e não
mudaria o comportamento no cenário descrito. Também não batia com o sintoma
(zero atividade de rede, quando a hipótese previa um download travado).

**Isolamento por disjuntores:** o pipeline inteiro da tool (fetch → escrita
→ extração → percorrer árvore → montar relatório) foi testado diretamente,
fora do harness do agente, fora do gateway, sem LLM — 4 etapas, todas
completando em menos de 1 segundo, sem nenhum gap suspeito. Isso **isentou a
extensão em si** como causa: o problema estava em código fora da fronteira
de `extensions/github-repo-report/`.

**Hook sem timeout confirmado (mecanismo, não causa ainda):** um teste
isolado provou que `before_agent_finalize` não tem timeout padrão no
framework — uma promise pendurada ali trava a resposta pra sempre, mesmo
avançando 24h de tempo virtual. Uma varredura completa em seguida (lendo
todo `src/` e `extensions/`) mostrou que **nenhum plugin ativo em produção
registra esse hook** — o gap existe no framework, mas está inerte neste
deployment. Uma segunda varredura com sub-agentes catalogou mais 9 hooks sem
timeout padrão no framework inteiro, sinalizando 2 como "perigo alto":
`acpx`/`reply_dispatch` e `memory-core`/`before_agent_reply` — ambos viraram
pistas centrais do Dia 2.

### Dia 2 (16/07) — hipóteses de hook refutadas uma a uma, reprodução empírica não dispara o bug, mecanismo real confirmado ao vivo

**Achado 0, fora do escopo original:** logo no início da auditoria deste dia,
produção foi encontrada rodando com a combinação de risco (tool conectada +
allowlist) **sem que isso estivesse em nenhum registro de sessão** — e pior,
rodando numa imagem Docker criada *antes* do commit de um fix que supostamente
a protegia. Revertido imediatamente. Lição registrada:
[[feedback_revert_temp_config_immediately]] — mudanças temporárias de config
feitas durante investigação precisam ser revertidas na hora, não "no fim da
sessão".

**Hipótese `acpx`/`reply_dispatch` (2ª refutação):** uma sessão separada do
Antigravity havia concluído que esse hook sem timeout, usado por `acpx`, era
a causa, e aplicado um fix (2 linhas em `hooks.ts`) sem nunca rodar o próprio
teste. Auditoria: o diff estava tecnicamente correto e bem testado (77/77
hooks tests passando, contraprova real confirmando que sem o fix o handler
trava indefinidamente) — mas **`acpx` nunca esteve instalado neste
deployment**. O log do incidente original listava os 9 plugins carregados
naquele exato momento, sem `acpx` entre eles. O fix não pode ter corrigido
algo que nunca esteve ativo. Hardening válido para o futuro, não o fix do
Bug 4.

**Hipótese `memory-core`/`before_agent_reply` (3ª refutação):** esse hook
só dispara com `trigger === "cron"`, nunca com `"heartbeat"` (confirmado nos
dois únicos call sites reais do código) — e a tabela de cron jobs no SQLite
compartilhado tinha **zero linhas**, nunca existiu um job desse tipo. A
pré-condição de disparo nunca foi satisfeita neste deployment.

**Rodada empírica com sub-agentes paralelos e ambiente isolado:** montado um
stack Docker Compose completo, isolado de produção, replicando a config real
do incidente, disparando turnos via CLI direto (sem WhatsApp real). 21
invocações reais da tool, 17 delas com o pipeline completo disparando de
verdade (sequencial e paralelo) — **nenhuma reproduziu o travamento**, todas
as 12 marcas de timing completaram em ordem. Um monitor externo independente
confirmou (253 amostras, ~13min) que CPU nunca chegou a zero absoluto durante
o teste. Um terceiro sub-agente varreu os 7 hooks restantes sem timeout
padrão do framework: todos descartados (plugin que os registraria não está
instalado, ou não existe nenhum registro real em produção). **Isso esgotou
o vetor "hook sem timeout + plugin ativo"** como explicação.

**Hipótese do payload gigante no DeepSeek (4ª refutação):** uma segunda
sessão do Antigravity propôs que um relatório de ~89 mil tokens fazia o
DeepSeek "engasgar" silenciosamente, e que `timeoutMs` chegando `undefined`
deixava o fetch esperando pra sempre. Refutado com evidência real, não só
leitura: o log do incidente original mostrava **zero conexão TCP
`ESTABLISHED`** (inconsistente com uma conexão viva mas silenciada); o
payload real medido (rodando a tool de verdade) era de ~5.278 tokens, ~20x
menor que o alegado; e o fix, quando testado de verdade, quebrava 4 testes
pré-existentes do core que documentavam o contrato oposto como intencional.
Diff revertido.

**O mecanismo real, confirmado ao vivo (candidato mais forte até hoje):**
partindo de uma reformulação do problema ("zero CPU + zero rede só pode ser
promise pendurada ou event loop congelado num syscall que dorme") e de dois
achados de código (o "zero rede" original só provava "zero TCP" —
`/proc/net/tcp` não vê o Docker socket montado; e já existe um timeout
global de 30 min no undici, descartando de vez a hipótese de fetch
pendurado), foi reproduzido experimentalmente: um turno de WhatsApp faz
**múltiplas escritas sequenciais** no mesmo `state/openclaw.sqlite`
compartilhado (fila de entrada, fila de entrega write-ahead, auditoria de
plugin). Com outro processo segurando `BEGIN IMMEDIATE` no banco, cada
escrita real do caminho de produção (`sendDurableMessageBatch` +
`pluginStateRegister`) travou o event loop **de forma síncrona** pelo
`busy_timeout` de 30 segundos configurado, empilhando: 30080ms na fila +
30087ms na auditoria = 60+ segundos de congelamento medido, batendo com
todos os sintomas (zero CPU, zero TCP, dois blocos parciais entregues e
depois silêncio, tabela de auditoria vazia). O que faltou fechar: identificar
quem segurava esse lock por minutos no incidente real de 15/07 — candidatos
não investigados (o container `openclaw-cli`, checkpoint do WAL, processo
de backup).

### Dia 3 (17/07) — correção real deployada, mais um bug encontrado e corrigido, e a causa de "por que o modelo não usa a tool"

**Deploy da correção falhou silenciosamente na primeira tentativa.** Uma
sessão paralela relatou ter aplicado a correção (`busy_timeout` de 30s para
3s em 3 arquivos), reiniciado produção e confirmado — mas a auditoria pedida
pelo usuário revelou que o "restart" usado (`docker compose restart`/`up`
sem rebuild prévio) **nunca troca a imagem em uso**. Grep direto no bundle
rodando dentro do container confirmou `busy_timeout = 30000` ainda presente
— a imagem em produção tinha sido criada 3h30 *antes* do commit do fix.
Produção rodava, ao vivo, com a condição exata do bug, sem que ninguém
tivesse percebido.

**Correção real aplicada e confirmada:** 2 testes desatualizados corrigidos,
suíte completa rodada (117/117), **`docker build` de verdade** (não
restart), confirmado por grep dentro da imagem nova que só restavam os
valores esperados (`0/1000/2000/3000`, nunca `30000`), redeploy real
(`down`/`up`), imagem confirmada via `docker inspect` batendo com o hash do
build. Testado sob carga real do WhatsApp (`healthz` nunca degradou) e via
reprodução controlada contra o commit exato da imagem rodando: bloqueios
caíram de 60167ms para 6019ms (3010+3009ms) — o mecanismo mudando
exatamente como esperado.

**Bug novo descoberto ao testar a reconexão:** com o fix do SQLite
confirmado em produção, um teste controlado de reconexão (com 4 monitores
independentes preparados antes) revelou um travamento **diferente** — "hang
de aprovação" de mais de 4 minutos, sem erro, sem degradação de `healthz`,
sem CPU zerada. Investigação com sub-agentes em paralelo achou a causa: a
policy da tool tratava "repo desconhecido" (o modelo mandando `"mox"` em vez
do slug exato `"Mox---Sistemas"`) da mesma forma que "repo conhecido mas
desabilitado" — entrando num fluxo de aprovação humana com timeout de ~130
segundos, e o canal WhatsApp Cloud não tem nenhum mecanismo de entrega de
aprovação (sem botão, sem quick-reply). Um bug secundário e independente
também foi achado no detector nativo de sessão travada do framework
(`recordRunCompleted` limpava estado compartilhado sem escopo por `runId`,
cegando o detector pra esse tipo de travamento).

**Ambos corrigidos, testados (390/390) e confirmados ao vivo** — dois testes
reais consecutivos de "analisa o mox" depois do fix, resposta rápida em
ambos, sem hang.

**A descoberta final da noite:** numa 2ª rodada de confirmação, o usuário
reconectou a tool e pediu explicitamente para forçar a chamada real (não uma
resposta de deflexão). O modelo **nunca chamou `github_repo_report`** em 3
tentativas — usava `web_fetch` genérico pra raspar HTML do GitHub direto,
chegando a produzir um relatório plausível mas fabricado por um caminho
errado. Investigação da trajetória do agente revelou a causa: a lista de
tools enviada ao modelo simplesmente **não incluía** `github_repo_report`. A
tool é marcada `optional: true` no manifest do plugin, e tools opcionais só
entram com allowlist explícita — e a "diff de sempre" usada em *todas* as
tentativas anteriores (dias 1, 2 e 3) colocava esse allowlist em
`tools.sandbox.tools.alsoAllow`, um caminho que só tem efeito com sandbox
ativo; este deployment roda com `sandbox.mode: "off"`, tornando essa chave
config **tecnicamente presente mas funcionalmente morta** desde o início.
Corrigido para `tools.alsoAllow` no nível raiz do arquivo, verificado que a
lista de tools do modelo passou a incluir a tool, e — depois de um reset de
sessão pra limpar a memória de um relatório improvisado anterior — um
`tool.call` real foi capturado ao vivo no WhatsApp do usuário: `toolName:
github_repo_report`, `isError: false`, relatório estruturado real entregue.

## 3. Os 2 bugs reais de mecanismo corrigidos

### Bug A — contenção síncrona de SQLite (`busy_timeout`)

**Sintoma:** travamento total do processo (zero CPU, zero rede) por dezenas
de segundos a minutos, sem erro visível, exigindo restart manual.

**Causa:** escritas sequenciais no `state/openclaw.sqlite` compartilhado
(fila de entrada, fila de entrega, auditoria) usam `node:sqlite` de forma
síncrona. Quando outro processo segura um lock de escrita, cada chamada
trava o event loop inteiro pelo valor configurado de `busy_timeout` — que
estava em **30 segundos**, empilhando a cada escrita subsequente do mesmo
turno.

**Correção:** `busy_timeout` reduzido de 30.000ms para 3.000ms em 3 arquivos
(`manager-reindex-lock.ts`, `qmd-manager.ts`, e o schema principal, com
valores específicos por call site: 0/1000/2000/3000ms conforme a
sensibilidade de cada um). Commit `42af0a959a`. Reduz o pior caso de
congelamento em ~10x sem eliminar a contenção em si (que é uma característica
do SQLite sob escrita concorrente), mas torna qualquer trava dessa família
curta o suficiente para não parecer um travamento permanente.

**Confirmação:** deploy real verificado por grep no bundle rodando (não só
no código-fonte), testado sob carga real do WhatsApp múltiplas vezes ao
longo do dia 3, `healthz` nunca degradou em nenhum teste.

### Bug B — policy sem bloqueio imediato para repo desconhecido

**Sintoma:** um turno pedindo análise de um repositório usando um nome que
não é o slug exato (ex.: `"mox"` em vez de `"Mox---Sistemas"`) ficava
pendurado por ~130 segundos sem erro, sem resposta, sem forma de o usuário
agir — porque o canal WhatsApp Cloud não tem mecanismo de entrega de
aprovação interativa.

**Causa:** `extensions/github-repo-report/src/policy.ts` tratava "repo fora
do enum" exatamente igual a "repo no enum mas desabilitado" — ambos caindo
no fluxo `require-approval` (timeout de ~120s + 10s de graça).

**Correção:** a policy agora distingue os dois casos — repo reconhecido mas
desabilitado continua pedindo aprovação (comportamento preservado); repo
**não reconhecido** bloqueia imediatamente, usando o campo `block`/
`blockReason` já existente e testado no framework (terminal, nunca entra em
aprovação). Um bug secundário e independente também foi corrigido no mesmo
lote: o detector nativo de sessão travada do framework
(`diagnostic-run-activity.ts`, `recordRunCompleted`) limpava
incondicionalmente o estado de atividade compartilhado da sessão inteira, em
vez de escopar por `runId` — isso o deixava cego justamente para esse tipo
de travamento (nunca disparava o alerta, mesmo com o threshold baixado para
15s de teste).

**Confirmação:** 390/390 testes passando (incluindo um teste novo com
contraprova real — rodado contra o código antigo, confirmado que falha do
jeito esperado antes de restaurar o fix), deploy real, dois testes ao vivo
consecutivos com resposta rápida.

## 4. Correção de configuração (não era bug de código)

Depois dos dois bugs de código acima estarem corrigidos e deployados, a tool
continuava não sendo usada pelo modelo em produção — mas por um motivo
inteiramente diferente, e que não é um bug no sentido de "código errado": é
uma configuração tecnicamente presente, mas lida pelo caminho errado.

`github_repo_report` é marcada `optional: true` no manifest do plugin
(`toolMetadata`), e o framework exige allowlist explícita para tools
opcionais — sem isso, elas simplesmente não entram na lista de tools que o
modelo recebe (diferente de tools de plugin "default", que aparecem sem
allowlist nenhum). A configuração usada em **todas** as tentativas de
reconexão dos 3 dias desta investigação colocava esse allowlist em:

```json
"tools": { "sandbox": { "tools": { "alsoAllow": ["github_repo_report"] } } }
```

Essa chave só tem efeito quando `agents.defaults.sandbox.mode` não é
`"off"` — e este deployment roda com sandbox desligado. Ou seja, a config
existia no arquivo, parecia correta, e nunca teve efeito nenhum. A correção
foi mover para o nível raiz do arquivo, que é onde o mecanismo de resolução
de allowlist do framework (`globalPolicy` → `collectExplicitAllowlist`) de
fato lê:

```json
"tools": { "alsoAllow": ["github_repo_report"] }
```

Verificado por dois caminhos independentes: (1) um turno de agente isolado
via CLI mostrou a lista `context.compiled.tools` passando de 31 para 32
tools, agora incluindo `github_repo_report`; (2) um turno real do WhatsApp
do usuário, depois de um reset de sessão, produziu um `tool.call` de verdade
(`toolName: github_repo_report`, `isError: false`) com o relatório
estruturado real entregue.

## 5. Metodologia aplicada

Esta investigação usou um conjunto pequeno e repetido de técnicas, que se
provaram mais valiosas do que qualquer hipótese individual — a maioria das
hipóteses testadas estava errada, mas o método de testá-las impediu que
qualquer uma virasse uma correção falsa em produção.

**Técnica de disjuntores (isolamento por etapas):** em vez de reproduzir um
turno de agente completo (LLM + harness + hooks + canal) para achar onde um
pipeline trava, cada etapa é isolada e testada sozinha, fazendo a função real
retornar cedo em pontos sucessivos ("desligando um disjuntor" por vez). Foi
o que provou que o pipeline da própria extensão (fetch → extração →
relatório) não era a causa — 4 etapas, todas rodando em menos de 1 segundo,
sem tocar no WhatsApp real nenhuma vez. Documentado em
`docs/TECNICAS_DEBUG.md` e [[technique_circuit_breaker_isolation]].

**Múltiplos modelos de IA como ferramentas de investigação, com auditoria
cruzada obrigatória:** hipóteses vieram de sessões separadas rodando
DeepSeek e Antigravity (Sonnet), e cada uma foi auditada com o mesmo rigor
antes de ser aceita — nenhuma foi aceita de primeira. Das 4 hipóteses de
causa raiz propostas por essas sessões (zlib/tar truncado, `acpx`/
`reply_dispatch`, `memory-core`/`before_agent_reply`, payload gigante no
DeepSeek), **todas as 4 foram refutadas** por evidência real, não por
"parecer razoável". A 5ª hipótese (contenção do SQLite) foi a que resistiu à
mesma auditoria. Ver [[technique_parallel_subagents_mandatory_repro]].

**Regra de ouro, validada repetidamente: nunca aceitar uma correção como
resolvida sem reprodução real e confirmação no bundle rodando.** Isso se
provou necessário mais de uma vez nesta mesma investigação:
- O fix do `acpx` estava corretamente implementado e testado — mas o plugin
  nunca esteve instalado neste deployment. Só a checagem do log real de
  plugins carregados revelou isso.
- O fix do `busy_timeout` estava corretamente commitado — mas a imagem
  rodando em produção era anterior ao commit. Só o grep dentro do container
  vivo (não no código-fonte) revelou isso.
- A tool `github_repo_report` estava corretamente registrada e habilitada —
  mas nunca aparecia na lista de tools do modelo. Só a inspeção da
  trajetória real do agente (`context.compiled.tools`) revelou isso.

Três instâncias diferentes do mesmo padrão: "o código/config está certo, mas
o sistema rodando não reflete isso" — ver [[feedback_verify_dependency_source_before_fix]]
e [[feedback_verify_plugin_actually_loaded]].

## 6. Lições aprendidas

- **`docker compose restart` (ou `up` sem rebuild prévio) não troca a
  imagem em uso.** Qualquer correção de código que precise chegar em
  produção via Docker exige `docker build` explícito, seguido de
  confirmação (`docker inspect --format '{{.Image}}'` comparado com a saída
  do build) — nunca assumir que um restart "pegou" a mudança.
- **Hipóteses plausíveis de leitura de código precisam de confirmação
  empírica antes de virar correção.** Das 5 hipóteses de causa raiz
  levantadas ao longo da investigação, 4 pareciam razoáveis lendo o código e
  foram refutadas assim que testadas contra o estado real do sistema
  (plugin não instalado, precondição de trigger nunca satisfeita, payload
  real 20x menor que o alegado, evidência de rede contradizendo o
  mecanismo).
- **Um sintoma pode ter mais de uma causa raiz ao mesmo tempo.** O
  travamento original de "analisa o mox" e o "hang de aprovação" descoberto
  no dia 3 pareciam o mesmo tipo de falha (turno que trava sem resposta) mas
  eram mecanismos completamente diferentes (SQLite síncrono vs. timeout de
  aprovação de ~130s) — corrigir um não corrige o outro, e é preciso
  verificar a assinatura exata (CPU, rede, presença de erro) para não
  confundir os dois.
- **Configuração pode estar "tecnicamente presente" mas funcionalmente
  inativa.** O caso do allowlist em `tools.sandbox.tools.alsoAllow` —
  sintaticamente válido, semanticamente sem efeito nenhum com
  `sandbox.mode: "off"` — persistiu por 3 dias inteiros de tentativas porque
  nada no sistema avisa que uma chave de config é lida por um caminho morto.
  A única forma de pegar isso foi inspecionar o artefato real que o
  framework monta para o modelo (`context.compiled.tools`), não o arquivo de
  config em si.

## 7. Ressalva honesta final

O mecanismo técnico identificado — contenção síncrona de escrita no SQLite
compartilhado sob `busy_timeout` alto — é o candidato mais forte e mais
bem-testado desta investigação inteira: reproduzido de forma controlada
múltiplas vezes usando os caminhos reais de código de produção, consistente
com cada detalhe observado do incidente original (zero CPU, zero conexões
TCP, dois blocos parciais entregues antes do silêncio, tabela de auditoria
vazia, recuperável só por restart), e a correção que o elimina foi deployada
e testada sob carga real sem nenhum sinal de recorrência.

**O que não existe é uma prova retroativa e direta de que foi exatamente
esse mecanismo que causou o incidente específico de 15/07 às 22:23.**
Ninguém capturou uma stack trace, um dump de processo, ou qualquer evidência
ao vivo mostrando *quem* segurava o lock de escrita naquele momento exato —
os candidatos levantados (o container `openclaw-cli`, um checkpoint de WAL,
um processo de backup) nunca foram investigados até o fim. A reconstrução
foi feita por engenharia reversa rigorosa (reproduzir o mecanismo, comparar
sintomas, eliminar alternativas por evidência), não por observação direta do
evento original.

Essa mesma disciplina se aplicou de novo no dia 3: a descoberta de que a
tool nunca esteve exposta ao modelo em nenhuma tentativa anterior também
**reabre** uma conclusão que já parecia fechada — o "hang de aprovação de
~130s" atribuído à `policy.ts` no dia 3 foi inferido lendo o código da
policy, nunca capturado com um `tool.call` de `github_repo_report`
efetivamente acontecendo (porque agora sabemos que o modelo nunca recebeu a
tool para chamar naquelas tentativas específicas). O bug de policy em si é
real e a correção é sólida (validada por invocação direta contra o código de
produção), mas a ligação causal exata com aqueles travamentos de mais de 4
minutos específicos permanece, honestamente, uma inferência bem fundamentada
— não uma certeza observada.

## 8. Estado atual do sistema

- **`github-repo-report`:** conectado em produção, com a configuração
  correta (`tools.alsoAllow` no nível raiz). Confirmado funcionando de ponta
  a ponta no WhatsApp real: modelo recebe a tool na lista, chama de verdade,
  policy libera o repo habilitado, fetch real do GitHub roda, relatório
  estruturado é entregue — capturado ao vivo com `toolName:
  github_repo_report`, `isError: false`.
- **Bug 4 (contenção SQLite):** mitigado e deployado (`busy_timeout` 30s →
  3s), testado sob carga real repetidamente, sem recorrência.
- **Bug do "hang de aprovação" (~130s para repo desconhecido):** corrigido
  (bloqueio imediato) e testado ao vivo com sucesso.
- **Bug do detector de sessão travada** (limpeza de estado sem escopo):
  corrigido junto com o item acima.
- **Configuração de exposição da tool ao modelo:** corrigida (allowlist no
  caminho certo do arquivo).
- **Nenhum bug ativo conhecido** relacionado a esta investigação. Sessões
  de teste e backups temporários do processo de investigação já foram
  limpos do ambiente de produção.

---

*Fontes: `docs/SESSAO_2026-07-15.md`, `docs/SESSAO_2026-07-16.md`,
`docs/SESSAO_2026-07-17.md`. Consolidado em 2026-07-17.*
