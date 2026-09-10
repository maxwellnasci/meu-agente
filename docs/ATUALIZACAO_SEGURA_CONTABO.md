# Guia de Atualização Segura — Contabo (Amigão / OpenClaw)

> **Status:** rascunho operacional, escrito em 2026-09-10 a partir do inventário de estado.
> **Nada neste guia foi executado.** Ele descreve o procedimento; a execução é manual e
> deve ser feita com o Max presente, seguindo a ordem e os pontos de validação abaixo.
>
> Este guia cobre três componentes que rodam no mesmo host (Contabo):
> 1. **Gateway OpenClaw** (`/root/openclaw/`, estado em `/root/.openclaw/`)
> 2. **Canal WhatsApp + plugins/extensões** (`whatsapp-cloud`, `ask-max`, `response-audit`,
>    `github-repo-report`) — hoje empacotados *dentro* da imagem do gateway
> 3. **Orquestrador LangGraph** (`/root/meu-agente-orchestrator/`)

---

## 0. Mapa de estado atual (o que o inventário confirma)

### ✅ Confirmado pelo inventário

| Item | Valor |
|---|---|
| Host | Contabo, `contabo` no `~/.ssh/config` (root, chave `id_ed25519_contabo`) |
| Specs | 4 vCPU, ~7.8 GB RAM, Docker 29.6.1, Ubuntu 24.04 |
| Versão OpenClaw em produção | `2026.6.9` + **19 commits locais** (repo vendorizado `openclaw/`, branch `production-local-fixes`) |
| Defasagem do upstream | `main` local está **~14.610 commits atrás** de `origin/main` (`openclaw/openclaw`). Upstream já tem branch `2026.9.1` |
| Remotes do repo vendorizado | `origin` = `openclaw/openclaw` (upstream), `backup` = `maxwellnasci/max-openclaw-local-fixes` (branch `production-local-fixes`) |
| Deploy do gateway no Contabo | `/root/openclaw/` contém **apenas** `docker-compose.yml` + `.env`. A imagem `openclaw:local` foi **buildada no Kali** e transferida via `docker save \| ssh contabo docker load` (Etapa 2 da migração). Não há árvore de código-fonte do OpenClaw no Contabo |
| Estado do gateway | `/root/.openclaw/` (config `openclaw.json`, `workspace/`, `credentials/`, `logs/`) — bind-mount, sobrevive a troca de imagem |
| Build flag crítico | Imagem compilada com `--build-arg OPENCLAW_INSTALL_DOCKER_CLI=1` (habilita sandbox Docker) |
| GID do docker.sock no Contabo | **988** — injetado via `docker-compose.override.yml` (`group_add: ${DOCKER_GID:-988}` no `.env` do servidor). Sem isso, o sandbox quebra em silêncio |
| Portas do gateway | `127.0.0.1:18789` (control UI / `healthz`), `3978` (MS Teams, se usado) — restritas a loopback |
| Canal WhatsApp | Cloudflare Tunnel com **1 único connector**, origem Contabo (`158.220.125.233`). Kali está fisicamente isolado desde o cutover (2026-08-02), `cloudflared` desligado lá |
| Credencial WhatsApp | `/root/.openclaw/credentials/whatsapp-cloud.json` — token System User, permanente. **Nunca sai do host** |
| Extensões próprias | `ask-max`, `whatsapp-cloud`, `response-audit`, `github-repo-report`. Fonte de verdade: `openclaw/extensions/` (ignorado pelo `.gitignore` do repo vendorizado). Cópia de backup versionada: `meu-agente/extensions/` (sync via `scripts/sync-extensions-backup.sh`). **Entram na imagem no momento do build** (fazem parte do contexto Docker) |
| Orquestrador no Contabo | `/root/meu-agente-orchestrator/` — repo com `.git` próprio, **sem remote**. Deploy via `scripts/deploy-orchestrator.sh` (rsync + `docker compose build` no servidor) |
| Orquestrador — imagem | `meu-agente-orchestrator:local` (build local) ou `${ORCHESTRATOR_IMAGE}` apontando pra `ghcr.io/maxwellnasci/meu-agente-orchestrator:<tag>` |
| Orquestrador — porta | `127.0.0.1:8000`, endpoint `/health` |
| Orquestrador — rede | usa rede externa `openclaw_default` (do compose do gateway). **O gateway precisa estar de pé primeiro** |
| Orquestrador — pré-requisito de disco | `orchestrator/data/` **precisa existir** ou o checkpointer SQLite derruba o startup |
| CI de imagem | `.github/workflows/docker-publish-orchestrator.yml` publica a imagem do orquestrador no `ghcr.io` **só** em tag `orchestrator-vX.Y.Z`. **Não existe CI equivalente para o gateway OpenClaw** (fora de escopo, decisão pendente) |
| Patches locais já conhecidos | SQLite `busy_timeout` 30s→3s (coma eterno), timeouts em hooks `reply_dispatch`/`reply_payload_sending`, `foregroundReplyFence` deadlock (corrigido em `whatsapp-cloud`), parametrização `DOCKER_GID`, plugin `orchestrator-bridge`, plugin `response-audit`, restrição de portas a loopback |

