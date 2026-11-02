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
| **Auditoria com provas** | 17 achados, cada um com PoC offline e correção guiada por teste (red → green): path traversal controlado pelo LLM, bypass de guardrail, confirmação fraca, injeção em CI | [docs/SEGURANCA_AUDITORIA_2026-11-02.md](docs/SEGURANCA_AUDITORIA_2026-11-02.md) |
| **Engenharia de produção** | Webhook com HMAC, anti-replay, fila por remetente; deploy via imagem publicada (GHCR); provisionamento multi-cliente; moldes de servidor dedicado sem portas expostas | [`extensions/`](extensions/), [`deployments/`](deployments/servidor-dedicado/), [`scripts/provision-client.sh`](scripts/provision-client.sh) |
| **Qualidade e supply chain** | 333 testes herméticos, ruff, bandit, pip-audit, gitleaks no histórico completo, shellcheck, actions fixadas por SHA | [`.github/workflows/ci.yml`](.github/workflows/ci.yml) |
| **Pós-incidentes documentados** | Cada falha real virou documento (deadlock de fila, loop do supervisor, criação indevida de workflow, vazamento de credencial) | [docs/](docs/), [docs/archive/](docs/archive/) |

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
orchestrator/            cérebro LangGraph (FastAPI) + 333 testes
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

## Sobre

Construído por **Max** — consultor de automação e IA em Curitiba (BR), com foco em
agentes autônomos seguros para pequenas e médias empresas.
