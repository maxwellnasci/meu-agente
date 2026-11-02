# Auditoria de segurança — 2026-11-02

Escopo: código próprio do monorepo (`orchestrator/`, `extensions/`, `scripts/`,
`deployments/`, `.github/`) e o histórico git completo. **Fora do escopo:** o
código-fonte do OpenClaw (`openclaw/`, terceiros) e qualquer verificação ao
vivo no servidor de produção (nenhum acesso foi feito; ver "Pendências").

Método: revisão manual dirigida pelo OWASP Top 10 for LLM Applications (2025),
análise estática (bandit, ruff, shellcheck), auditoria de dependências
(pip-audit), varredura de segredos em todo o histórico e **provas de conceito
offline** (nenhuma rede real) para cada achado de maior severidade. Cada correção
nasceu de um teste que falhava antes (red → green).

## Resumo

| Resultado | Antes | Depois |
|---|---|---|
| Testes | 157 (passavam só com `.env` local) | **333** hermético, 1 live opt-in |
| Lint (ruff) | 10 avisos | 0 |
| SAST (bandit, severidade ≥ média) | 1 | 0 |
| CVEs em dependências (pip-audit) | 7 em 3 pacotes | 0 |
| Segredos no histórico git (202 mil linhas adicionadas) | 0 | 0 |
| Entradas ofensivas que passavam no `cybersec_guard` | 13 de 17 | 0 de 17 |

## Achados

Severidade: **Alta** = permite ação/acesso indevido a partir de entrada não
confiável; **Média** = enfraquece um controle ou expõe informação; **Baixa** =
higiene/defesa em profundidade.

| ID | Sev. | Onde | Achado | Status |
|---|---|---|---|---|
| S-01 | **Alta** | `clients/n8n_client.py` | **Path traversal controlado pelo LLM.** `workflow_id` e `path` de webhook entravam na URL sem validação; o httpx normaliza `..` e mantém o header `X-N8N-API-KEY`. PoC: `get_workflow("../executions/1")` → `GET /api/v1/executions/1` **com a chave**; `x/../../credentials` → `/api/v1/credentials`. Prompt injection (LLM01) conseguia apontar a chave de API do n8n para qualquer endpoint. | **Corrigido** — allowlist (`[A-Za-z0-9_-]{1,64}`; segmentos de webhook sem `..`; métodos GET/POST/PUT/PATCH/DELETE), recusa antes de qualquer requisição **e antes de propor a confirmação** ao usuário. 99 testes. |
| S-02 | **Alta** | `graph/cybersec_guard.py` | **Bypass do gate de produção.** Qualquer `"nao "` na frase, antes *ou depois* da keyword, liberava: "escaneie o Contabo e não pare" passava. Também não cobria IP/domínio, nem variações de acento, leetspeak, separadores ou caracteres invisíveis. 13 de 17 entradas ofensivas passavam. | **Corrigido** — negação só vale se *precede* a keyword e *governa* o verbo (infinitivo/particípio; imperativo só imediatamente após a negação); `;` `:` e adversativas encerram o escopo; alvos protegidos configuráveis (`ORCHESTRATOR_PROTECTED_TARGETS`) bloqueiam sempre. A exceção que evita o loop do supervisor foi **preservada** (os 5 testes existentes de eco/loop do supervisor seguem verdes). |
| S-03 | Média | `graph/n8n_confirmation.py` | **Confirmação fraca de ação em produção.** Até 3 tokens, bastava *um* token afirmativo e nenhum negativo: "ok mas espera", "talvez ok", "pode apagar outro" confirmavam create/activate/deactivate/delete. | **Corrigido** — todos os tokens precisam ser afirmação/cortesia; verbo de ação só vale para a ação **pendente** ("pode ativar sim" confirma ativar, "pode apagar" não confirma criar). |
| S-04 | Média | `.github/workflows/docker-publish-orchestrator.yml` | **Injeção de shell** via `github.event.inputs.tag` interpolado dentro de `run:` num job com `packages: write`. Actions por tag mutável. | **Corrigido** — entrada via `env` + validação por regex; actions fixadas por commit SHA; `persist-credentials: false`. |
| S-05 | Média | `tests/` | **Suíte não hermética e teste live em produção.** 5 testes dependiam do `orchestrator/.env`; um teste de integração criava/apagava workflow no n8n **real** sempre que o `.env` tinha credenciais. Um CI limpo falharia (inclusive o job que publica a imagem). | **Corrigido** — `tests/conftest.py` fixa valores falsos; teste live exige `RUN_LIVE_N8N_TESTS=1`. |
| S-06 | Média | repo público | **Reconhecimento/PII no repositório público.** O IP do servidor de produção aparece em 6 arquivos versionados (docs e relatórios), um segundo IP (provavelmente do operador) em 2 docs de sessão, e um telefone real em docs e em testes. Não são segredos de autenticação, mas são PII e informação de reconhecimento. Corrigir o HEAD **não remove** do histórico. | **Aberto — depende de decisão** (ver "Pendências"). |
| S-07 | Baixa | `main.py` | `/tasks/stream` devolvia `str(exc)` ao cliente (caminhos, URLs internas, trechos de upstream). | **Corrigido** — mensagem genérica; detalhe só no log do servidor. |
| S-08 | Baixa | `schemas/requests.py` | Sem limite de tamanho em `text`/`message`/ids (OWASP LLM10, consumo ilimitado). | **Corrigido** — `text`/`message` ≤ 8000, ids 1–256, `from` ≤ 64 → 422 antes do grafo. |
| S-09 | Baixa | `pyproject.toml` | 7 CVEs em dependências transitivas (certifi, urllib3, langgraph-sdk). | **Corrigido** — pisos de versão; `pip-audit` limpo. Sem lockfile (ver S-12). |
| S-10 | Média (disp.) | `extensions/whatsapp-cloud/src/webhook.ts` | O rate limit roda **antes** da verificação de assinatura e usa `remoteAddress`. Atrás de proxy/túnel todos caem no mesmo balde: um flood não autenticado pode esgotar a cota e devolver 429 à Meta (negação de serviço do canal). | **Aberto** — não alterado: depende do SDK do OpenClaw (fora do repo) e não pôde ser testado aqui. Correção recomendada: verificar a assinatura primeiro (HMAC é barato) e limitar por conta/IP real (`CF-Connecting-IP`/`X-Forwarded-For` confiável). |
| S-11 | Baixa | `orchestrator/Dockerfile` | Container roda como root; imagem base sem digest; sem `HEALTHCHECK`. | **Aberto, mitigado** nos moldes de servidor dedicado (`user: 1000:1000`, zero portas publicadas, sem `docker.sock`). Mudar o default da imagem quebraria ambientes existentes cujo `data/` pertence ao root. |
| S-12 | Baixa | `extensions/*` | Nenhuma extensão tem lockfile (`package-lock.json`): builds não reprodutíveis, `npm audit` inaplicável. | **Aberto** — gerar lockfiles e incluir `npm audit` no CI. |
| S-13 | Info (design) | `schemas/n8n_tools.py` | `N8nTriggerWebhook` em modo produção (`test=false`) dispara qualquer workflow ativo **sem** passar pelo gate de confirmação (excessive agency, LLM06). | **Aberto** — decisão de produto: exigir confirmação para disparos em produção. |
| S-14 | Info (design) | `graph/cybersec_guard.py` | O gate é uma *denylist* heurística sobre texto livre. Fecha evasões baratas, mas não substitui controle de rede. | **Aceito, documentado.** Recomendado: *allowlist* de alvos autorizados + política de egress no sandbox. |
| S-15 | Info | `graph/n8n_confirmation.py` | O emoji 👍 listado como afirmação nunca casa (a normalização remove não-alfanuméricos) → cai em `unclear`. | Lado seguro; sem ação. |
| S-16 | Info | `webhook.ts` | Responde 200 em `phone_number_id` divergente (evita retry da Meta; só depois da assinatura válida). | **Aceito**, já documentado. |
| S-17 | Info | `/v1/turn` | Qualquer portador do token pode usar qualquer `session_key` (token único serviço-a-serviço, sem vínculo por sessão). | **Aceito** — autenticação é entre serviços; o `allowFrom` do gateway restringe quem fala. |