### ⚠️ Pontos ainda a validar (antes de qualquer atualização real)

Estes itens **não** estão confirmados pelo inventário e devem ser checados (comandos read-only)
antes de montar o plano definitivo:

1. **Como o Contabo recebe a imagem do gateway hoje.** O inventário diz "build no Kali + `docker save`/`load`".
   Confirmar se ainda é assim (`ssh contabo "docker images openclaw:local"` + data da imagem) ou se
   passou a buildar localmente em algum momento (procurar `/root/openclaw/Dockerfile`, `/root/openclaw/src/`).
2. **Hash exato do commit em produção.** Não há git no `/root/openclaw` do Contabo. O que roda é a imagem.
   Para saber a versão real: `ssh contabo "docker exec openclaw-openclaw-gateway-1 node -e \"console.log(require('./package.json').version)\""`.
   Comparar com o `HEAD` de `production-local-fixes` local.
3. **Qual alvo de upstream.** `2026.9.1` (branch) vs a última **tag estável** (`v2026.7.x` e adiante).
   Preferir sempre uma **tag de release**, nunca a ponta de `main`.
4. **Viabilidade do rebase dos 19 patches.** Com ~14.6k commits de distância, rebase direto vai gerar
   conflito em massa. Avaliar reaplicar os patches como um conjunto novo e pequeno sobre a base nova
   (ver §2.3). Antes disso: checar **quais dos 19 já foram absorvidos pelo upstream** (ex.: o fix de
   `busy_timeout`, timeouts de hooks) — reaplicar um patch já mesclado causa conflito e/ou regressão.
5. **Mudanças de schema do `openclaw.json`** entre `2026.6.9` e o alvo. Ler `CHANGELOG.md` do upstream
   e rodar `openclaw doctor` / validação de schema **contra uma cópia** antes de subir.
6. **Mudanças no Plugin SDK** que afetem as 4 extensões próprias (assinaturas de hook, formato de
   `openclaw.plugin.json`, APIs de `tool`). Buildar as extensões contra a base nova **num container
   descartável** e rodar os testes `*.test.ts` delas antes.
7. **Runtime da imagem** (versão de Node/Bun no `Dockerfile` novo) e se `OPENCLAW_INSTALL_DOCKER_CLI`
   ainda é o mecanismo de sandbox (pode ter virado `scripts/docker/setup.sh` / `OPENCLAW_SANDBOX=1`).
8. **Formato do estado em `~/.openclaw`** (sessões, memória, checkpoints) — se há migração automática
   na primeira subida da versão nova, e se ela é reversível.
