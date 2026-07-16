# Técnicas de debug reutilizáveis

## Isolamento por disjuntores (circuit-breaker isolation)

Variação de bisecação/binary search aplicada a um pipeline assíncrono,
usada pela primeira vez em 2026-07-15 pra investigar o Bug 4 do
`github-repo-report` (deadlock sem CPU/rede, exigindo restart do
container — ver `docs/SESSAO_2026-07-15.md`, seção "Retomada 4").

### Quando usar

- Um pipeline com vários `await` em sequência (fetch → escreve →
  processa → monta resultado) trava esporadicamente, e você não sabe
  em qual etapa.
- Esperar o travamento acontecer de novo em produção — torcendo pra um
  log pegar o flagra — é caro (derruba um serviço real, como
  WhatsApp) ou lento (o bug é raro/intermitente).
- Existe instrumentação de timing já colocada em cada fronteira de
  `await` (ex.: `debug-timing.ts` no `github-repo-report`) — o
  isolamento por disjuntores complementa essa instrumentação, não
  substitui.

### Como funciona

1. **Divida o pipeline em blocos** na ordem em que as etapas já
   acontecem (não precisa reescrever nada, só identificar as
   fronteiras naturais — geralmente já marcadas por `await`).
2. **Adicione um gate de retorno antecipado**, controlado por uma env
   var nunca setada em produção (ex.: `MEUFEATURE_DEBUG_STOP_AFTER`),
   em cada fronteira de bloco. O gate faz a função real retornar
   *ali mesmo*, sem executar os blocos seguintes — literalmente
   "desligando o disjuntor" das etapas posteriores.
3. **Rode o pipeline real através do gate**, um bloco de cada vez,
   começando do primeiro (só bloco 1 ativo) e ligando mais um bloco por
   rodada. Chame o código de produção diretamente (a função/tool
   real), não uma reimplementação — senão você não está testando o
   bug, está testando outra coisa.
4. **Envolva cada rodada num timeout de sistema operacional**
   (`timeout -k <grace> <segundos> <comando>`), nunca só um timeout em
   JavaScript/runtime. Ver justificativa abaixo — é a parte que mais
   importa e mais fácil de esquecer.
5. **Pare na primeira etapa que travar.** Essa é a etapa culpada — some
   com os marks de timing já existentes (se houver) pra apontar a
   linha exata dentro do bloco.
6. **Se nenhuma etapa travar isolada**, isso também é um resultado
   válido e conclusivo: indica que o bug não está no pipeline testado,
   e sim em algo que só existe fora dele (orquestração externa,
   concorrência com outros processos, camada que chama o pipeline).
   Redirecione a investigação pra essa camada — não insista repetindo
   o mesmo teste isolado esperando resultado diferente.

### Por que o timeout tem que ser do sistema operacional, não do runtime

Se a hipótese em jogo for "o event loop travou de verdade" (uma
chamada nativa síncrona bloqueante, por exemplo), **qualquer timeout
implementado em JS depende do próprio event loop pra disparar** — um
`setTimeout`, um `Promise.race`, o `testTimeout` do test runner, tudo
isso é system código JS que não roda se o loop está travado. Nesse
cenário, a única coisa que garante recuperar o controle do terminal é
um timeout do kernel (`timeout(1)` no Linux/macOS, ou equivalente) —
ele manda `SIGTERM`/`SIGKILL` pro processo de fora, sem depender de
nada rodando dentro dele. Rodar sem essa proteção, torcendo pro
travamento "não acontecer dessa vez", é repetir o mesmo erro que
motivou a técnica.

### Por que testar a função real, não uma reimplementação isolada

O objetivo é decidir "o bug está aqui dentro ou está em outro lugar?".
Se você reescrever uma versão simplificada do pipeline só pro teste,
qualquer resultado (travou ou não travou) não prova nada sobre o
código de produção — só prova algo sobre a cópia. Chame a função/tool
exportada de verdade (ex.: `tool.execute(...)`), contra dados reais
quando possível (rede real, arquivo real), só pulando as camadas que
não fazem parte da hipótese em teste (no caso do Bug 4: pulou o LLM
decidindo chamar a tool e o harness do agente, porque a pergunta era
"o pipeline da tool em si trava?" — não "o agente inteiro trava?").

### Resultado negativo é informação, não fracasso

Isolar 100% das etapas óbvias sem achar o ponto de travamento **é um
resultado útil**: elimina um espaço de busca inteiro (o pipeline
testado) e redireciona a investigação pra fora dele — orquestração,
concorrência com outros processos, ou uma camada que só existe quando
o pipeline roda dentro do sistema maior. Documentar isso evita repetir
a mesma investigação depois.

### Checklist rápido pra próxima vez

- [ ] Pipeline dividido em blocos na ordem natural dos `await`s.
- [ ] Gate de retorno antecipado por env var, nunca ativa por padrão.
- [ ] Chamando a função/tool real de produção, não uma cópia.
- [ ] Timeout de sistema operacional (`timeout -k ... Ns ...`) em toda
      rodada, não só timeout de JS/test runner.
- [ ] Instrumentação de timing (`performance.now()` em cada fronteira
      de `await`) já presente ou adicionada antes de começar.
- [ ] Critério de parada definido antes de começar (achou a causa /
      esgotou os blocos óbvios / precisa de decisão que sai do escopo
      atual) — evita continuar investigando indefinidamente sem rumo.
