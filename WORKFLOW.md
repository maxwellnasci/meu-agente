# WORKFLOW — estado do projeto e fluxo de publicação

Atualizado em **2026-11-02** (após o deploy na Contabo).

## Estado atual

| Item | Situação |
|---|---|
| GitHub (`origin/master`) | histórico **reescrito e limpo** (IP de produção, 2º IP e telefone do operador removidos) + auditoria de segurança integrada; último commit publicado: `cceadd2` |
| CI | **100% verde** em `cceadd2`: orchestrator (ruff, pytest, bandit, pip-audit), gitleaks e shellcheck |
| Testes | **359 passam, 1 pulado** (o teste live do n8n exige `RUN_LIVE_N8N_TESTS=1`) |
| Produção (Contabo) | **deploy feito em 2026-11-02**: orquestrador com as correções da auditoria; verificado ao vivo (ver abaixo) |
| Commits locais ainda NÃO publicados | o fix do script de deploy e esta atualização do `WORKFLOW.md` (ver `git log origin/master..master`) |

Relatório da auditoria: [docs/SEGURANCA_AUDITORIA_2026-11-02.md](docs/SEGURANCA_AUDITORIA_2026-11-02.md)
· modelo de ameaças: [SECURITY.md](SECURITY.md).

## Deploy na Contabo (2026-11-02)

Feito com o fluxo de `scripts/deploy-orchestrator.sh`, **com proteções que o script original não tinha**
(ele agora as inclui). O dry-run do `rsync` antes do deploy mostrou dois riscos reais:

- o `docker-compose.yml` **do servidor** tem a rede extra `agencia_ia_n8n-internal` (é por ela que o
  orquestrador alcança o n8n) e **não está no repo** — sobrescrevê-lo quebraria o especialista n8n;
- o `rsync --delete` apagaria os backups soltos `.env.bak-*` / `docker-compose.yml.bak-*`, e o `git add -A`
  do snapshot comitaria o `.env.bak-*` (chaves de API) no histórico git do servidor.

Sequência executada: backup do `.env` e do compose (`/root/backups/pre-deploy-orchestrator-20261102`, pasta `700`)
→ tag da imagem anterior `meu-agente-orchestrator:rollback-pre-20261102` → `ORCHESTRATOR_PROTECTED_TARGETS`
acrescentado ao `.env` do servidor (`mxos.com.br` + IP de produção) → `rsync` (0 arquivos apagados, compose intocado)
→ snapshot no repo do servidor (`b27d840`) → `docker compose build` → `up -d`.

Verificação ao vivo (dentro do container): `/health` 200 · `/v1/turn` sem token 401 e com token errado 401 ·
com token e texto > 32000 → 422 (autenticação passou, limite novo ativo) · 2 alvos protegidos carregados ·
guard bloqueia "escaneie o Contabo e não pare" e libera "nunca testar o Contabo" · 0 erros no log ·
container nas duas redes (`openclaw_default` e `agencia_ia_n8n-internal`) · `setuptools 84.2.1`.
Conferência só de leitura do n8n: 19 workflows, **nenhum resíduo** (`pytest-teste-orchestrator-*`),
nenhum atualizado depois de 21/10.

**Falta (só você consegue):** mandar uma mensagem real pelo WhatsApp e confirmar a resposta.

### Rollback (se algo estranho aparecer)

```bash
ssh contabo
cd /root/meu-agente-orchestrator
ORCHESTRATOR_IMAGE=meu-agente-orchestrator:rollback-pre-20261102 docker compose up -d   # volta à imagem anterior, sem rebuild
# o .env anterior está em /root/backups/pre-deploy-orchestrator-20261102/ (para remover PROTECTED_TARGETS, se necessário)
```

## Backups (contêm os dados sensíveis — apague quando não precisar mais)

Em `/home/max/Documentos/Kali Linux/`: `meu-agente-BACKUP-pre-limpeza-2026-11-02.bundle` (todas as refs antes da
limpeza do histórico) e `meu-agente-security-hardening-2026-11.bundle`. O commit antigo `a901da4` continua
acessível por SHA no GitHub (caches/forks); para remoção total, suporte do GitHub ou repositório privado.
Quem tiver clone antigo deve refazê-lo (`git clone`), não dar `pull`.

## Pendências

1. **Teste real pelo WhatsApp** após o deploy (acima).
2. **Testes TypeScript de `extensions/ask-max` nunca foram executados** (dependem do SDK do OpenClaw);
   `resolve-hook.test.ts` teve números de telefone trocados pela limpeza — rode `pnpm vitest` na extensão.
3. **Deriva repo ↔ servidor:** o `docker-compose.yml` de produção (rede do n8n) só existe no servidor.
   Versionar como override (ex.: `docker-compose.prod.yml`) para o deploy não depender de memória.
4. Imagem nova do **gateway** com token no `orchestrator-bridge` (pendência de 02/10; fora deste deploy).
5. Achados abertos da auditoria: S-10 (rate limit do webhook antes da assinatura), Dockerfile roda como root,
   lockfiles das extensões, confirmação para disparo de webhook n8n em produção, allowlist de alvos para o
   especialista de cibersegurança.
6. O padrão `mxos.com.br` em `ORCHESTRATOR_PROTECTED_TARGETS` também bloqueia varrer o próprio site da empresa.

## Como verificar a qualquer momento

```bash
cd orchestrator
pip install -e ".[dev,security]"
ruff check . && python -m pytest -q          # 359 passed, 1 skipped
bandit -r src -ll -q && pip-audit --skip-editable
```