9. **Versão do `cloudflared`** no Contabo vs a recomendada pela Cloudflare (hoje `2026.7.1`). Atualização
   do túnel é **independente** da do gateway e deve ser feita separada (ver §3.4).
10. **Janela real de indisponibilidade aceitável.** Definir com o Max antes (o canal WhatsApp tem a
    janela de 24h que fecha após idle — ver `feedback`/memória sobre erro `131047`).

---

## 1. Pré-requisitos e princípios

### 1.1 Antes de começar

- [ ] Sessão agendada **com o Max presente** (cutover de canal em produção — mesma regra do cutover original).
- [ ] Sem incidente aberto: `curl -s http://127.0.0.1:18789/healthz` → `{"ok":true,...}`, container `healthy`
      há > 1h, `cloudflared` sem restart loop, sem erro/`fatal`/`panic` nos logs das últimas 2h.
- [ ] Espaço em disco: `ssh contabo "df -h / && docker system df"` — reservar folga para 2 imagens
      simultâneas (a atual + a nova).
- [ ] `git status` limpo no repo `meu-agente` local e no `openclaw/` vendorizado (ou mudanças
      pendentes conhecidas e intencionais).
- [ ] Confirmar os 10 pontos da lista "a validar" (§0) — **não pular esta etapa**.

### 1.2 Princípios

1. **Uma etapa por vez, com validação entre elas.** Se uma validação falhar, **pare e faça rollback**
   antes de seguir — não empilhe mudanças.
2. **Nada de build no servidor sem necessidade.** A imagem do gateway é buildada no Kali (ou via CI
   quando existir) e transferida; o Contabo só faz `load`/`pull` + `up -d`.
3. **O estado (`/root/.openclaw`, `orchestrator/data`) nunca é apagado** durante a atualização.
   Só é *copiado* para backup.
4. **A imagem antiga fica no host** até a nova ser validada em produção por pelo menos 24h.
   Rollback = voltar a apontar pra ela.
5. **Segredos nunca no chat, nunca em commit, nunca em log colado.** Backup de credenciais fica no
   host, criptografado ou com permissão restrita.
6. **Atualizar um componente por sessão**, se possível. Ordem recomendada: **(1) extensões/plugins →
   (2) gateway OpenClaw → (3) orquestrador**. O canal WhatsApp acompanha o gateway (mesma imagem).
   `cloudflared` é uma quarta atualização, totalmente independente.

---

## 2. Backup (obrigatório — executar e verificar antes de tocar em qualquer coisa)

Todos os comandos abaixo são **no Contabo** (`ssh contabo`), exceto onde indicado.

### 2.1 Backup do estado do gateway

```bash
# No Contabo
TS=$(date -u +%Y%m%d-%H%M%S)
mkdir -p /root/backups/pre-update-$TS

# Estado completo do gateway (config, workspace, credenciais, logs)
tar -czf /root/backups/pre-update-$TS/openclaw-state.tar.gz -C /root .openclaw

# Cópia avulsa dos arquivos críticos (acesso rápido no rollback)
mkdir -p /root/backups/pre-update-$TS/critical
cp /root/.openclaw/openclaw.json                 /root/backups/pre-update-$TS/critical/
for f in AGENTS SOUL IDENTITY USER HEARTBEAT TOOLS; do
  cp "/root/.openclaw/workspace/$f.md" "/root/backups/pre-update-$TS/critical/" 2>/dev/null || true
done

# Compose + .env do deploy
cp /root/openclaw/docker-compose.yml /root/backups/pre-update-$TS/critical/
cp /root/openclaw/.env               /root/backups/pre-update-$TS/critical/env.bak
chmod 600 /root/backups/pre-update-$TS/critical/env.bak

# Verificação de integridade
sha256sum /root/backups/pre-update-$TS/openclaw-state.tar.gz | tee /root/backups/pre-update-$TS/SHA256SUMS
tar -tzf /root/backups/pre-update-$TS/openclaw-state.tar.gz | head   # lista sem erro = arquivo íntegro
```

