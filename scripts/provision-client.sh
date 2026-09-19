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
#   workflows/ ........ copia do workflow n8n de exemplo do nicho, com
#                       webhooks namespaced pelo slug do cliente
#   data/ ............. estado local (banco checkpoints.sqlite, memorias)
# --force regenera apenas infra/template (AGENTS.md, compose, workflows/)
# e preserva ./data e .env existentes; aborta se a porta estiver em uso.
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
PORT_SET=0
OPERATOR_NAME_SET=0
OPERATOR_TO_SET=0

usage() {
  echo "Uso: $0 --name <NomeCliente> --niche <nicho> [opcoes]"
  echo "Nichos disponiveis: $(ls "$TEMPLATES_DIR" 2>/dev/null | tr '\n' ' ')"
  echo "Opcoes: --operator-name, --operator-to, --channel, --port, --force, --help"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="${2:-}"; shift 2 ;;
    --niche) NICHE="${2:-}"; shift 2 ;;
    --operator-name) OPERATOR_NAME="${2:-}"; OPERATOR_NAME_SET=1; shift 2 ;;
    --operator-to) OPERATOR_TO="${2:-}"; OPERATOR_TO_SET=1; shift 2 ;;
    --channel) CHANNEL="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; PORT_SET=1; shift 2 ;;
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

# Trava de container ativo: re-provisionar com --force com o servico no ar
# destruiria o ambiente em execucao. SLUG calculado aqui pois o calculo
# canonico ocorre apenas mais abaixo no fluxo normal.
if [ "$FORCE" = "1" ] && [ -e "$DEST" ]; then
  _FORCE_SLUG="$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-')"
  if command -v docker >/dev/null 2>&1; then
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "orchestrator-$_FORCE_SLUG"; then
      echo "erro: container 'orchestrator-$_FORCE_SLUG' esta em execucao; pare o servico com 'docker compose down' antes de re-provisionar com --force" >&2
      exit 1
    fi
  fi
fi

# Checagem preventiva de colisao de porta no host: aborta com erro
# informativo em vez de falhar silenciosamente no `docker compose up`.
port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -tln 2>/dev/null | grep -Eq "[:.]${port}([[:space:]]|$)"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1
  else
    python3 -c 'import socket,sys; sys.exit(0 if socket.socket().connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)' "$port"
  fi
}
if port_in_use "$PORT"; then
  echo "erro: porta $PORT ja esta em uso no host (confira com 'ss -tulpn | grep :$PORT'); use --port <porta-livre> ou libere a porta" >&2
  exit 1
fi

# Alerta (sem abortar) se outro deployment ja declara a mesma porta.
for _other_env in "$DEPLOYMENTS_DIR"/*/.env; do
  [ -f "$_other_env" ] || continue
  if [ "$(dirname "$_other_env")" = "$DEST" ]; then
    continue # re-provisionamento do proprio cliente com --force
  fi
  _other_port="$(grep -E "^ORCHESTRATOR_HOST_PORT=" "$_other_env" | head -n 1 | sed -E "s/^[^=]*='?([^']*)'?.*/\1/" || true)"
  if [ -n "${_other_port:-}" ] && [ "$_other_port" = "$PORT" ]; then
    echo "aviso: porta $PORT tambem declarada por $(dirname "$_other_env") (considere --port dedicado por cliente)" >&2
  fi
done

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

# Placeholders de configuracao sem argumento na CLI: marcacao explicita
# para o operador saber o que falta preencher (lista fechada dos slots de
# configuracao dos templates; texto de exemplo como "[ID]" nao e tocado,
# e valores inseridos via argumento nunca sao reprocessados aqui).
PENDENTES = ("ESPECIALIDADES", "CONVENIOS", "ENDERECO_TELEFONE", "SISTEMAS", "PLAYBOOKS")
marcados = []
for slot in PENDENTES:
    token = "[" + slot + "]"
    if token in result:
        result = result.replace(token, "[A PREENCHER: " + slot + "]")
        marcados.append(slot)
if marcados:
    print("aviso: AGENTS.md tem campo(s) a preencher pelo operador: "
          + ", ".join("[A PREENCHER: " + s + "]" for s in marcados),
          file=sys.stderr)

with open(dst, "w", encoding="utf-8") as f:
  f.write(result)
' "$TEMPLATES_DIR/$NICHE/AGENTS.md" "$TMP_DEST/AGENTS.md" "$NAME" "$OPERATOR_NAME" "$OPERATOR_TO" "$CHANNEL"

# Slug do cliente (mesmo usado no compose): identifica o deployment.
SLUG="$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-')"

