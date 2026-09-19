#!/usr/bin/env bash
# Provisiona o ambiente de um cliente (multi-tenant) a partir de um nicho.
#
# Uso:
#   ./scripts/provision-client.sh --name "ClinicaSaoLucas" --niche "clinica-saude" \
#       [--operator-name "Dra. Ana"] [--operator-to "5541999999999"] \
#       [--channel "whatsapp-cloud"] [--port 8001] [--force]
#
# Cria deployments/<nome-cliente>/ com:
#   .env .............. variaveis proprias do cliente (nao commitar - gitignored)
#   AGENTS.md ......... manual do atendente, a partir do template do nicho
#   docker-compose.yml  compose do cliente (orquestrador dedicado na rede
#                       compartilhada meu-agente-net)
#   workflows/ ........ copia do workflow n8n de exemplo do nicho
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATES_DIR="$ROOT/templates/nichos"
DEPLOYMENTS_DIR="$ROOT/deployments"

NAME=""
NICHE=""
OPERATOR_NAME="Max"
OPERATOR_TO=""
CHANNEL="whatsapp-cloud"
PORT="8000"
FORCE=0

usage() {
  echo "Uso: $0 --name <NomeCliente> --niche <nicho> [opcoes]"
  echo "Nichos disponiveis: $(ls "$TEMPLATES_DIR" 2>/dev/null | tr '\n' ' ')"
  echo "Opcoes: --operator-name, --operator-to, --channel, --port, --force, --help"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="${2:-}"; shift 2 ;;
    --niche) NICHE="${2:-}"; shift 2 ;;
    --operator-name) OPERATOR_NAME="${2:-}"; shift 2 ;;
    --operator-to) OPERATOR_TO="${2:-}"; shift 2 ;;
    --channel) CHANNEL="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "erro: argumento desconhecido: $1" >&2; usage >&2; exit 1 ;;
  esac
done

[ -n "$NAME" ] || { echo "erro: --name e obrigatorio" >&2; usage >&2; exit 1; }
[ -n "$NICHE" ] || { echo "erro: --niche e obrigatorio" >&2; usage >&2; exit 1; }