**Detecção de falha:** `tar -tzf` retorna erro, `sha256sum` não gera hash, ou o `.tar.gz` tem
tamanho muito menor que `du -sh /root/.openclaw`. Nesse caso, **não prossiga**.

### 2.2 Snapshot da imagem atual do gateway (rollback instantâneo)

```bash
# No Contabo — "congela" a imagem que está rodando com uma tag de resgate
CUR_ID=$(docker inspect --format '{{.Image}}' openclaw-openclaw-gateway-1)
docker tag "$CUR_ID" openclaw:rollback-$TS
docker images | grep -E 'openclaw|rollback'
```

> A imagem `openclaw:local` costuma ser sobrescrita por um `load` novo. A tag `openclaw:rollback-$TS`
> garante que a versão boa não seja perdida por GC. Opcional (mais robusto): exportar para arquivo —
> `docker save openclaw:rollback-$TS | gzip > /root/backups/pre-update-$TS/openclaw-image.tar.gz`
> (pesa ~700 MB+; só se houver disco sobrando).

### 2.3 Backup do repo vendorizado local (Kali) e dos patches

```bash
# No Kali, dentro de openclaw/
cd "/home/max/Documentos/Kali Linux/meu-agente/openclaw"

# 1. Garantir que a branch de produção está publicada no remote de backup
git push backup production-local-fixes

# 2. Registrar exatamente quais commits são "os 19 patches locais" sobre a base
#    (ajuste a base pro merge-base real com a tag da versão em produção)
git merge-base production-local-fixes v2026.6.9 2>/dev/null || \
  git log --oneline v2026.6.9..production-local-fixes   # <-- lista os patches locais

# 3. Exportar os patches como arquivos .patch (portáveis pra qualquer base futura)
mkdir -p ../docs/patches-openclaw-$(date +%Y%m%d)
git format-patch v2026.6.9..production-local-fixes -o ../docs/patches-openclaw-$(date +%Y%m%d)
```

> **Por que exportar como `.patch`:** com ~14.6k commits de distância, um `git rebase` direto é
> inviável. O caminho realista é: criar uma branch nova a partir da **tag alvo** do upstream e
> `git am` (ou aplicar manualmente) só os patches que **ainda não foram absorvidos** pelo upstream.
> Cada patch aplicado deve ser revisado individualmente (ver ponto 4 da lista "a validar").

### 2.4 Backup do orquestrador

```bash
# No Contabo
TS=$(date -u +%Y%m%d-%H%M%S)   # reusar o mesmo TS da sessão, se ainda válido
mkdir -p /root/backups/pre-update-$TS/orchestrator
tar -czf /root/backups/pre-update-$TS/orchestrator/data.tar.gz -C /root/meu-agente-orchestrator data
cp /root/meu-agente-orchestrator/.env /root/backups/pre-update-$TS/orchestrator/env.bak
chmod 600 /root/backups/pre-update-$TS/orchestrator/env.bak
ssh_cur=$(docker inspect --format '{{.Image}}' meu-agente-orchestrator-orchestrator-1)
docker tag "$ssh_cur" meu-agente-orchestrator:rollback-$TS
# Snapshot do git local do servidor (histórico de deploys)
cd /root/meu-agente-orchestrator && git log --oneline -5 > /root/backups/pre-update-$TS/orchestrator/git-head.txt
```

### 2.5 Checklist de saída da fase de backup

- [ ] `openclaw-state.tar.gz` íntegro (`tar -tzf` ok) + `SHA256SUMS` gerado
- [ ] `openclaw:rollback-$TS` aparece em `docker images`
- [ ] `.env` (gateway e orquestrador) copiados com `chmod 600`
- [ ] `production-local-fixes` publicado em `backup`
- [ ] Patches exportados como `.patch` no repo local
- [ ] `orchestrator/data.tar.gz` + `meu-agente-orchestrator:rollback-$TS`
- [ ] Anotado em lugar seguro: TS da sessão, ID da imagem atual do gateway, versão reportada
      pelo `package.json` do container

