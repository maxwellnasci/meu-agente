# WORKFLOW — estado do projeto e fluxo de revisão/publicação

Atualizado em **2026-11-02**. Este arquivo registra o ponto em que o projeto foi
deixado pronto para revisão humana: tudo está **local**, **nada foi enviado ao GitHub**.

## Estado atual (limpo, local)

| Item | Situação |
|---|---|
| Branch `master` (local) | contém a auditoria de segurança integrada (merge) + histórico **reescrito** |
| Histórico git | IP do servidor de produção, um segundo IP e o telefone do operador **removidos de todos os commits** das branches locais (substituídos por `203.0.113.x` e número zerado) |
| Testes | **359 passam, 1 pulado** (o teste live do n8n exige `RUN_LIVE_N8N_TESTS=1`) |
| Lint / SAST / deps | `ruff` limpo · `bandit -ll` sem achados · `pip-audit` sem CVEs |
| Ambientes verificados | `orchestrator/.venv` (Python 3.14) e venv novo (resolução do zero); em Python 3.11 (CI/imagem) a versão pré-limpeza passou com 359 testes |
| `git push` | **NÃO executado** |
| Produção (Contabo) | **não alterada** — ainda roda o código anterior |

Relatório completo da auditoria: [docs/SEGURANCA_AUDITORIA_2026-11-02.md](docs/SEGURANCA_AUDITORIA_2026-11-02.md)
· modelo de ameaças: [SECURITY.md](SECURITY.md).

### Atenção: a `master` local divergiu do `origin/master`

A reescrita do histórico muda **todos os SHAs**. O `origin/master` (cópia da última
posição conhecida do remoto) ainda tem o histórico antigo, com IP e telefone. Isso é
esperado e é o que permite o `--force-with-lease` abaixo.

## Backups (contêm os dados sensíveis — apague depois de revisar)

Em `/home/max/Documentos/Kali Linux/`:

- `meu-agente-BACKUP-pre-limpeza-2026-11-02.bundle` — **todas** as refs antes da limpeza (inclui o merge de segurança)
- `meu-agente-security-hardening-2026-11.bundle` — só a branch de segurança, antes do merge

Para voltar ao estado anterior à limpeza: `git clone <bundle> pasta-restaurada` (ou, enquanto
o reflog existir, `git reset --hard 3eda69c`).

## O que revisar antes de subir

1. `git log --oneline -13` — os 13 commits **novos de conteúdo** (11 da auditoria, o merge e
   este). Atenção: `git log origin/master..master` mostrará ~160 commits, porque a reescrita
   mudou os SHAs de praticamente todo o histórico — isso é esperado, não são 160 mudanças.
2. `git diff origin/master master --stat` compara o **conteúdo** (árvores), então funciona
   mesmo com SHAs diferentes: deve mostrar a auditoria (arquivos novos/alterados) mais os
   poucos arquivos em que IP/telefone foram trocados. É a melhor forma de revisar.
3. **Testes TypeScript de `extensions/ask-max` NÃO foram executados** (dependem do SDK do
   OpenClaw). `resolve-hook.test.ts` teve números de telefone trocados pela limpeza — rode
   `pnpm vitest` na extensão antes do push.
4. Confirme que nenhum servidor faz `git pull` agendado deste repositório (quebraria com o
   histórico reescrito) e que nenhum outro clone tem trabalho não enviado.
5. O **gitleaks nunca foi executado** localmente; a primeira execução do CI pode apontar falso
   positivo (ver `.gitleaks.toml`).

## Subir (quando você decidir) — manual

```bash
cd "/home/max/Documentos/Kali Linux/meu-agente"
git diff origin/master master --stat             # confira o conteúdo que vai
git push --force-with-lease origin master        # reescreve o histórico do remoto (todos os SHAs mudam)
```

`--force-with-lease` só sobrescreve se o remoto ainda estiver onde o seu `origin/master`
diz — não apaga trabalho de terceiros por engano. **É irreversível no remoto**: faça o backup
acima antes. O GitHub pode manter os commits antigos acessíveis por SHA (forks, PRs, caches);
para remoção total, peça ao suporte. Se preferir, torne o repositório privado antes.

Depois do push, quem tiver clone antigo deve refazê-lo (`git clone`), não dar `pull`.

## Pendências de produção (nada disto foi feito)

1. Rebuild da imagem do orquestrador e deploy — as correções só valem depois.
2. `.env` do servidor: definir `ORCHESTRATOR_PROTECTED_TARGETS` **com o IP real de produção**
   e recriar o container com `docker compose up -d` (`restart` não relê o `.env`).
   O padrão `mxos.com.br` também bloqueia varrer o próprio site da empresa.
3. Conferir o n8n de produção por workflows residuais (um teste live rodou uma vez contra ele
   durante a auditoria, antes de passar a exigir opt-in).
4. Achados abertos: S-10 (rate limit do webhook antes da assinatura), Dockerfile como root,
   lockfiles das extensões, confirmação para disparo de webhook n8n em produção.

## Como verificar a qualquer momento

```bash
cd orchestrator
pip install -e ".[dev,security]"
ruff check . && python -m pytest -q          # 359 passed, 1 skipped
bandit -r src -ll -q && pip-audit --skip-editable
```