# Nome seguro: so letras, numeros, traco e underline (sem path traversal).
if [[ ! "$NAME" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "erro: --name deve conter so letras, numeros, '-' e '_' (recebido: $NAME)" >&2
  exit 1
fi

# Nicho: formato seguro antes de checar existencia.
if [[ ! "$NICHE" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "erro: --niche deve conter so letras, numeros, '-' e '_' (recebido: $NICHE)" >&2
  exit 1
fi

# Nicho precisa existir como template.
if [ ! -d "$TEMPLATES_DIR/$NICHE" ]; then
  echo "erro: nicho desconhecido: $NICHE" >&2; usage >&2; exit 1
fi
[ -f "$TEMPLATES_DIR/$NICHE/AGENTS.md" ] || { echo "erro: template sem AGENTS.md: $NICHE" >&2; exit 1; }

# Porta numerica valida.
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || ! [ "$PORT" -ge 1 ] || ! [ "$PORT" -le 65535 ]; then
  echo "erro: --port invalida: $PORT" >&2; exit 1
fi

# Telefone do operador: vazio ou formato internacional (+ opcional, 8-15 digitos).
if [[ ! -z "$OPERATOR_TO" && ! "$OPERATOR_TO" =~ ^\+?[0-9]{8,15}$ ]]; then
  echo "erro: --operator-to invalido (use formato internacional com 8-15 digitos): $OPERATOR_TO" >&2
  exit 1
fi

# Campos livres: rejeitar caracteres de controle e caracteres que quebram
# o parsing no Compose e no shell ($, ', ", \, `, #).
reject_unsafe_free_field() {
  local opt="$1"
  local val="$2"
  if [[ "$val" =~ [[:cntrl:]] ]]; then
    echo "erro: $opt contem caracteres de controle" >&2
    exit 1
  fi
  case "$val" in
    *'$'*|*"'"*|*'"'*|*\\*|*'`'*|*'#'*)
      echo "erro: $opt contem caractere invalido (\$, ', \", \\, \` ou #)" >&2
      exit 1
      ;;
  esac
}
reject_unsafe_free_field "--operator-name" "$OPERATOR_NAME"
reject_unsafe_free_field "--channel" "$CHANNEL"

DEST="$DEPLOYMENTS_DIR/$NAME"
if [ -e "$DEST" ] && [ "$FORCE" -ne 1 ]; then
  echo "erro: $DEST ja existe (use --force para recriar)" >&2; exit 1
fi

mkdir -p "$DEPLOYMENTS_DIR"
TMP_DEST="$(mktemp -d "$DEPLOYMENTS_DIR/.${NAME}.tmp.XXXXXX")"
BACKUP_DEST=""
chmod 755 "$TMP_DEST"
cleanup() {
  if [ -n "$TMP_DEST" ]; then
    rm -rf -- "$TMP_DEST"
  fi
  if [ -n "$BACKUP_DEST" ] && [ -e "$BACKUP_DEST" ]; then
    if [ ! -e "$DEST" ]; then
      mv -T "$BACKUP_DEST" "$DEST" 2>/dev/null || rm -rf -- "$BACKUP_DEST"
    else
      rm -rf -- "$BACKUP_DEST"
    fi
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p "$TMP_DEST/workflows"
mkdir -p "$TMP_DEST/data"

# 1) AGENTS.md customizado a partir do template do nicho.
# Substituicao em passada unica via re.sub com dicionario: evita que um valor
# inserido (ex: OPERATOR_NAME contendo "[CANAL]") seja re-substituido.
python3 -c '
import re, sys

src, dst, name, op_name, op_to, channel = sys.argv[1:7]
with open(src, encoding="utf-8") as f:
  text = f.read()

mapping = {
    "NOME_DA_CLINICA": name,
    "NOME_DA_EMPRESA": name,
    "OPERADOR_NOME": op_name,
    "OPERADOR_NUMERO": op_to,
    "CANAL": channel,
}
pattern = re.compile(
    r"\[(NOME_DA_CLINICA|NOME_DA_EMPRESA|OPERADOR_NOME|OPERADOR_NUMERO|CANAL)\]"
)
result = pattern.sub(lambda m: mapping[m.group(1)], text)

with open(dst, "w", encoding="utf-8") as f:
  f.write(result)
' "$TEMPLATES_DIR/$NICHE/AGENTS.md" "$TMP_DEST/AGENTS.md" "$NAME" "$OPERATOR_NAME" "$OPERATOR_TO" "$CHANNEL"

# 2) Workflow(s) n8n de exemplo do nicho.
cp "$TEMPLATES_DIR/$NICHE"/workflow-*.json "$TMP_DEST/workflows/" 2>/dev/null || true

# 3) .env proprio do cliente (segredo local - gitignored via **/.env).
# Valores entre aspas simples: literais no Compose e no shell.
cat > "$TMP_DEST/.env" <<EOF
CLIENT_NAME='$NAME'
CLIENT_NICHE='$NICHE'
ORCHESTRATOR_IMAGE=\${ORCHESTRATOR_IMAGE:-meu-agente-orchestrator:local}
ORCHESTRATOR_HOST_PORT='$PORT'
ORCHESTRATOR_OPENCLAW_GATEWAY_URL='http://openclaw-gateway:18789'
ORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN=''
ORCHESTRATOR_N8N_URL=''
ORCHESTRATOR_N8N_API_KEY=''
ORCHESTRATOR_ATTENDANT_MODE='atendente'
ORCHESTRATOR_ATTENDANT_OPERATOR_NAME='$OPERATOR_NAME'
ORCHESTRATOR_ATTENDANT_OPERATOR_TO='$OPERATOR_TO'
ORCHESTRATOR_ATTENDANT_CHANNEL='$CHANNEL'
ASKMAX_OPERATOR_NAME='$OPERATOR_NAME'
ASKMAX_OPERATOR_TO='$OPERATOR_TO'
ASKMAX_CHANNEL='$CHANNEL'
EOF
chmod 600 "$TMP_DEST/.env"

# 4) docker-compose.yml do cliente (orquestrador dedicado, mesma base canonica).
SLUG="$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-')"
cat > "$TMP_DEST/docker-compose.yml" <<EOF
# Ambiente do cliente $NAME (nicho: $NICHE). Gerado por scripts/provision-client.sh.
# Sobe um orquestrador dedicado ao cliente na rede compartilhada meu-agente-net.
# Uso (a partir desta pasta): docker compose up -d --build
services:
  orchestrator-$SLUG:
    build: ../../orchestrator
    image: \${ORCHESTRATOR_IMAGE:-meu-agente-orchestrator:local}
    container_name: orchestrator-$SLUG
    env_file:
      - path: .env
        required: true
    volumes:
      - ./data:/app/data
    ports:
      - "127.0.0.1:\${ORCHESTRATOR_HOST_PORT:-$PORT}:8000"
    networks:
      - meu-agente-net
    restart: unless-stopped

networks:
  meu-agente-net:
    name: meu-agente-net
    external: true
EOF

if [ "$FORCE" = "1" ] && [ -e "$DEST" ]; then
  # Substituicao atomica: DEST vai para um backup temporario antes do mv
  # final; o backup so e removido apos o sucesso da movimentacao. Se o mv
  # final falhar, o backup e restaurado para nao perder o destino original.
  BACKUP_DEST="$(mktemp -d "$DEPLOYMENTS_DIR/.${NAME}.tmp.backup.XXXXXX")"
  rmdir "$BACKUP_DEST"
  mv -T "$DEST" "$BACKUP_DEST"
  if mv -T "$TMP_DEST" "$DEST"; then
    TMP_DEST=""
    rm -rf -- "$BACKUP_DEST"
    BACKUP_DEST=""
  else
    status=$?
    mv -T "$BACKUP_DEST" "$DEST"
    echo "erro: falha ao substituir $DEST" >&2
    exit "$status"
  fi
else
  mv -T "$TMP_DEST" "$DEST"
  TMP_DEST=""
fi

echo "ok: cliente '$NAME' provisionado em deployments/$NAME/ (nicho: $NICHE)"
ls -R "$DEST"
