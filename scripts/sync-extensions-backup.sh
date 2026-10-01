#!/bin/bash
# Atualiza o backup de código das extensões próprias em meu-agente/extensions/
# a partir da fonte de verdade em openclaw/extensions/ (repo de terceiros,
# ignorado pelo .gitignore). Backup por cópia, não symlink: o build Docker
# do openclaw usa `openclaw/` como contexto e não enxerga nada fora dela.
#
# Cada extensão é sincronizada isoladamente (um rsync --delete por par de
# diretórios "$SRC/<ext>/" -> "$DST/<ext>/"), então sincronizar uma extensão
# nunca toca no diretório de outra.
#
# Uso:
#   ./scripts/sync-extensions-backup.sh <extensao> [<extensao2> ...]
#       Sincroniza só as extensões indicadas (modo recomendado, padrão seguro).
#       Ex.: ./scripts/sync-extensions-backup.sh orchestrator-bridge
#
#   ./scripts/sync-extensions-backup.sh --all --yes-sync-all
#       Sincroniza TODAS as extensões conhecidas de uma vez. Exige a flag de
#       confirmação explícita --yes-sync-all; sem ela, nada é alterado.
#
# Depois: git add extensions/ && git commit -m "..." && git push
#
# Incidente histórico (registrado em docs): uma sincronização sem escopo
# definido, pensada só para orchestrator-bridge, também rodou --delete sobre
# github-repo-report e whatsapp-cloud, cujo estado local havia divergido da
# fonte em openclaw/extensions/. Por isso o modo "uma extensão" agora é o
# padrão e o modo "todas" exige confirmação explícita e lista o escopo antes
# de mexer em qualquer arquivo.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/openclaw/extensions"
DST="$REPO_ROOT/extensions"

KNOWN_EXTENSIONS=(ask-max whatsapp-cloud response-audit github-repo-report orchestrator-bridge)

usage() {
  cat >&2 <<EOF
Uso:
  $0 <extensao> [<extensao2> ...]
      Sincroniza só as extensões indicadas. Modo recomendado e padrão seguro.

  $0 --all --yes-sync-all
      Sincroniza TODAS as extensões conhecidas (${KNOWN_EXTENSIONS[*]}).
      Requer a flag --yes-sync-all como confirmação explícita.

Extensões conhecidas: ${KNOWN_EXTENSIONS[*]}
EOF
}

is_known_extension() {
  local candidate="$1"
  local known
  for known in "${KNOWN_EXTENSIONS[@]}"; do
    if [ "$candidate" = "$known" ]; then
      return 0
    fi
  done
  return 1
}

sync_one() {
  local ext="$1"
  if [ ! -d "$SRC/$ext" ]; then
    echo "AVISO: $SRC/$ext não existe, pulando." >&2
    return
  fi
  rsync -a --delete \
    --exclude node_modules \
    --exclude dist \
    --exclude ".env" \
    --exclude "*.log" \
    "$SRC/$ext/" "$DST/$ext/"
  echo "Sincronizado: $ext"
}

if [ "$#" -eq 0 ]; then
  usage
  exit 1
fi

if [ "$1" = "--all" ]; then
  if [ "${2:-}" != "--yes-sync-all" ]; then
    echo "ERRO: --all exige confirmação explícita com --yes-sync-all." >&2
    echo "Isso roda rsync --delete sobre TODAS as extensões a seguir:" >&2
    echo "  ${KNOWN_EXTENSIONS[*]}" >&2
    echo "Se é isso que você quer, rode: $0 --all --yes-sync-all" >&2
    exit 1
  fi
  echo "Escopo confirmado: sincronizando TODAS as extensões (${KNOWN_EXTENSIONS[*]})."
  for ext in "${KNOWN_EXTENSIONS[@]}"; do
    sync_one "$ext"
  done
else
  targets=("$@")
  for ext in "${targets[@]}"; do
    case "$ext" in
      */* | . | ..)
        echo "ERRO: nome de extensão inválido: '$ext'." >&2
        exit 1
        ;;
    esac
    if ! is_known_extension "$ext"; then
      echo "ERRO: '$ext' não é uma extensão conhecida." >&2
      echo "Conhecidas: ${KNOWN_EXTENSIONS[*]}" >&2
      exit 1
    fi
  done
  echo "Escopo: sincronizando ${targets[*]}."
  for ext in "${targets[@]}"; do
    sync_one "$ext"
  done
fi

echo ""
echo "Pronto. Revise com 'git status' e commite se houver mudanças reais:"
echo "  git add extensions/ && git commit -m 'backup: sync extensões' && git push"