---

## 3. Procedimento de atualização

### 3.1 Etapa A — Extensões / plugins (WhatsApp e demais)

> As 4 extensões (`ask-max`, `whatsapp-cloud`, `response-audit`, `github-repo-report`) vivem em
> `openclaw/extensions/` e **entram na imagem no build**. Atualizá-las = rebuildar a imagem do
> gateway. Portanto, na prática, a Etapa A e a Etapa B acontecem no mesmo build — mas a validação
> das extensões é feita **antes** de considerar o gateway pronto.

**Pré-requisitos:**
- Alvo do upstream já escolhido (§0, ponto 3).
- Branch de trabalho criada: `git switch -c update/<versão-alvo> <tag-alvo>` no `openclaw/` local.
- Extensões copiadas para a nova árvore: `cp -r` de `openclaw/extensions/{ask-max,whatsapp-cloud,response-audit,github-repo-report}`
  (a fonte de verdade) ou restaurar de `meu-agente/extensions/` via sync reverso.

**Ordem:**

1. Aplicar, um a um, os patches locais **que não foram absorvidos** pelo upstream
   (`git am ../docs/patches-openclaw-*/NNNN-*.patch`). Resolver conflito de cada patch antes do próximo.
2. Buildar **num container/host de teste** (Kali), com o flag de sandbox:
   ```bash
   # No Kali, dentro da branch de update
   docker build -t openclaw:test --build-arg OPENCLAW_INSTALL_DOCKER_CLI=1 .
   ```
3. Rodar os testes das extensões dentro da imagem de teste (ou no workspace pnpm):
   ```bash
   pnpm --filter './extensions/**' test        # ajustar ao runner real do repo
   ```
   Alvos mínimos: `whatsapp-cloud` (serialização por remetente / `foregroundReplyFence`),
   `response-audit` (heurística `false_action`), `github-repo-report` (policy / bloqueio de repos),
   `ask-max` (escalonamento).

**Validação da Etapa A:**
- [ ] `docker build` conclui sem erro.
- [ ] Testes das 4 extensões passam (mesma contagem de antes, ou diferença explicada).
- [ ] `openclaw.plugin.json` de cada extensão continua válido para o schema da versão nova.
- [ ] Log de boot da imagem de teste lista **os mesmos plugins** que produção (hoje: 11), sem erro.

**Detecção de falha:** build quebra por API de SDK mudada; plugin não carrega ("unknown hook",
"invalid manifest"); teste de `whatsapp-cloud` falha em concorrência. → **Não avance.** Trate o
patch/extensão ou reavalie o alvo de versão.

**Rollback da Etapa A:** descartar a branch de update (`git switch production-local-fixes`,
`git branch -D update/<versão>`). Nada em produção foi tocado.

---

### 3.2 Etapa B — Gateway OpenClaw

**Pré-condição:** Etapa A validada; imagem `openclaw:test` (agora renomeável para
`openclaw:<versão-alvo>`) pronta no Kali.

**Ordem dos comandos:**

```bash
# --- No Kali ---
docker tag openclaw:test openclaw:<versão-alvo>
docker save openclaw:<versão-alvo> | gzip | ssh contabo 'gunzip | docker load'

# --- No Contabo: revisar diff do compose ANTES de aplicar ---
cd /root/openclaw
# Se o compose do repo mudou entre as versões, comparar manualmente com o de produção.
# Ajustar .env do servidor se novas variáveis passaram a ser obrigatórias
# (ex.: DOCKER_GID=988 já deve estar lá; conferir OPENCLAW_* novas no .env.example).
docker compose config    # valida sintaxe + interpolação do .env, sem subir nada

# --- Cutover ---
# Apontar o compose pra imagem nova (via OPENCLAW_IMAGE no .env, OU editar o compose)
#   OPENCLAW_IMAGE=openclaw:<versão-alvo>
docker compose up -d      # recria só o que mudou; NÃO usar `down` (evita corrida no túnel)

# Acompanhar o boot
docker compose logs -f --since 2m openclaw-gateway
```

