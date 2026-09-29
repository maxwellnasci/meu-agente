# Plano: Copiloto SRE / Plantonista via WhatsApp

Status: planejamento (visão estratégica alinhada com Max; nenhuma etapa de
código implementada ainda). Este documento registra a arquitetura acordada
para viabilizar diagnóstico e correção de infraestrutura/bugs de extensões
diretamente pelo WhatsApp, sem depender de notebook aberto.

## 1. Visão Geral e Objetivo Operacional

Hoje o atendimento a incidentes de clientes exige o Max sentado com o
notebook aberto, terminal na VPS, investigando manualmente. A visão é dar
ao Max — e, por extensão, ao ecossistema `meu-agente` — a capacidade de
atuar como **Copiloto SRE e plantonista de emergência via WhatsApp**: o
canal de atendimento já existente (Amigão) vira também o canal de operação
da infraestrutura.

Caso de uso real que motiva o desenho:

> Max está na rua, longe do computador. Um cliente reporta no WhatsApp:
> "o bot caiu". Max reencaminha ou digita para o próprio agente: "analisa
> o servidor do cliente X". Em segundos, o agente faz a triagem (containers
> de pé? healthcheck respondendo? logs com stack trace?) e devolve um
> diagnóstico preciso. Se a causa for simples e de baixo risco (serviço
> travado, log cheio), o agente corrige autonomamente e avisa o que fez.
> Se a causa for crítica (mudança de `.env`, migration, alteração de
> compose), o agente **não age sozinho** — descreve o problema, propõe a
> correção e pede confirmação explícita do Max antes de tocar em produção.

O objetivo não é substituir o Max sentado investigando a fundo — é cobrir
a lacuna entre "cliente reporta problema" e "Max consegue abrir o
notebook", que hoje pode ser de minutos a horas.

## 2. Viabilidade Técnica do Claude Code na VPS Contabo

### 2.1 Autenticação via conta mensal (Claude Pro/Max)

O Claude Code suporta login via OAuth (`claude login`) mesmo em ambiente
headless (sem navegador local): o CLI imprime uma URL de autorização, o
Max abre essa URL em qualquer navegador (celular incluso), autoriza, e a
sessão fica persistida no host. Isso evita o custo por token da API pública
— o consumo é debitado da cota do plano mensal (Pro/Max) já pago pelo Max,
não de uma chave de API separada.

### 2.2 Atenção às cotas de janela (5h)

A cota de uso do plano mensal é uma **janela compartilhada de ~5h** com a
interface web/desktop do Claude. Isso tem duas implicações práticas para
este projeto:

- Se o Max estiver usando o Claude normalmente (web, desktop, outro
  Claude Code) na mesma janela, o consumo do copiloto SRE soma-se ao
  mesmo teto.
- O Claude Code em modo autônomo (`-p`, com ferramentas de leitura de
  arquivos, `grep`, `docker logs`, etc.) tende a inspecionar **muitos**
  arquivos e comandos por tarefa — o consumo de tokens por chamado de
  plantão é maior do que uma pergunta pontual na web. Um incidente mal
  delimitado (escopo amplo, "investiga tudo") pode consumir uma fatia
  desproporcional da janela de 5h.

Mitigação: o escopo de cada acionamento deve ser o mais restrito possível
(ver §4 — Claude Code só entra quando é bug de código confirmado, já
delimitado a um diretório/cliente), e a telemetria leve (Nível 1, §3) deve
resolver a maioria dos chamados sem nunca acionar o Claude Code.

### 2.3 Desafio do timeout do WhatsApp

O Claude Code raciocinando e iterando sobre código real leva tipicamente
**2 a 5 minutos** — muito acima do que qualquer canal de mensageria trata
como resposta síncrona (a API do WhatsApp Cloud e o próprio usuário não
esperam esse tempo parados numa única requisição). O desenho precisa ser
assíncrono:

