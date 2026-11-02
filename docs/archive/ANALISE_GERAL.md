# ANÁLISE GERAL — Repositório `meu-agente`

Data da varredura: 2026-09-19 (UTC). Raiz: `/home/max/Documentos/Kali Linux/meu-agente`.
Método: inspeção de estrutura + execução real de testes (pytest no `.venv` do orchestrator, vitest/tsc nas extensões, `bash -n` nos scripts). Sem correção de código — apenas diagnóstico.

## 1. Sumário Executivo

Status geral: **núcleo do orquestrador saudável; provisionamento multi-tenant instável; extensões TypeScript sem harness executável isolado.**

- Orquestrador LangGraph (graph, guards, clients, schemas): íntegro e com núcleo 100% verde (94 passed, 1 skipped excluindo `test_provision_client.py`).
- Suíte completa do orchestrator: **133 testes**; observado **118 passed / 15 failed** na 1ª execução e **108 passed / 25 failed** na 2ª — a variação entre runs indica poluição de estado (diretórios residuais em `deployments/`), não apenas falhas determinísticas. Todas as falhas estão em `tests/test_provision_client.py`.
- Extensões (`extensions/`, 4 módulos): código-fonte e `*.test.ts` presentes, mas `vitest run` e `tsc --noEmit` **não passam isoladamente** — falta `extensions/tsconfig.package-boundary.base.json` (TS5083) e resolução de `openclaw/plugin-sdk/*` + `@types/node` fora do workspace openclaw.
- Scripts: sintaxe `bash -n` OK nos 3 verificados; `scripts/provision-client.sh` e `tests/test_provision_client.py` possuem modificações não commitadas (250 inserções no diff) — principal suspeito das falhas.
- Templates e docs: 2 nichos alinhados (`clinica-saude`, `suporte-ti-pme`, cada um com `AGENTS.md` + `workflow-exemplo.json`); `docs/SESSAO_2026-09-18.md` é a referência canônica atual do provisionamento.

## 2. Saúde dos Testes e Execução

### 2.1 Orquestrador Python — pytest (execução real, `.venv`)

| Escopo | Comando | Resultado observado |
|---|---|---|
| Suíte completa (run 1) | `.venv/bin/python -m pytest -q` | 15 failed, 118 passed (6.25s) |
| Suíte completa (run 2, `-p no:cacheprovider`) | idem | 25 failed, 108 passed (4.18s) |
| Núcleo sem provisionamento | `pytest tests --ignore=tests/test_provision_client.py` | **94 passed, 1 skipped** |
| Guards isolados (`n8n_guard`, `cybersec_guard` self/unmatched, e2e, `human_escalation`) | 4 arquivos | **18 passed** |
| Lint | `ruff check src` | **5 erros** (2 auto-fixáveis) |

