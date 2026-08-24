# Arquitetura do Orquestrador (Portfólio)

## Objetivo

Construir um orquestrador de agentes de IA em Python, com padrões de produção
reais (não um script de demo), para servir como peça central de portfólio.
A ideia central: um **grafo de decisão (LangGraph)** atua como "Cérebro" —
recebe a tarefa do usuário, decide o que fazer, mantém estado e memória — e
delega trabalho pesado de programação para o **OpenClaw** (já rodando em
Docker/Node.js neste mesmo projeto), tratado como um "Especialista"
acessível via API HTTP, exatamente como um humano chamaria um serviço
externo especializado.

Este documento é o contrato de arquitetura antes de qualquer lógica ser
implementada. O código correspondente vive em `orchestrator/`.

## Por que separar "Cérebro" e "Especialista"

O OpenClaw já resolve, e resolve bem, a parte de "executar comandos, editar
arquivos, rodar sandbox Docker isolado" — é o motor de execução. Ele não
resolve (e não é o papel dele) orquestração multi-etapas com estado
persistente, contratos de entrada/saída tipados, streaming granular de
eventos de raciocínio para uma UI, ou observabilidade de decisão de alto
nível. Duplicar isso dentro do OpenClaw seria reinventar a roda dentro de
um sistema já validado em produção (ver `docs/ARQUITETURA_SEGURANCA.md`).

Por isso a divisão de responsabilidade é:

- **LangGraph (Cérebro)**: decide *o quê* fazer, mantém o estado da
  conversa/tarefa entre etapas, decide *quando* chamar o especialista,
  interpreta o resultado, decide o próximo passo ou encerra.
- **OpenClaw (Especialista em Programação)**: recebe uma instrução
  concreta e delimitada, executa em sandbox isolado (Docker, sem rede,
  sem acesso a root, workspace read-only conforme já documentado), devolve
  um resultado. Não sabe nada sobre o restante do fluxo de decisão.

Essa fronteira é a mesma lição já aplicada no projeto `run_local_task` (ver
memória do projeto): tratar um sistema de agentes existente como uma
**tool/serviço via API**, não tentar fundir os dois loops de execução.

## Os 4 Pilares

### 1. Memória / Checkpointing

Cada tarefa do orquestrador é uma execução de grafo (`StateGraph`) com um
`thread_id` próprio. O estado do grafo (mensagens, resultados intermediários,
decisões tomadas) é persistido a cada transição via um **Checkpointer** do
LangGraph (`orchestrator/src/orchestrator/persistence/checkpointer.py`).

- Fase de esqueleto: `SqliteSaver` (arquivo local, zero infraestrutura
  extra, suficiente para portfólio/demo).
- Caminho de evolução natural: `PostgresSaver`, sem mudar a interface do
  grafo — só troca o checkpointer injetado.
- Isso é o que permite: retomar uma tarefa interrompida, dar "voltar 2
  passos" numa conversa, e inspecionar o histórico de decisão de qualquer
  execução passada por `thread_id`.

### 2. Streaming

O usuário (ou a UI de portfólio) não espera a resposta final em bloco — ele
vê o raciocínio acontecendo: qual nó do grafo está ativo, quando o
Especialista (OpenClaw) foi chamado, tokens da resposta final chegando aos
poucos.

- Endpoint FastAPI expõe **Server-Sent Events (SSE)** (`main.py`), consumindo
  o `astream_events`/`astream` do LangGraph.
- Contrato de cada evento emitido é tipado em
  `schemas/events.py` (ex.: `NodeStartedEvent`, `SpecialistCalledEvent`,
  `TokenEvent`, `TaskCompletedEvent`) — o cliente da API sabe exatamente
  quais formatos esperar, nunca texto solto.

### 3. Contratos Rígidos (Pydantic)

Nenhuma fronteira do sistema aceita `dict` solto ou texto livre sem
validação:

- **Entrada da API** (`schemas/requests.py`): o que o usuário manda para
  iniciar/continuar uma tarefa.
- **Estado do grafo** (`graph/state.py`): o "TypedDict"/`BaseModel` que
  trafega entre nós do LangGraph — cada nó só pode ler/escrever campos
  declarados.