1. **Confirmação de recebimento imediata**: assim que o pedido chega
   ("analisa o servidor do cliente X"), o agente responde na hora
   confirmando que a triagem começou (ex.: *"Entendido, verificando o
   servidor da Clínica Vida agora..."*), para o Max saber que o pedido foi
   recebido e não repetir/duvidar.
2. **Disparo proativo ao concluir**: o resultado (diagnóstico, correção
   aplicada, ou pedido de confirmação de risco) é enviado como mensagem
   nova assim que a tarefa termina — não como resposta síncrona à mesma
   requisição HTTP. Isso já tem precedente arquitetural no projeto: o
   padrão de escalonamento humano assíncrono via WhatsApp (`ask-max`,
   ver memória do projeto) resolve exatamente esse tipo de notificação
   fora do ciclo requisição/resposta.

### 2.4 Risco de segurança crítico no host de produção

A VPS Contabo **não é um ambiente de laboratório** — ela roda o ambiente de
produção real: Amigão (WhatsApp), n8n oficial, PostgreSQL, túneis
Cloudflare, e os deployments dos clientes (ver
`docs/PADRAO_CLIENTES_DOCKER.md`). Isso implica uma regra rígida e não
negociável:

> **Claude Code em modo autônomo (`-p`) NUNCA deve rodar solto no host,
> nem com acesso ao `/var/run/docker.sock`.**

O motivo é o mesmo já documentado para os tenants de clientes em
`docs/PADRAO_CLIENTES_DOCKER.md` §2 (regra de segurança "`docker.sock`
desativado"): um agente com acesso ao socket do Docker tem controle total
do host — pode criar containers privilegiados, montar `/`, ler segredos de
qualquer outro tenant. Um agente de código que processa instruções
potencialmente ambíguas vindas de um chamado de incidente (texto livre,
sob pressão de "resolve isso agora") é exatamente o tipo de superfície que
não pode ter esse nível de acesso direto. Daí a arquitetura de 3 níveis do
§3 e o isolamento por sandbox do §4.

## 3. Arquitetura em 3 Níveis — Defesa em Profundidade

O princípio geral: quanto mais barata e rápida a ação, mais autonomia ela
tem; quanto mais cara ou irreversível, mais ela para e espera confirmação
humana. Este é o mesmo espírito do "Cão de Guarda"/disjuntor já usado em
`docs/METODO_DISJUNTOR_SUBAGENTES.md` e nos guardas do orquestrador
(`orchestrator/src/orchestrator/graph/n8n_guard.py`,
`graph/cybersec_guard.py`), aplicado agora ao domínio de infraestrutura.

### Nível 1 — Telemetria Read-Only (15-30s)

Sempre a primeira etapa de qualquer chamado. Só leitura, sem nenhum efeito
colateral, execução rápida o suficiente para caber numa única resposta
"quase síncrona":

- Healthchecks HTTP/TCP dos serviços do cliente (mesmo padrão de
  `GET /health` já validado em `docs/PADRAO_CLIENTES_DOCKER.md` §6.3).
- `docker compose ps` no diretório do cliente — containers de pé, reiniciando
  em loop, ou parados.
- Consumo de memória/disco/CPU do host e dos containers (`docker stats`,
  `df -h`, sinal de OOM).
- `docker logs --tail=50` de cada serviço relevante, caçando stack traces,
  erros de conexão, timeouts.

Resultado: diagnóstico direto no WhatsApp do Max, sem nenhuma ação tomada.
Boa parte dos chamados ("caiu", "não responde") se resolve só com esse
nível — muitas vezes revelando um serviço reiniciando em loop ou um disco
cheio, sem precisar de nenhuma inteligência de código.

### Nível 2 — Correção Autônoma Segura

Ações de **baixo risco, reversíveis e sem perda de dados**, que o agente
pode executar sem pedir confirmação prévia porque o pior caso é equivalente
a "não ter feito nada":

- `docker compose restart <serviço>` quando o serviço está travado/em loop
  de crash mas os dados (volumes, `.env`) não são tocados.
- Rotação/limpeza de logs que encheram o disco.
- Reinício de túnel/conexão que caiu (ex. `cloudflared`) sem alterar
  configuração.

Após agir, o agente confirma no WhatsApp o que fez e o resultado observado,
por exemplo: *"Reiniciei o gateway da Clínica Vida, healthcheck voltou
para 200 OK"*. Nunca silencioso — toda ação de Nível 2 gera uma mensagem
de confirmação pós-fato, mesmo sem exigir aprovação prévia.

### Nível 3 — Ações Críticas / Disjuntor Humano

Qualquer ação que envolva:

- Alteração de `.env` (credenciais, URLs, toggles de comportamento).
- Migrations de banco de dados.
- Mudanças no `docker-compose.yml` (novos serviços, portas, volumes,
  redes).
- Qualquer operação potencialmente destrutiva ou difícil de reverter.

é **bloqueada por padrão**. O agente monta a proposta de correção (o que
mudaria, por quê, qual o risco) e envia no WhatsApp exigindo confirmação
explícita — por exemplo *"Responda SIM para autorizar"* — antes de
executar qualquer coisa. Esse é o mesmo padrão já validado em produção
para automações de risco: o `n8n_guard` (gate de confirmação com TTL e uso
único, ver memória do projeto — Incidente cérebro/n8n) e o método do
disjuntor descrito em `docs/METODO_DISJUNTOR_SUBAGENTES.md`. A ideia de
"disjuntor" aqui é literal: na dúvida sobre o nível de risco de uma ação,
ela sobe para Nível 3 por padrão, nunca o contrário.

## 4. Divisão de Responsabilidades: Orquestrador SRE vs. Claude Code Sandbox

Dois motores diferentes, cada um no papel que já resolve bem hoje:

- **Orquestrador LangGraph** (ver `docs/ARQUITETURA_ORQUESTRADOR.md`):
  cuida da **triagem rápida de infraestrutura e serviços** — Níveis 1 e 2
  inteiros. É leve, roda em Python puro, sem necessitar de um modelo caro
  de raciocínio prolongado, e já tem o padrão de supervisor/especialistas
  com guardas de risco em produção (`cybersec_guard.py`, `n8n_guard.py`).
  Adicionar um especialista `sre`/`infra` a esse enxame é a extensão
  natural, não uma arquitetura nova.
- **Claude Code em sandbox Docker**: acionado **apenas** quando a triagem
  do orquestrador conclui que a falha não é operacional (serviço
  travado, disco cheio) e sim um **bug real no código de uma extensão do
  cliente** — algo que exige ler/entender/editar código, não só reiniciar
  processo. Nesse caso, o Claude Code roda **confinado à pasta do código em
  questão** (o diretório da extensão/cliente específico, nunca o host
  inteiro nem o socket do Docker — mesma regra do §2.4 e do isolamento
  descrito em `docs/PADRAO_CLIENTES_DOCKER.md`), ajusta a lógica, roda os
  testes existentes, e avisa no WhatsApp pedindo validação antes do
  deploy — o deploy em si é sempre Nível 3 (§3), nunca automático.

Essa divisão espelha a mesma fronteira já documentada em
`docs/ARQUITETURA_ORQUESTRADOR.md` ("Cérebro" decide o quê fazer,
"Especialista" executa uma tarefa concreta e delimitada em sandbox
isolado) — aqui o "Especialista" de código é o próprio Claude Code, em vez
do OpenClaw.

## 5. Isolamento de Ambientes de Clientes (Multi-Tenant Seguro)

Quando o Claude Code precisa agir sobre o código de um cliente específico,
vale a mesma exigência de *blast radius* trancado já aplicada aos
deployments de cliente (`docs/PADRAO_CLIENTES_DOCKER.md`):

- **Chaves SSH e usuários dedicados** por cliente, com escopo restrito via
  `sudoers` — o usuário usado para investigar/corrigir o cliente X não tem
  permissão de tocar em nada fora do diretório/containers daquele cliente.
- **Sem acesso cruzado entre clientes diferentes**: o sandbox do Claude
  Code para o cliente X não enxerga `deployments/<outro-cliente>/`, não
  tem rede compartilhada com os containers de outro tenant (mesma rede
  bridge dedicada `cliente-<slug>-net` já usada hoje) e não tem
  credenciais de outro `.env` em memória.
- Nenhuma exceção para "é rápido, é só esse caso": a regra de isolamento
  vale mesmo sob pressão de incidente ao vivo — é justamente nesse
  cenário (decisão rápida, texto livre do WhatsApp) que o isolamento
  importa mais.

## 6. Roadmap de Implementação

- **Etapa 1 (atual)**: Homologação do Molde 1 (Core VPS) com subida real —
  `docker compose up -d` em ambiente de laboratório descartável, validando
  que a base do orquestrador sobe de forma isolada e reprodutível antes de
  acoplar qualquer lógica de SRE nela (ver
  `docs/SESSAO_2026-09-25.md`/memória "Servidor Dedicado: arquitetura
  definida").
- **Etapa 2**: Estruturação do Molde 2 (Kit Agente + n8n e Postgres
  dedicados) — a base de infraestrutura sobre a qual o especialista de SRE
  vai operar precisa existir e estar validada antes da lógica de triagem.
- **Etapa 3**: Desenvolvimento da Tool SRE/Telemetria no Orquestrador
  (Níveis 1 e 2 deste documento, como novo especialista no enxame
  supervisor/especialistas) e criação da imagem Sandbox do Claude Code
  dedicada a correções de código sob demanda (Nível 3 + §4), incluindo o
  mecanismo de resposta assíncrona via WhatsApp descrito em §2.3.

Nenhuma etapa de código foi iniciada ainda — este documento é o contrato de
arquitetura que orienta as próximas etapas, no mesmo espírito de
`docs/ARQUITETURA_ORQUESTRADOR.md` para o orquestrador original.
