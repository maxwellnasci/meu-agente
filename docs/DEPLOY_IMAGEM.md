# Deploy via imagem publicada (registry) — orquestrador

Preparado em 2026-08-25 e **validado ao vivo no mesmo dia**: tag
`orchestrator-v0.1.0` criada, workflow rodou de ponta a ponta (32 testes
+ build + push), imagem puxada de volta via `docker pull` e subida via
`ORCHESTRATOR_IMAGE` (sem build local) — `/health` respondeu `ok`. A
imagem real está em `ghcr.io/maxwellnasci/meu-agente-orchestrator:v0.1.0`
(e `:latest`).

**Nota de visibilidade**: o repo `meu-agente` é público no GitHub, então
o pacote também ficou público por padrão — mesma exposição que o código
já tinha no repo (a imagem não carrega segredo nenhum, confirmado via
`.dockerignore`). Se decidirem tornar o repo privado no futuro, revisitar
a visibilidade do pacote também.

## Ideia

Uma imagem Docker genérica (sem nada de cliente dentro) é buildada uma vez,
publicada no GitHub Container Registry (ghcr.io), e cada servidor de
cliente só faz `docker pull` + `docker compose up -d` apontando pra essa
imagem — nunca builda localmente. O que muda por cliente fica **fora** da
imagem: `.env` (segredos), `data/` (histórico de conversa via SQLite
checkpoint), e o `openclaw.json`/workspace do gateway (bind mount).

Isso já era essencialmente verdade antes desta mudança — o `Dockerfile` do
orquestrador nunca copiou `.env` nem `data/` (confirmado em
`orchestrator/.dockerignore`), e o gateway OpenClaw já monta
`openclaw.json`, workspace e segredos como volumes externos, nunca dentro
da imagem. O que faltava era só o mecanismo de publicar/puxar a imagem em
vez de buildar em cada servidor.

## O que foi preparado nesta sessão

- `orchestrator/docker-compose.yml`: `image:` agora lê
  `${ORCHESTRATOR_IMAGE}` com fallback pro comportamento atual
  (`meu-agente-orchestrator:local`, build local). Testado nos dois modos
  (`docker compose config` com e sem a variável) e com build+run real
  (`docker compose up` + `/health` respondeu `{"status":"ok"}`).
- `.github/workflows/docker-publish-orchestrator.yml`: pipeline que roda os
  32 testes, builda e publica no ghcr.io — só dispara em tag
  `orchestrator-vX.Y.Z` ou manualmente (`workflow_dispatch`), nunca em todo
  push. YAML validado (`yaml.safe_load` sem erro).
- `openclaw/docker-compose.yml`: corrigido bug de portabilidade achado
  nesta sessão — `group_add` tinha o GID do grupo docker do Kali
  (`124`) hardcoded; um servidor de cliente com GID diferente perderia o
  acesso ao `docker.sock` montado (sandbox real quebraria silenciosamente).
  Agora lê `${DOCKER_GID:-124}` — default preserva o comportamento atual,
  mas fica configurável. **Nota**: esse arquivo vive no repo vendorizado
  `openclaw/` (git próprio, `CLAUDE.md` com política de contribuição
  própria) — só editei o arquivo, não commitei lá; commitar essa mudança
  específica fica a critério de vocês (o repo tem uma pilha grande de
  outras mudanças locais não relacionadas, não mexi nelas).

**Fora de escopo, deliberadamente**: publicar a imagem do gateway
OpenClaw (`openclaw/`) via CI. O build dele é multi-stage (Node/Bun,
extensões customizadas ainda não commitadas no repo vendorizado) — decidir
isso junto com "qual conjunto de extensões vai na imagem oficial do
cliente" antes de montar o pipeline, pra não empacotar código
não-finalizado.

## Como usar num servidor de cliente

1. Como o pacote é público (repo público), não precisa de PAT pra
   **puxar** a imagem — só `docker pull ghcr.io/maxwellnasci/meu-agente-orchestrator:v0.1.0`
   direto funciona em qualquer servidor. PAT só seria necessário se o
   pacote virasse privado no futuro.
2. Exportar `ORCHESTRATOR_IMAGE=ghcr.io/maxwellnasci/meu-agente-orchestrator:v0.1.0`
   no `.env` do servidor, rodar `docker compose pull && docker compose up -d`
   — validado ao vivo, é exatamente esse fluxo que rodou no teste.
3. Deploy atual (`scripts/deploy-orchestrator.sh`, rsync + build no
   servidor) continua funcionando sem nenhuma mudança — os dois caminhos
   coexistem; migrar o Contabo pro modo registry é uma decisão separada,
   não obrigatória por essa mudança.
4. Pra cortar um release novo: `git tag orchestrator-vX.Y.Z && git push
   origin orchestrator-vX.Y.Z` — dispara o workflow automaticamente.

## Versionamento e rollback

- Tags de imagem seguem a tag do git: `orchestrator-v1.2.0` → imagem
  `:v1.2.0`. `:latest` sempre aponta pro release mais recente.
- Rollback = trocar `ORCHESTRATOR_IMAGE` pra uma tag anterior no `.env` do
  servidor e rodar `docker compose pull && docker compose up -d` de novo —
  não precisa rebuildar nada, a imagem antiga já está no registry.
- Antes de cortar uma tag, os 32 testes já rodam automaticamente no CI —
  se falhar, a imagem não é publicada.

## Estado salvo entre versões (checkpoint SQLite)

O histórico de conversa (`data/checkpoints.sqlite`, via LangGraph
checkpointer) fica num volume externo, sobrevive a troca de imagem. Isso é
bom pra atualização normal, mas **se uma mudança futura alterar o formato
do `GraphState`** salvo, checkpoints antigos podem não decodificar direito
com a imagem nova.

Política adotada: não é banco de dados de produção crítico, é memória de
conversa recente. Se uma mudança de schema for necessária, a opção mais
simples é documentar que aquela versão exige limpar `data/` (reseta o
histórico das conversas em andamento, não é um dado que precise de
migração formal). Revisitar essa política se o projeto crescer a ponto do
histórico de conversa virar algo que não pode ser perdido.