Falhas concentradas em `orchestrator/tests/test_provision_client.py` (integração que invoca `scripts/provision-client.sh` de verdade): `test_provision_clinica_end_to_end`, `test_provision_suporte_ti_niche`, `operator_name_with_ampersand`, `channel_with_slash`, `refuses_overwrite_without_force`, famílias `rejects_dollar_and_control_chars` / `rejects_shell_breaking_chars` (`\`, backtick, `#`, `'`, `"`), `operator_to_accepts_empty_and_international`, `single_pass_substitution`, `atomic_no_leftovers_on_error`, `success_leaves_no_tmp_and_secure_env_perms`. Evidência de não-determinismo: o total é estável (133), mas o nº de falhas variou de 15 para 25 entre runs consecutivos; `git status` mostra `deployments/` untracked com resíduos (`TClienteUnsafe`, `TDebugBS`), e os testes criam/limpam `deployments/<nome>/` — resíduo de um run contamina o seguinte (ex.: teste `refuses_overwrite` e asserções de `returncode`/permissões `.env`).

### 2.2 Extensões TypeScript — vitest / typecheck (execução real)

- Arquivos `*.test.ts` existem nos 4 módulos (`ask-max`, `github-repo-report`, `response-audit`, `whatsapp-cloud` — ver §3), mas **nenhum `package.json` das extensões declara runner** (`vitest`/`jest` ausentes; sem script `test`/`typecheck` local).
- `vitest run` dentro de `extensions/whatsapp-cloud` usando o binário de `openclaw/node_modules`: **4 arquivos falham no transform, 0 testes executados** — `TSCONFIG_ERROR: Tsconfig not found`, porque cada `tsconfig.json` estende `../tsconfig.package-boundary.base.json`, arquivo **inexistente** (`ls extensions/*.json` vazio).
- `tsc --noEmit -p extensions/whatsapp-cloud/tsconfig.json`: **TS5083** (base ausente) + `TS2307` (`openclaw/plugin-sdk/*` não resolvido fora do monorepo openclaw) + `TS2591` (`process`, falta `@types/node`).
- Conclusão: testes TS **não são executáveis de forma isolada**; o harness válido provavelmente é o workspace `openclaw/` (que possui `vitest`+`tsx` em `node_modules/.bin` e scripts `test`/`lint`), não documentado para as extensões espelhadas em `extensions/`.

### 2.3 Scripts — sintaxe

`bash -n` OK em `scripts/provision-client.sh`, `scripts/deploy-orchestrator.sh`, `scripts/heartbeat-monitor.sh`. Saúde funcional do provisionamento, porém, é **reprovada** pelos testes de integração acima — sintaxe válida não implica comportamento correto.

## 3. Mapeamento dos Módulos

### 3.1 Orquestrador (`orchestrator/`) — íntegro

- `src/orchestrator/graph/`: `builder.py`, `nodes.py`, `state.py`, `event_mapper.py`, `human_escalation.py`, `n8n_guard.py` (43 linhas), `cybersec_guard.py` (101 linhas), `n8n_confirmation.py`.
- `src/orchestrator/clients/`: `n8n_client.py` (114 linhas), `openclaw_client.py` (99 linhas).
- `src/orchestrator/schemas/`: `events.py`, `routing.py`, `requests.py`, `n8n_tools.py`, `human_tools.py` (~243 linhas somadas) + `persistence/checkpointer.py`, `config.py`, `main.py` (FastAPI).
- `tests/`: 12 arquivos (guards, confirmação n8n, fluxos e2e, multiturn reset, tracing LangSmith, especialistas, provisionamento). Núcleo de guards/fluxos verde.

### 3.2 Extensões (`extensions/`) — código presente, harness quebrado isoladamente

| Módulo | `src/*.test.ts` presentes | `src/` principal |
|---|---|---|
| `ask-max` | `ask-max-tool`, `config`, `display`, `proactive-send`, `resolve-hook`, `store` | mesmos nomes + `plugin.ts` |
| `github-repo-report` | `audit-log`, `bug4-concurrency`, `bug4-payload-size.live`, `bug4-repro.live`, `config`, `github-fetch`, `policy`, `repo-registry`, `report-builder`, `schema`, `tool` | idem + `debug-timing.ts` |
| `response-audit` | `heuristic-filter`, `turn-capture` | + `audit-runner.ts`, `audit-store.ts`, `plugin.ts` |
| `whatsapp-cloud` | `inbound-parser`, `webhook-signature`, `webhook`, `webhook-verify` | + `accounts`, `channel`, `config-schema`, `gateway`, `inbound`, `orchestrator-client`, `phone`, `runtime`, `send`, `types` |

Observação: existe `openclaw/` (submódulo/monorepo volumoso, com `extensions/` próprio) ao lado de `extensions/` — relação de espelho/sync entre os dois não documentada na varredura (há `scripts/sync-extensions-backup.sh` que pode esclarecer).

### 3.3 Scripts (`scripts/`)

- `provision-client.sh` (multi-tenant: `--name/--niche/--operator-name/--operator-to/--channel/--port/--force`; validações de nome, nicho, porta 1–65535, telefone internacional; substituição literal via `python3 str.replace` pós-bug do `sed` — ver sessão 2026-09-18): **modificado, não commitado**.
- `deploy-orchestrator.sh` (rsync `orchestrator/` → Contabo `/root/meu-agente-orchestrator`, commit snapshot remoto, `docker compose build/up`, healthcheck `:8000/health`; **roda `pytest -q` antes de sincronizar** — com a suíte vermelha atual, o deploy trava/falha por desenho): sintaxe OK.
- `heartbeat-monitor.sh`, `eval-router.py`, `sync-extensions-backup.sh`: sintaxe OK (heartbeat); demais não executados nesta varredura.
- `bug4-cli-concurrency.sh`, `bug4-monitor.sh` na raiz + `logs/`: artefatos da investigação Bug4.

### 3.4 Templates e docs

- `templates/nichos/`: apenas `clinica-saude` e `suporte-ti-pme`, cada um com `AGENTS.md` (placeholders `[NOME_DA_CLINICA]`/`[NOME_DA_EMPRESA]`, `[OPERADOR_NOME]`, `[OPERADOR_NUMERO]`, `[CANAL]`) + `workflow-exemplo.json`. `diff` confirma conteúdos distintos por nicho (alinhado).
- `docs/`: ~30 arquivos; mais recente `SESSAO_2026-09-18.md` (base canônica dockerizada, post-mortem do `sed`, solução Python, cobertura de provisionamento) — coerente com o estado atual do script. `ESTADO_ATUAL.md`, `PROXIMOS_PASSOS.md`, `ARQUITETURA_ORQUESTRADOR.md` complementam; sem divergência gritante detectada nesta varredura (alinhamento fino placeholder-a-placeholder não verificado teste a teste).

## 4. Pontos de Atenção e Débitos Técnicos Encontrados

1. **Provisionamento vermelho e flaky (P0).** Todas as falhas da suíte estão em `test_provision_client.py`; variação 15→25 entre runs + resíduos em `deployments/` indicam testes order-dependentes / limpeza incompleta. Enquanto vermelho, `deploy-orchestrator.sh` (que exige `pytest -q` verde) bloqueia deploys.
2. **Mudanças não commitadas no caminho crítico.** `git status`: `M scripts/provision-client.sh`, `M orchestrator/tests/test_provision_client.py`, `?? deployments/`. Últimos commits visíveis são do fluxo "Orquestra" — o diff de 250 linhas no provisionamento/testes ainda não foi revisado nem commitado.
3. **Harness TS inexistente/inoperante isoladamente.** Falta `extensions/tsconfig.package-boundary.base.json`; sem `test`/`typecheck` nos `package.json` das extensões; `vitest`/`tsc` só fazem sentido dentro do workspace `openclaw/`. Risco: regressões em `whatsapp-cloud`/`ask-max`/`github-repo-report`/`response-audit` sem sinal vermelho visível.
4. **`ruff check src`: 5 erros.** Pequeno, mas indica lint sem gate no fluxo (deploy só roda pytest).
5. **Resíduos de investigação no repo.** `deployments/` (inclui `TCliente*`, `TDebug*` de testes), `__pycache__/`, `.pytest_cache` potencial, `logs/`, scripts `bug4-*` na raiz — poluem `git status` e os próprios testes.
6. **Duplicidade `extensions/` × `openclaw/extensions/`.** Sem documento lido nesta varredura que defina qual é canônico e como o sync ocorre (só a existência de `sync-extensions-backup.sh`).
7. **Cobertura não medida.** `pyproject` não inclui `pytest-cov`; nenhum número de cobertura — só contagem pass/fail.

## 5. Próximos Passos Recomendados

1. **Estabilizar o provisionamento:** limpar `deployments/T*` residuais, rodar a suíte em árvore limpa, corrigir `provision-client.sh` (casos `\`, backtick, `#`, `&`, `/`, `operator-to` vazio/internacional, atomicidade/tmp, perms do `.env`) até 133/133, e só então commitar o diff atual após revisão.
2. **Tornar o teste hermético:** fixture `tmp_path` ou `DEPLOYMENTS_DIR` isolado por teste + `force`/cleanup garantido (try/finally), eliminando a flakiness entre runs.
3. **Definir o harness TS:** documentar e/ou criar `extensions/package.json` workspace com `test`/`typecheck` (ou declarar oficialmente que o teste TS roda dentro de `openclaw/`), restaurando/criando o `tsconfig.package-boundary.base.json` ausente e fixando `@types/node` + `plugin-sdk` resolution.
4. **Adicionar gates mínimos:** `ruff check` no pre-deploy (ao lado do pytest), `git status --porcelain` limpo antes de `deploy-orchestrator.sh`, e `pytest-cov` com meta inicial.
5. **Higiene do repo:** gitignorar `deployments/T*`, `__pycache__/`, `.pytest_cache`; mover `bug4-*` para `scripts/` ou `docs/`; esclarecer canonicidade `extensions/` vs `openclaw/extensions/` em `docs/ARQUITETURA_*` ou README.
