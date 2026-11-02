#!/bin/bash
# Deploy repetivel do Orquestrador (orchestrator/) para o servidor Contabo.
#
# Antes desta ferramenta, o deploy era manual: copiar arquivo por arquivo
# via scp e rebuildar na mao (ver docs/ESTADO_ATUAL.md, marco 2026-08-24).
# O repo em /root/meu-agente-orchestrator no Contabo tem seu proprio .git
# (raiz = orchestrator/, sem remote configurado) porque a estrutura de
# pastas diverge do monorepo local (aqui orchestrator/ e uma subpasta) -
# por isso o deploy e via rsync + commit local no servidor, nao git pull.
# Mesmo padrao ja usado em scripts/sync-extensions-backup.sh para o mesmo
# tipo de conflito estrutural.
#
# Uso: ./scripts/deploy-orchestrator.sh
# Requer: alias SSH "contabo" configurado em ~/.ssh/config.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/orchestrator/"
REMOTE_HOST="contabo"
REMOTE_DIR="/root/meu-agente-orchestrator"

echo "==> Rodando testes locais antes de sincronizar..."
(cd "$REPO_ROOT/orchestrator" && source .venv/bin/activate 2>/dev/null; python -m pytest -q)

# ATENCAO (aprendido no deploy de 2026-11-02): o servidor tem coisas que NAO
# existem no repo e que o rsync --delete destruiria:
#   - docker-compose.yml com a rede extra "agencia_ia_n8n-internal" (e por ela
#     que o orquestrador alcanca o n8n) - sobrescreve-lo quebra o especialista n8n;
#   - backups soltos (.env.bak-*, docker-compose.yml.bak-*), que o --delete apagaria.
# Por isso eles ficam excluidos do rsync (e, abaixo, do snapshot git).
echo "==> Sincronizando código para $REMOTE_HOST:$REMOTE_DIR ..."
rsync -a --delete \
  --exclude ".venv" \
  --exclude ".git" \
  --exclude "data" \
  --exclude ".env" \
  --exclude ".env.bak-*" \
  --exclude "docker-compose.yml" \
  --exclude "docker-compose.yml.bak-*" \
  --exclude ".pytest_cache" \
  --exclude ".ruff_cache" \
  --exclude "__pycache__" \
  --exclude "response.json" \
  --exclude ".gitignore" \
  "$SRC" "$REMOTE_HOST:$REMOTE_DIR/"

echo "==> Commitando snapshot no repo do servidor (rastreabilidade local)..."
# O .gitignore do servidor ignora so ".env" exato: um "git add -A" comitaria os
# backups ".env.bak-*" (com chaves de API) no historico git do servidor.
ssh "$REMOTE_HOST" "cd $REMOTE_DIR && git add -A -- . ':!.env.bak-*' ':!docker-compose.yml.bak-*' && (git diff --cached --quiet || git commit -m 'deploy: sync a partir do repo local meu-agente/orchestrator')"

echo "==> Rebuild da imagem Docker..."
ssh "$REMOTE_HOST" "cd $REMOTE_DIR && docker compose build"

echo "==> Recriando container..."
ssh "$REMOTE_HOST" "cd $REMOTE_DIR && docker compose up -d"

echo "==> Healthcheck (ate ~30s: a recriacao do container levou ~10s no deploy de 2026-11-02)..."
ssh "$REMOTE_HOST" 'for i in $(seq 1 15); do curl -sf http://127.0.0.1:8000/health && echo && exit 0; sleep 2; done; exit 1' || {
  echo "FALHA no healthcheck - verifique 'docker logs meu-agente-orchestrator-orchestrator-1' no servidor." >&2
  exit 1
}

echo "==> Deploy concluido."
