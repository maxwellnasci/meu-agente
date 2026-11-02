# Segurança

Este projeto é um agente de IA que **age no mundo** (responde clientes no WhatsApp,
cria workflows de automação, executa varreduras de segurança em sandbox). Isso o
torna um alvo de *prompt injection* e de *excessive agency*, não só de bugs
clássicos. Este documento descreve o modelo de ameaças, os controles que existem
**no código** (com o arquivo onde vivem) e o que é risco aceito.

## Reportar uma vulnerabilidade

Use **GitHub → Security → Report a vulnerability** (relato privado). Não abra
issue pública com detalhes de exploração. Auditoria interna mais recente:
[docs/SEGURANCA_AUDITORIA_2026-11-02.md](docs/SEGURANCA_AUDITORIA_2026-11-02.md).

## Arquitetura e fronteiras de confiança

```
 Usuário (WhatsApp)
      │  (1) HTTPS, assinado pela Meta
      ▼
 ┌──────────────────────────────┐   fronteira A: internet → webhook
 │ Gateway OpenClaw             │   • HMAC-SHA256 do corpo cru (X-Hub-Signature-256)
 │  plugin whatsapp-cloud       │   • limite de corpo + timeout, anti-replay, allowFrom
 └──────────────┬───────────────┘
                │ (2) Bearer token (rede interna)          fronteira B: serviço → serviço
                ▼
 ┌──────────────────────────────┐
 │ Orquestrador (FastAPI)       │   • fail-closed sem token, compare_digest
 │  /v1/turn  /tasks/stream     │   • limites de tamanho de entrada
 │  LangGraph: supervisor ──────┼──► roteia por intenção; checkpoints SQLite por sessão
 └───────┬──────────┬───────────┘
         │          │                                       fronteira C: LLM → ferramentas
         ▼          ▼
  Especialista   Especialista n8n          ← o LLM é NÃO CONFIÁVEL a partir daqui:
  cybersec/code  (API REST + webhooks)       toda saída dele passa por validação em
  (OpenClaw,     • allowlist de ids/paths    Python puro antes de agir
  sandbox)       • gate de confirmação
  • gate de alvos
```

**Premissa central:** o texto do usuário e a saída do LLM são entrada não
confiável. Nenhum controle crítico depende de o modelo "obedecer" ao prompt — os
gates abaixo são código determinístico que roda *antes* da ação.

## Atores e ativos

| Ativo | Por que importa |
|---|---|
| Chave de API do n8n | dá controle total sobre automações de produção |
| Token serviço-a-serviço (`ORCHESTRATOR_API_TOKEN`) | quem o tem fala com o cérebro |
| Infraestrutura de produção própria | nunca pode ser alvo do especialista de segurança |
| Conversas dos clientes (SQLite) | dados pessoais |
| Orçamento de LLM | custo e disponibilidade |

Atacantes considerados: (1) remetente malicioso no WhatsApp, (2) conteúdo
externo que o agente lê (indireto), (3) host na internet que alcança o webhook,
(4) dependência/CI comprometidos.

## Mapa OWASP Top 10 for LLM Applications (2025)

| Risco | Controle implementado | Onde |
|---|---|---|
| **LLM01** Prompt injection | Validação de saída do LLM por **allowlist** antes de usar como argumento de rede (`workflow_id`, `path`, método); gate de alvos protegidos; confirmação humana de ações de escrita | `clients/n8n_client.py`, `graph/cybersec_guard.py`, `graph/n8n_confirmation.py` |
| **LLM02** Divulgação de informação sensível | Erros internos não vão ao cliente (SSE/HTTP genéricos, detalhe só em log); segredos só por env/SecretRef, nunca versionados; varredura de segredos no CI | `main.py`, `.github/workflows/ci.yml` |
| **LLM03** Cadeia de suprimentos | Pisos de versão contra CVEs; `pip-audit` + gitleaks + actions por SHA no CI; imagem publicada só por tag/manual | `pyproject.toml`, `.github/workflows/` |
| **LLM04** Envenenamento de dados/modelo | Sem fine-tuning nem ingestão automática de dados de usuários; "treinamento" por `AGENTS.md` versionado e revisado | `templates/nichos/` |
| **LLM05** Tratamento inadequado de saída | Saída do LLM nunca vira comando/URL sem validação; sem `eval`/shell a partir de texto do modelo no orquestrador | `clients/`, `graph/nodes.py` |
| **LLM06** Agência excessiva | Ferramentas mínimas por especialista; ações destrutivas/de produção só com confirmação explícita, **vinculada** à ação e ao id, com TTL e uso único; "criar" nunca ativa no mesmo turno; especialista de segurança em sandbox sem rede de produção | `graph/n8n_confirmation.py`, `graph/n8n_guard.py`, sandbox do OpenClaw |
| **LLM07** Vazamento de prompt de sistema | Nenhum segredo no prompt; regras críticas aplicadas em código, não só em texto | `graph/nodes.py` |
| **LLM08** Fraquezas de vetores/embeddings | Não aplicável hoje (sem RAG sobre dados de usuários) | — |
| **LLM09** Desinformação | Plugin de auditoria de respostas detecta "ação declarada como feita" sem ter sido feita; instrução de "não sei" por nicho | `extensions/response-audit/` |
| **LLM10** Consumo ilimitado | Limites de tamanho de entrada (422), limite de iterações do supervisor, timeouts por turno, rate limit e anti-replay no webhook | `schemas/requests.py`, `config.py`, `extensions/whatsapp-cloud/src/webhook.ts` |

