# Meu Agente — Agentes de IA autônomos, com segurança desde o desenho

Plataforma de agentes de IA para PMEs brasileiras (atendimento no WhatsApp,
automação de processos e análise de segurança), construída como um **sistema
multi-agente com controles de segurança determinísticos** em volta do LLM — e em
**produção real**, não só em demo.

[![CI](https://github.com/maxwellnasci/meu-agente/actions/workflows/ci.yml/badge.svg)](https://github.com/maxwellnasci/meu-agente/actions/workflows/ci.yml)

> A tese do projeto: um agente que *age* (cria workflows, executa varreduras,
> responde clientes) precisa tratar a saída do modelo como **entrada não
> confiável**. Os controles críticos vivem em código Python/TypeScript testado,
> não em instruções de prompt.

## O que há de interessante aqui

| Tema | O que foi feito | Evidência |
|---|---|---|
| **Orquestração multi-agente** | Supervisor em **LangGraph** roteia por intenção para especialistas (programação, cibersegurança, automação n8n); estado e memória por sessão em checkpointer SQLite; streaming SSE | [`orchestrator/`](orchestrator/), [docs/ARQUITETURA_ORQUESTRADOR.md](docs/ARQUITETURA_ORQUESTRADOR.md) |
| **Segurança de agentes (OWASP LLM Top 10)** | Gate de confirmação com TTL e uso único para ações em produção; allowlist de argumentos vindos do LLM; gate de alvos protegidos; limites de entrada | [SECURITY.md](SECURITY.md) |
| **Auditoria com provas** | 17 achados registrados (severidade, evidência, status — inclusive os que seguem abertos). Os de maior severidade têm PoC offline e correção guiada por teste (red → green): path traversal controlado pelo LLM, bypass de guardrail, confirmação fraca de ações em produção, injeção de shell no CI | [docs/SEGURANCA_AUDITORIA_2026-11-02.md](docs/SEGURANCA_AUDITORIA_2026-11-02.md) |
| **Engenharia de produção** | Webhook com HMAC, anti-replay, fila por remetente; deploy via imagem publicada (GHCR); provisionamento multi-cliente; moldes de servidor dedicado sem portas expostas | [`extensions/`](extensions/), [`deployments/`](deployments/servidor-dedicado/), [`scripts/provision-client.sh`](scripts/provision-client.sh) |
| **Qualidade e supply chain** | 732 testes herméticos (Python 3.11 e 3.14), ruff, bandit, pip-audit, gitleaks (histórico completo semanal), shellcheck, actions fixadas por SHA | [`.github/workflows/ci.yml`](.github/workflows/ci.yml) |
| **Pós-incidentes documentados** | Falhas reais viraram documentos: o bug do "coma eterno", a investigação de travamento de hooks e a criação indevida de workflow no n8n | [docs/RESOLUCAO_BUG_COMA_ETERNO.md](docs/RESOLUCAO_BUG_COMA_ETERNO.md), [docs/CASE_BUG4_INVESTIGACAO_COMPLETA.md](docs/CASE_BUG4_INVESTIGACAO_COMPLETA.md), [docs/archive/P0_CONTENCAO_N8N_2026-09-06.md](docs/archive/P0_CONTENCAO_N8N_2026-09-06.md) |

## RAG: manual de procedimentos

Especialista `rag` no agente: responde perguntas sobre um manual de
procedimentos (fictício) de supermercado **citando o POP e a seção**, e diz "o
manual de procedimentos não cobre isso" em vez de inventar.

**recall@5 da busca** (gabarito fixo, 17 perguntas com fonte, 6 POPs):

| Passo | recall@5 |
|---|---|
| BM25 (baseline) | 14/17 (82%) |
| BM25 com stemming em português | 15/17 (88%) |
| **Híbrido (BM25 + vetor, RRF) com contextual retrieval**, o padrão atual | **16/17 (94%)** |
| + reranking (cross-encoder): MRR 0,60 → 0,81 | 16/17, **não adotado** (p95 de 10 s) |

> Cada passo é **1 pergunta em 17**, dentro do ruído: é tendência, não prova
> estatística. A tabela mede só a busca; as respostas estão no bloco abaixo.

**Avaliação de ponta a ponta (20/11/2026)**: as 20 perguntas do gabarito
passaram pelo grafo inteiro com LLM real, uma amostra por pergunta. Os
critérios foram fixados antes de medir.

| Métrica | Resultado |
|---|---|
| Roteamento para o `rag` | 19/20 (a q18, sobre férias, foi pelo caminho geral e respondeu CLT de memória) |
| Fatos-chave (determinística) | 16/17 |
| Correção (juiz LLM, **não calibrado**) | 16/17 (na q01, o único item da calibração cega, o humano discordou do juiz) |
| Sem afirmação grave (juiz, **não calibrado**) | 15/20; os 5 graves foram conferidos por humano depois do juiz, com 5/5 de acordo |
| Formato do Max (Sim/Não primeiro, resposta curta, oferta de detalhes) | 0/17 na linha de base. A Missão 9 testou a v2, que formatou 15,5/17 mas derrubou fatos e correção e errou o Sim/Não: **não adotada**. A próxima é a v3, "pensa primeiro, formata depois" |

Aprendizado: **citação não garante verdade.** Na q10, a resposta citou o
POP-04 §5 com uma frase que não existe nessa seção. Só um juiz de fidelidade,
que compara a resposta com os trechos, pega isso.

**Aprendizados:**
- O híbrido empatou com o BM25 e depois perdeu para ele (com stemming); só
  passou à frente com contextual retrieval.
- O reranking melhorou muito a ordem (recall@1 de 6 para 12 em 17), mas foi
  barrado pela latência, pela regra fixada antes de medir.
- Formato e conteúdo competem (Missão 9, não adotada). Exigir Sim/Não na 1ª palavra e no máximo 3 linhas levou o formato de 0 para 15,5/17. Mas derrubou fatos-chave (13,5 → 10,5) e correção (15,5 → 12,5), e respondeu "Sim" para aceitar frango a −10 °C. Hipótese: o modelo decide antes de raciocinar. Próximo passo: pensar primeiro, formatar depois.
- Comparação numérica ("faltam 3 reais: cabe em até R$ 5,00?") é limite do RAG.
  Dado numérico ou estruturado vai por SQL ou camada semântica, não por busca.

**Como foi feito:**
- critérios de decisão pré-registrados antes de cada medição, e só eles
  decidem;
- revisão adversária por outro modelo (Gemini, via Antigravity) nas etapas de
  fundação e, numa 2ª rodada, nas Missões 3–7: nenhum achado alto, 7 médios e 3
  baixos, todos corrigidos com um teste que falhava antes da correção
  ([docs/RAG.md](docs/RAG.md), *2ª revisão adversária*);
- testes com rede bloqueada, LLM e embedder falsos, sem chamada a modelo real
  no pytest.

**Como rodar** (o `rag` vem **desligado por padrão**: `ORCHESTRATOR_RAG_ENABLED=false`):

```bash
cd orchestrator
pip install -e ".[rag]"
python -m orchestrator.rag.ingest      # índice local (híbrido + contexto)
python -m orchestrator.rag.evaluate    # recall@5 no gabarito
python -m orchestrator.rag.smoke "o preço na prateleira ta mais barato do que passou no caixa, cobro qual?"             # só mostra o plano
python -m orchestrator.rag.smoke --executar "o preço na prateleira ta mais barato do que passou no caixa, cobro qual?"  # LLM real (OpenRouter, centavos)
```

O smoke liga o `rag` só no próprio processo. Detalhes, números por pergunta e
decisões: [docs/RAG.md](docs/RAG.md).

## Arquitetura

```
 WhatsApp ──► Gateway OpenClaw ──► Orquestrador (FastAPI + LangGraph) ──► Especialistas
              plugin whatsapp-cloud   supervisor → roteia → sintetiza        • programação / cibersegurança (sandbox Docker)
              HMAC · anti-replay      /v1/turn · /tasks/stream (SSE)         • automação n8n (API REST + webhooks)
              allowlist de remetentes token Bearer, fail-closed              • transbordo humano (ask-max)
```

O LLM decide *o quê* fazer; **código determinístico decide se pode**. Detalhes das
fronteiras de confiança e do mapeamento OWASP em [SECURITY.md](SECURITY.md).

## Stack

**Python 3.11+** · FastAPI · LangGraph · LangChain · Pydantic · httpx · tenacity ·
SQLite (checkpointer) · LangSmith (tracing opcional) — **TypeScript** (plugins) ·
**Docker/Compose** · GitHub Actions · GHCR — **OpenClaw** (gateway de agentes),
**n8n**, **WhatsApp Cloud API**, LLMs via OpenRouter (DeepSeek por padrão).

## Estrutura

```
orchestrator/            cérebro LangGraph (FastAPI) + 732 testes
extensions/              plugins TypeScript do gateway
  whatsapp-cloud/          canal WhatsApp oficial (webhook assinado)
  orchestrator-bridge/     ferramenta ask_orchestrator
  ask-max/                 escalonamento humano
  response-audit/          auditoria de respostas (ação declarada vs. executada)
  github-repo-report/      relatórios de repositório
deployments/servidor-dedicado/   moldes de servidor por cliente (zero portas publicadas)
scripts/                 provisionamento multi-cliente, deploy, heartbeat
templates/nichos/        AGENTS.md por nicho (clínica, suporte de TI)
docs/                    arquitetura, sessões, post-mortems  (docs/archive: relatórios históricos)
SECURITY.md              modelo de ameaças e mapa OWASP LLM Top 10
```

## Rodando os testes

```bash
cd orchestrator
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,security]"
ruff check . && python -m pytest -q      # hermético: não precisa de .env nem de rede
bandit -r src -ll -q && pip-audit --skip-editable
```

Os testes não falam com rede. O único teste de integração contra um n8n real exige
opt-in explícito (`RUN_LIVE_N8N_TESTS=1`) e nunca roda no CI.

## Status

Em produção (conforme [docs/ESTADO_ATUAL.md](docs/ESTADO_ATUAL.md), posição de
02/10/2026): canal WhatsApp Cloud, orquestrador com autenticação por token
(fail-closed) e especialistas de automação e cibersegurança. Em evolução: add-on
de automação n8n para o servidor dedicado, allowlist de alvos para o especialista
de segurança e correção do rate limit do webhook (ver auditoria).
Em 20/11/2026, o especialista `rag` (manual de procedimentos) foi integrado ao grafo, fica
desligado por padrão e foi avaliado de ponta a ponta (ver
[RAG: manual de procedimentos](#rag-manual-de-procedimentos) e [docs/RAG.md](docs/RAG.md)).
Estado detalhado: [docs/ESTADO_ATUAL.md](docs/ESTADO_ATUAL.md) · roadmap:
[docs/PROXIMOS_PASSOS.md](docs/PROXIMOS_PASSOS.md).

## Aprendizados-chave

- **Sem prova, sem aprovação.** Toda correção nasce de um teste que falhava, e todo
  achado de segurança tem uma PoC reproduzível.
- **Guardrail em prompt não é guardrail.** O que importa é o que roda *antes* da ação.
- **Heurística de texto tem limite.** Cada gate documenta o que não cobre e aponta
  para o controle de rede que realmente fecha a porta.
- **Alucinação elegante é mais perigosa que erro óbvio** — por isso a auditoria de
  respostas e o "não sei" como resposta profissional.
- **Documentar o incidente vale mais que escondê-lo.**
- **Decidir o critério antes de medir.** A regra pré-registrada barrou duas mudanças
  que pareciam melhorias: o reranking (10 s por pergunta) e o formato v2 (respondeu
  "Sim" para frango a −10 °C).

## Sobre

Construído por **Max** — consultor de automação e IA em Curitiba (BR), com foco em
agentes autônomos seguros para pequenas e médias empresas.
