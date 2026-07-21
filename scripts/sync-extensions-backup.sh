#!/bin/bash
# Atualiza o backup de código das extensões próprias em meu-agente/extensions/
# a partir da fonte de verdade em openclaw/extensions/ (repo de terceiros,
# ignorado pelo .gitignore). Backup por cópia, não symlink: o build Docker
# do openclaw usa `openclaw/` como contexto e não enxerga nada fora dela.
#
# Uso: ./scripts/sync-extensions-backup.sh
# Depois: git add extensions/ && git commit -m "..." && git push

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/openclaw/extensions"
DST="$REPO_ROOT/extensions"

EXTENSIONS=(ask-max whatsapp-cloud response-audit github-repo-report)

for ext in "${EXTENSIONS[@]}"; do
  if [ ! -d "$SRC/$ext" ]; then
    echo "AVISO: $SRC/$ext não existe, pulando." >&2
    continue
  fi
  rsync -a --delete \
    --exclude node_modules \
    --exclude dist \
    --exclude ".env" \
    --exclude "*.log" \
    "$SRC/$ext/" "$DST/$ext/"
  echo "Sincronizado: $ext"
done

echo ""
echo "Pronto. Revise com 'git status' e commite se houver mudanças reais:"
echo "  git add extensions/ && git commit -m 'backup: sync extensões' && git push"