> **Por que `up -d` e não `down` + `up`:** `down` remove a rede `openclaw_default`, que o
> orquestrador usa como rede externa — derruba o orquestrador junto e força recriação. `up -d`
> recria só o container do gateway.
>
> **Lembrete do inventário:** `docker compose restart` **não relê o `.env`**. Toda mudança de
> variável exige `up -d` (recriar), nunca `restart`.

**Validação da Etapa B (nesta ordem):**

1. `docker compose ps` → `openclaw-gateway` como `healthy` (aguardar `start_period` de 20s +
   alguns ciclos de healthcheck).
2. `curl -s http://127.0.0.1:18789/healthz` → `{"ok":true,...}`.
3. Versão nova confirmada:
   ```bash
   docker exec openclaw-openclaw-gateway-1 node -e "console.log(require('./package.json').version)"
   ```
4. Plugins: nos logs de boot, mesma lista de antes, **zero** `plugin load error`.
5. Sandbox vivo (o flag `OPENCLAW_INSTALL_DOCKER_CLI` / `DOCKER_GID` funcionou):
   - disparar uma tarefa trivial que use o sandbox e ver o container efêmero nascer
     (`docker ps` durante a execução), **ou**
   - `docker exec openclaw-openclaw-gateway-1 id` mostrando o GID 988 nos grupos.
6. `openclaw.json` aceito sem "schema migration" destrutiva silenciosa — conferir nos logs
   se houve migração automática do estado e se ela foi anunciada.
7. **Teste real de ponta a ponta do WhatsApp:** o Max manda uma mensagem pelo número
   cadastrado; nos logs deve aparecer `WhatsApp Cloud reply started for <número>` seguido do
   trace do agente completando a sessão **sem erro**. Confirmar recebimento da resposta no aparelho.
8. Estabilidade: 10-15 min sem restart do container, sem `panic`/`fatal`, `cloudflared` sem
   restart loop, CPU do host normal (`ps aux --sort=-%cpu | head`).

**Detecção de falha:**
- Container em `restarting` / `unhealthy` após `start_period`.
- `healthz` não responde ou responde erro.
- Log com `plugin load error`, `schema validation failed`, `EACCES`, `mkdir '/Users'`
  (vazamento de path do `.env` — indica regressão nas variáveis `OPENCLAW_*_DIR`).
- Sandbox não sobe container efêmero (GID errado / CLI ausente).
- Mensagem de teste do WhatsApp não gera `reply started`, ou o agente responde com erro.
- Processo `docker exec` órfão em ~100% de CPU depois de teste manual de credencial
  (ver `docs/MANUTENCAO.md` — fechar sessões `docker exec -i` de forma limpa).

**Rollback da Etapa B:**

```bash
# No Contabo — voltar pra imagem congelada no backup
cd /root/openclaw
# .env: OPENCLAW_IMAGE=openclaw:rollback-$TS   (ou re-tag: docker tag openclaw:rollback-$TS openclaw:local)
docker compose up -d
docker compose ps && curl -s http://127.0.0.1:18789/healthz

# Se o estado foi migrado pela versão nova e não volta:
docker compose stop openclaw-gateway
rm -rf /root/.openclaw            # só se necessário — confirme o backup ANTES
mkdir /root/.openclaw
tar -xzf /root/backups/pre-update-$TS/openclaw-state.tar.gz -C /root
docker compose up -d
```