### Incidente de processo durante a auditoria

A primeira execução de `pytest` no checkout principal (antes de eu ter lido a
suíte) rodou o teste live do S-05 contra o n8n de **produção**: o checkout tinha
`.env` com credenciais e o teste não pedia opt-in. O teste cria e apaga um
workflow próprio e se limpa sozinho, mas **vale conferir a lista de workflows**
do n8n. A correção do S-05 impede que isso se repita.

## Pontos fortes (verificados)

- **Autenticação fail-closed** no orquestrador: sem token → 401 em tudo; modo
  inseguro só com opt-in explícito; comparação em tempo constante
  (`secrets.compare_digest`); `/health` é o único endpoint público.
- **Webhook do WhatsApp**: HMAC SHA-256 sobre o corpo cru com comparação em tempo
  constante e checagem de tamanho; `verify_token` em tempo constante; limite de
  corpo (256 KB) com timeout; cache anti-replay; ACK antes de processar;
  serialização por remetente; `dmPolicy` padrão `allowlist`.
- **Gate de confirmação do n8n**: ação que muda produção exige "sim" em turno
  posterior, vinculada à ferramenta e ao `workflow_id` exatos, com expiração
  (TTL) e uso único; "criar" nunca ativa no mesmo turno.
- **Provisionador multi-tenant** (`scripts/provision-client.sh`): `set -euo
  pipefail`, allowlist em todos os campos, rejeição de metacaracteres e de
  caracteres de controle, `.env` em `600`, nunca faz `source` de `.env`.
- **Moldes de servidor dedicado**: zero portas publicadas no host, sem
  `docker.sock`, sem `privileged`, rede interna dedicada.
- **Higiene de segredos**: `.env`, vault e sessões fora do git; varredura do
  histórico completo sem nenhuma credencial (o vazamento de setembro foi
  remediado de fato).

## Pendências que dependem de decisão ou de acesso à produção

1. **S-06 (repo público).** Opções: (a) tornar o repositório privado; (b) manter
   público e limpar o histórico (`git filter-repo --replace-text` + *force push*
   — reescreve SHAs, exige que todos os clones sejam refeitos); (c) aceitar o
   risco. Recomendação: (b) antes de usar o repositório como portfólio, ou (a)
   até lá. Não executado: é irreversível e afeta o remoto.
2. **Aplicar em produção.** As correções só valem depois de rebuild + deploy do
   orquestrador. No `.env` do servidor, definir `ORCHESTRATOR_PROTECTED_TARGETS`
   incluindo o **IP** de produção e recriar o container com `docker compose up -d`
   (`restart` não relê o `.env`).
3. **Conferir o n8n de produção** por workflows residuais (incidente acima).
4. Itens abertos S-10, S-11, S-12, S-13.

## Como reproduzir

```bash
cd orchestrator
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,security]"
ruff check . && python -m pytest -q           # 333 passed, 1 skipped
bandit -r src -ll -q                           # sem achados >= média
pip-audit --skip-editable                      # sem CVEs nas dependências
```

O CI (`.github/workflows/ci.yml`) roda os mesmos passos, mais *gitleaks* no
histórico completo e *shellcheck* nos scripts de deploy.