## Controles por camada

**Borda (webhook).** Assinatura HMAC-SHA256 do corpo cru com comparação em tempo
constante; `verify_token` em tempo constante; corpo ≤ 256 KB com timeout;
anti-replay por `message_id`; ACK imediato (a Meta não reenvia por lentidão do
agente); `dmPolicy` padrão `allowlist` (só números autorizados).

**Serviço-a-serviço.** `Authorization: Bearer` ou `X-Orchestrator-Token`;
**fail-closed** (sem token configurado → 401 em tudo); modo sem autenticação só
com `ORCHESTRATOR_ALLOW_INSECURE_DEV_AUTH=true` (aviso no log); `/health` público
e sem dados.

**Agência.** Dois gates em Python puro, independentes do prompt:
1. *Gate de confirmação do n8n* — `create/activate/deactivate/delete` viram uma
   **proposta pendente** (token aleatório, TTL, uso único, ligada à ferramenta e
   ao `workflow_id`). Só executa com uma resposta curta e inequívoca em turno
   posterior ("sim"); ruído como "ok mas espera" **não** confirma.
2. *Gate de alvos do cibersegurança* — recusa instruções que mirem infraestrutura
   própria (nomes de serviço e IPs/domínios configuráveis), robusto a acento,
   caixa, leetspeak e separadores, e a negações que não governam o alvo.

**Execução.** O especialista de segurança roda em sandbox Docker efêmero (usuário
sem privilégio, sem acesso ao filesystem do host, sem rede externa, workspace
somente leitura — configuração em [docs/ARQUITETURA_SEGURANCA.md](docs/ARQUITETURA_SEGURANCA.md),
validada em sessões anteriores e **não** re-testada na auditoria de 2026-11-02).
Os moldes de servidor dedicado não publicam portas no host, não montam
`docker.sock` e não usam `privileged` (verificado nesta auditoria).

**Pipeline.** CI com permissão mínima, ruff + pytest hermético + bandit +
pip-audit + gitleaks (histórico completo) + shellcheck; publicação de imagem só
por tag, com entrada validada.

## Riscos aceitos e limites (honestidade técnica)

- **O gate de alvos é uma denylist heurística** sobre texto livre. Ele fecha
  evasões baratas, mas não é uma fronteira de segurança por si só. A fronteira
  real é o isolamento de rede do sandbox; o próximo passo é uma **allowlist** de
  alvos autorizados.
- **Disparo de webhook n8n em produção não pede confirmação** (decisão de
  produto em aberto).
- **Rate limit do webhook** é aplicado antes da verificação de assinatura e por IP
  de origem (que atrás de proxy é o do proxy) — um flood pode degradar o canal.
  Correção planejada em [docs/SEGURANCA_AUDITORIA_2026-11-02.md](docs/SEGURANCA_AUDITORIA_2026-11-02.md) (S-10).
- **Token único** entre serviços: sem vínculo por sessão; o `allowFrom` do
  gateway é quem restringe interlocutores.
- Webhook responde `200` em `phone_number_id` divergente (evita retry da Meta;
  só ocorre após assinatura válida).

## Checklist de deploy seguro

- [ ] `ORCHESTRATOR_API_TOKEN` definido e **idêntico** no gateway e no orquestrador
- [ ] `ORCHESTRATOR_PROTECTED_TARGETS` com IPs e domínios de produção
- [ ] Nenhuma porta publicada fora de `127.0.0.1` (ou rede interna do compose)
- [ ] `.env` com permissão `600`, fora do git; segredos rotacionados se já passaram por chat/log
- [ ] `dmPolicy: allowlist` com os números autorizados
- [ ] Container recriado com `docker compose up -d` após mudar `.env` (`restart` não relê)
- [ ] CI verde na revisão que será implantada