> Rollback do estado só é necessário se a versão nova reescreveu `~/.openclaw` num formato que a
> versão antiga não lê. Se a migração for só aditiva, basta trocar a imagem.

---

### 3.3 Etapa C — Orquestrador

> Independente do gateway em termos de código, mas **depende da rede `openclaw_default`** existir
> (o gateway precisa estar de pé). Faça o orquestrador **depois** do gateway estabilizar.

**Caminho 1 — deploy atual (rsync + build no servidor), via script existente:**

```bash
# No Kali
cd "/home/max/Documentos/Kali Linux/meu-agente"
./scripts/deploy-orchestrator.sh
```

O script já: roda os testes locais → `rsync -a --delete` (preservando `.env`, `data/`, `.git`) →
commit no git local do servidor → `docker compose build` → `up -d` → `curl /health`.

**Caminho 2 — deploy via imagem publicada (ghcr.io):**

```bash
# No Kali: cortar release
git tag orchestrator-vX.Y.Z && git push origin orchestrator-vX.Y.Z   # dispara o CI (32 testes + build + push)

# No Contabo, após o CI concluir:
cd /root/meu-agente-orchestrator
# .env: ORCHESTRATOR_IMAGE=ghcr.io/maxwellnasci/meu-agente-orchestrator:vX.Y.Z
mkdir -p data      # garantir que existe (senão o checkpointer SQLite derruba o startup)
docker compose pull && docker compose up -d
```

**Validação da Etapa C:**
- [ ] `curl -sf http://127.0.0.1:8000/health` → `{"status":"ok"}`.
- [ ] `docker logs meu-agente-orchestrator-orchestrator-1 --since 2m` sem stack trace no boot
      (em especial: **sem** `unable to open database file` — significaria `data/` ausente).
- [ ] Teste funcional: disparar uma tarefa via o especialista (ex.: `run_local_task` ou uma
      mensagem que o Amigão delegue ao orquestrador) e ver a resposta voltar completa.
- [ ] Rede: `docker inspect meu-agente-orchestrator-orchestrator-1 --format '{{json .NetworkSettings.Networks}}'`
      mostra `openclaw_default`; o orquestrador resolve o gateway pelo nome do container.
- [ ] Checkpoints antigos ainda decodificam (histórico de conversa preservado). Se a versão nova
      mudou o `GraphState`, ver política em `docs/DEPLOY_IMAGEM.md` (pode exigir limpar `data/`).

**Detecção de falha:** `/health` não responde; boot com erro de SQLite / migração; especialista
não completa tarefa; container não entra na rede `openclaw_default` (nome/rede externa mudou).

**Rollback da Etapa C:**

```bash
# No Contabo
cd /root/meu-agente-orchestrator
# .env: ORCHESTRATOR_IMAGE=meu-agente-orchestrator:rollback-$TS
#   (Caminho 1: git reset --hard <hash de git-head.txt> && docker compose build)
docker compose up -d
# Se data/ foi corrompido pela versão nova:
docker compose stop
rm -rf data && mkdir data
tar -xzf /root/backups/pre-update-$TS/orchestrator/data.tar.gz -C /root/meu-agente-orchestrator
docker compose up -d
curl -sf http://127.0.0.1:8000/health
```

---

### 3.4 Etapa D — `cloudflared` (túnel WhatsApp) — opcional e independente

> **Não misturar com a Etapa B.** Atualizar o túnel troca o binário/serviço que expõe o webhook
> do WhatsApp; é a mudança de maior risco de indisponibilidade do canal.

**Ordem:**
1. Checar versão atual: `ssh contabo "cloudflared --version"`.
2. Baixar o `.deb` da versão alvo **do GitHub releases da Cloudflare** (mesma origem usada antes).
3. `systemctl stop cloudflared` → `dpkg -i cloudflared-XXXX.deb` → `systemctl start cloudflared`.
4. Validar (§ abaixo). Janela de indisponibilidade do webhook = tempo entre `stop` e `start` ok
   (segundos, se o `.deb` já estiver no host).

