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
if ! printf '%s' "$NAME" | grep -Eq '^[A-Za-z0-9_-]+$'; then
  echo "erro: --name deve conter so letras, numeros, '-' e '_' (recebido: $NAME)" >&2
  exit 1
fi

# Nicho precisa existir como template.
if [ ! -d "$TEMPLATES_DIR/$NICHE" ]; then
  echo "erro: nicho desconhecido: $NICHE" >&2; usage >&2; exit 1
fi
[ -f "$TEMPLATES_DIR/$NICHE/AGENTS.md" ] || { echo "erro: template sem AGENTS.md: $NICHE" >&2; exit 1; }

# Porta numerica valida.
if ! printf '%s' "$PORT" | grep -Eq '^[0-9]+$' || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "erro: --port invalida: $PORT" >&2; exit 1
fi

DEST="$DEPLOYMENTS_DIR/$NAME"
if [ -e "$DEST" ] && [ "$FORCE" -ne 1 ]; then
  echo "erro: $DEST ja existe (use --force para recriar)" >&2; exit 1
fi
rm -rf "$DEST"
mkdir -p "$DEST/workflows"

# 1) AGENTS.md customizado a partir do template do nicho.
# Substituicao literal via python3 (str.replace): segura contra '&', '/',
# barras invertidas, aspas e acentos que quebrariam o 'sed'.
python3 -c '
import sys
src, dst, name, op_name, op_to, channel = sys.argv[1:7]
with open(src, encoding="utf-8") as f:
    text = f.read()
text = text.replace("[NOME_DA_CLINICA]", name)
text = text.replace("[NOME_DA_EMPRESA]", name)
text = text.replace("[OPERADOR_NOME]", op_name)
text = text.replace("[OPERADOR_NUMERO]", op_to)
text = text.replace("[CANAL]", channel)
with open(dst, "w", encoding="utf-8") as f:
    f.write(text)
' "$TEMPLATES_DIR/$NICHE/AGENTS.md" "$DEST/AGENTS.md" "$NAME" "$OPERATOR_NAME" "$OPERATOR_TO" "$CHANNEL"

# 2) Workflow(s) n8n de exemplo do nicho.
cp "$TEMPLATES_DIR/$NICHE"/workflow-*.json "$DEST/workflows/" 2>/dev/null || true

# 3) .env proprio do cliente (segredo local - gitignored via **/.env).
cat > "$DEST/.env" <<EOF
# Ambiente do cliente $NAME (nicho: $NICHE). Gerado por scripts/provision-client.sh.
# Nao commitar - arquivo local com segredos.
CLIENT_NAME=$NAME
CLIENT_NICHE=$NICHE
ORCHESTRATOR_IMAGE=\${ORCHESTRATOR_IMAGE:-meu-agente-orchestrator:local}
ORCHESTRATOR_HOST_PORT=$PORT
ORCHESTRATOR_OPENCLAW_GATEWAY_URL=http://openclaw-gateway:18789
ORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN=
ORCHESTRATOR_N8N_URL=
ORCHESTRATOR_N8N_API_KEY=
ORCHESTRATOR_ATTENDANT_MODE=atendente
ORCHESTRATOR_ATTENDANT_OPERATOR_NAME=$OPERATOR_NAME
ORCHESTRATOR_ATTENDANT_OPERATOR_TO=$OPERATOR_TO
ORCHESTRATOR_ATTENDANT_CHANNEL=$CHANNEL
ASKMAX_OPERATOR_NAME=$OPERATOR_NAME
ASKMAX_OPERATOR_TO=$OPERATOR_TO
ASKMAX_CHANNEL=$CHANNEL
EOF

# 4) docker-compose.yml do cliente (orquestrador dedicado, mesma base canonica).
SLUG="$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-')"
cat > "$DEST/docker-compose.yml" <<EOF
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
mkdir -p "$DEST/data"

echo "ok: cliente '$NAME' provisionado em deployments/$NAME/ (nicho: $NICHE)"
ls -R "$DEST"