# 2) Workflow(s) n8n de exemplo do nicho, com namespace do cliente.
# O path de cada webhook ganha o sufixo "-<slug>" para nao colidir quando
# varios clientes compartilham a mesma infraestrutura de automacao.
cp "$TEMPLATES_DIR/$NICHE"/workflow-*.json "$TMP_DEST/workflows/" 2>/dev/null || true
python3 -c '
import glob, json, os, sys

slug, wf_dir = sys.argv[1:3]
for path in sorted(glob.glob(os.path.join(wf_dir, "workflow-*.json"))):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for node in data.get("nodes", []):
        if node.get("type") == "n8n-nodes-base.webhook":
            params = node.setdefault("parameters", {})
            p = params.get("path", "")
            if p and not p.endswith("-" + slug):
                params["path"] = p + "-" + slug
            print("info: webhook '{}' com namespace do cliente".format(params.get("path", "")))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
' "$SLUG" "$TMP_DEST/workflows"

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
# (SLUG calculado no passo 2 e reutilizado aqui.)
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

# Blindagem do --force: re-provisionar regenera apenas infra e template
# (AGENTS.md, docker-compose.yml, workflows/) e NUNCA apaga estado nem
# segredos — ./data (banco checkpoints.sqlite, memorias) e .env existente
# sao copiados para o novo diretorio antes da troca atomica.
if [ "$FORCE" = "1" ] && [ -e "$DEST" ]; then
  if [ -d "$DEST/data" ]; then
    mkdir -p "$TMP_DEST/data"
    cp -a "$DEST/data/." "$TMP_DEST/data/"
    echo "aviso: preservando $DEST/data existente (--force nao apaga memorias/banco)" >&2
  fi
  if [ -f "$DEST/.env" ]; then
    cp -a "$DEST/.env" "$TMP_DEST/.env"
    # Sincronizacao seletiva: segredos preservados, mas chaves de
    # infraestrutura/operador passadas explicitamente na CLI sao atualizadas
    # para manter paridade com docker-compose.yml e AGENTS.md.
    if [ "$PORT_SET" = "1" ]; then
      PORT="$PORT" ENV_FILE="$TMP_DEST/.env" python3 -c '
import os
path = os.environ["ENV_FILE"]
port = os.environ["PORT"]
with open(path, encoding="utf-8") as f:
    lines = f.readlines()
out = []
replaced = False
for line in lines:
    if line.startswith("ORCHESTRATOR_HOST_PORT="):
        out.append("ORCHESTRATOR_HOST_PORT='"'"'%s'"'"'\n" % port)
        replaced = True
    else:
        out.append(line)
if not replaced:
    out.append("ORCHESTRATOR_HOST_PORT='"'"'%s'"'"'\n" % port)
with open(path, "w", encoding="utf-8") as f:
    f.writelines(out)
'
    fi
    if [ "$OPERATOR_TO_SET" = "1" ]; then
      OPERATOR_TO="$OPERATOR_TO" ENV_FILE="$TMP_DEST/.env" python3 -c '
import os
path = os.environ["ENV_FILE"]
val = os.environ["OPERATOR_TO"]
targets = (
    "ORCHESTRATOR_ATTENDANT_OPERATOR_TO",
    "ASKMAX_OPERATOR_TO",
    "ORCHESTRATOR_OPERATOR_PHONE_TO",
)
with open(path, encoding="utf-8") as f:
    lines = f.readlines()
out = []
seen = set()
for line in lines:
    done = False
    for key in targets:
        if line.startswith(key + "="):
            out.append("%s='"'"'%s'"'"'\n" % (key, val))
            seen.add(key)
            done = True
            break
    if not done:
        out.append(line)
with open(path, "w", encoding="utf-8") as f:
    f.writelines(out)
'
    fi
    if [ "$OPERATOR_NAME_SET" = "1" ]; then
      OPERATOR_NAME="$OPERATOR_NAME" ENV_FILE="$TMP_DEST/.env" python3 -c '
import os
path = os.environ["ENV_FILE"]
val = os.environ["OPERATOR_NAME"]
targets = (
    "ORCHESTRATOR_ATTENDANT_OPERATOR_NAME",
    "ASKMAX_OPERATOR_NAME",
    "ORCHESTRATOR_OPERATOR_NAME",
)
with open(path, encoding="utf-8") as f:
    lines = f.readlines()
out = []
for line in lines:
    done = False
    for key in targets:
        if line.startswith(key + "="):
            out.append("%s='"'"'%s'"'"'\n" % (key, val))
            done = True
            break
    if not done:
        out.append(line)
with open(path, "w", encoding="utf-8") as f:
    f.writelines(out)
'
    fi
    chmod 600 "$TMP_DEST/.env"
    echo "aviso: preservando $DEST/.env existente (--force nao sobrescreve segredos; chaves --port/--operator-* passadas na CLI foram sincronizadas)" >&2
  fi
fi

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