**Validação:**
- [ ] `systemctl status cloudflared` → `active (running)`, sem restart loop por 10 min.
- [ ] `cloudflared tunnel info <ID>` → **1 único** connector ativo, origem Contabo.
- [ ] Mensagem de teste do WhatsApp entregue e respondida (mesmo teste da Etapa B, item 7).

**Detecção de falha:** serviço não sobe; `tunnel info` sem connector; webhook do WhatsApp com
timeout; Meta reclamando de entrega (erro `131047` é **outra coisa** — janela de 24h, não túnel).

**Rollback:** reinstalar o `.deb` da versão anterior (guardar o `.deb` atual antes de atualizar) e
`systemctl restart cloudflared`.

---

## 4. Pós-atualização (todas as etapas concluídas)

- [ ] **24h de observação** antes de apagar qualquer imagem `:rollback-$TS` ou backup.
- [ ] Monitorar: `healthz` do gateway, `/health` do orquestrador, logs sem `error`/`fatal`,
      `cloudflared` estável, CPU do host (sem processo órfão em ~100%).
- [ ] Rodar o teste real de ponta a ponta do WhatsApp mais uma vez no dia seguinte.
- [ ] Se estável por 24h+:
  - `git push backup update/<versão>` e mesclar em `production-local-fixes` (ou renomear a branch).
  - Sincronizar a cópia de backup das extensões: `./scripts/sync-extensions-backup.sh` +
    `git add extensions/ && git commit`.
  - Atualizar `docs/MANUTENCAO.md` (a seção "Update OpenClaw" está com o processo antigo do Kali) e
    `docs/ESTADO_ATUAL.md` com a nova versão em produção.
  - Remover imagens de rollback: `docker rmi openclaw:rollback-$TS meu-agente-orchestrator:rollback-$TS`
    e limpar `/root/backups/pre-update-$TS` **só depois** de confirmada a estabilidade.
- [ ] Atualizar este guia com o que divergiu na prática (gotchas reais > plano teórico).

---

## 5. Quadro-resumo de rollback

| Componente | Rollback rápido | Rollback de estado |
|---|---|---|
| Gateway OpenClaw | `.env`: `OPENCLAW_IMAGE=openclaw:rollback-$TS` → `docker compose up -d` | `tar -xzf .../openclaw-state.tar.gz -C /root` com o container parado |
| Extensões/plugins | Já embutidas na imagem → volta com o rollback do gateway | — |
| Orquestrador | `.env`: `ORCHESTRATOR_IMAGE=...:rollback-$TS` → `up -d` (ou `git reset --hard` + `build`) | `tar -xzf .../orchestrator/data.tar.gz` |
| `cloudflared` | `dpkg -i` do `.deb` anterior → `systemctl restart cloudflared` | — |

**Regra de ouro:** se dois componentes estiverem instáveis ao mesmo tempo, faça rollback do
**gateway primeiro** (é a base da rede e do canal), valide, depois avalie os demais.

---

## 6. Referências internas

- `docs/MANUTENCAO.md` — processo antigo de update (Kali) + caso do processo `docker exec` órfão.
- `docs/DEPLOY_IMAGEM.md` — deploy do orquestrador via registry, versionamento e política de `data/`.
- `scripts/deploy-orchestrator.sh` — deploy atual do orquestrador (rsync + build no servidor).
- `scripts/sync-extensions-backup.sh` — sync da cópia de backup das extensões.
- `openclaw/docker-compose.yml` + `openclaw/docker-compose.override.yml` — compose do gateway e `group_add`/`DOCKER_GID`.
- `orchestrator/docker-compose.yml` — compose do orquestrador (rede externa `openclaw_default`).
- Memória do projeto: migração Contabo (Etapas 0-7), incidente cérebro/n8n 05/09, janela de 24h do WhatsApp.