- **Chamada ao Especialista** (`clients/openclaw_client.py`): request e
  response da API do OpenClaw são modelos Pydantic próprios, isolando o
  resto do sistema do formato bruto da API externa.
- **Eventos de streaming** (`schemas/events.py`): como descrito acima.

Isso é o que torna o sistema auditável e testável: qualquer violação de
contrato falha cedo (na validação), não silenciosamente três camadas depois.

### 4. Observabilidade (LangSmith)

Cada execução de grafo é instrumentada via LangSmith (tracing nativo do
LangGraph/LangChain) — permite inspecionar, por execução real, cada nó
visitado, cada chamada ao Especialista (latência, payload, resposta), e
onde o tempo foi gasto. Configurado via variáveis de ambiente em
`config.py` (`LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`,
`LANGCHAIN_PROJECT`), sem acoplar código de tracing dentro dos nós — é
transversal, não invasivo.

## Integração LangGraph → OpenClaw

O OpenClaw já expõe um gateway HTTP/WS (ver `docs/ARQUITETURA_SEGURANCA.md`,
portas `18789` API/UI, `18790` sandbox). O orquestrador não sobe um novo
motor de execução de código — ele fala com esse gateway já existente como
um cliente HTTP comum:

```
Usuário → FastAPI (SSE) → LangGraph (StateGraph, checkpointed)
                                │
                                ├─ nó de decisão / raciocínio
                                │
                                └─ nó "specialist_call"
                                       │
                                       ▼
                            OpenClawClient (httpx)
                                       │
                                       ▼
                     OpenClaw Gateway (Docker, porta 18789)
                     — sandbox isolado, sem rede, workspace ro —
                                       │
                                       ▼
                            resultado validado (Pydantic)
                                       │
                                       ▼
                         volta pro grafo → próxima decisão
```

Do ponto de vista do grafo, o OpenClaw é só mais um nó que faz uma chamada
de I/O (`clients/openclaw_client.py`) e devolve um resultado tipado — o
grafo não sabe (nem precisa saber) que por trás existe um container Docker,
sandbox e todas as 8 camadas defensivas já documentadas. Essa opacidade é
intencional: é a mesma fronteira limpa recomendada na análise de inversão
de arquitetura (ver memória do projeto) — nenhum dos dois sistemas tenta
hospedar o loop de execução do outro.

## Estrutura de pastas

```
orchestrator/
├── pyproject.toml
└── src/
    └── orchestrator/
        ├── __init__.py
        ├── main.py                  # FastAPI app + endpoint de streaming (SSE)
        ├── config.py                # Settings (Pydantic), env vars
        ├── graph/
        │   ├── __init__.py
        │   ├── state.py             # Contrato do estado do grafo
        │   ├── nodes.py             # Nós do grafo (stubs)
        │   └── builder.py           # Monta o StateGraph
        ├── schemas/
        │   ├── __init__.py
        │   ├── requests.py          # Contratos da API (entrada/saída)
        │   └── events.py            # Contratos dos eventos de streaming
        ├── clients/
        │   ├── __init__.py
        │   └── openclaw_client.py   # Client HTTP pro gateway do OpenClaw
        └── persistence/
            ├── __init__.py
            └── checkpointer.py      # Checkpointer do LangGraph (SqliteSaver)
```

## Estado desta fase

**Atualizado em 2026-08-24** — este documento descreve o desenho original
(fase de esqueleto). O sistema evoluiu além dele: o padrão real
implementado é **Supervisor/Enxame de Especialistas** (não um único nó
"specialist_call" linear) — o `supervisor` decide via tool-calling quais
especialistas acionar entre `openclaw` (Programação), `cybersec`
(Ciberseguranca) e `n8n` (Automação), podendo despachar mais de um por
rodada. Cada especialista roda em produção de verdade, incluindo defesa em
profundidade em Python puro para os dois que têm efeito real sobre
infraestrutura (`graph/cybersec_guard.py`, `graph/n8n_guard.py`) — ver
detalhes e histórico em [ESTADO_ATUAL.md](ESTADO_ATUAL.md) e
[SESSAO_2026-08-22_orchestrator-deploy-contabo.md](SESSAO_2026-08-22_orchestrator-deploy-contabo.md).
Rodando em produção no Contabo desde 2026-08-22, deploy via
`scripts/deploy-orchestrator.sh`.
