#!/usr/bin/env bash
#
# Molde 1 (Kit Agente Essencial) e Molde 2 (+ n8n/Postgres) — bootstrap de
# VPS virgem para o Servidor Dedicado.
#
# Prepara o diretório de deploy para o primeiro `docker compose up -d`:
# cria os bind mounts com dono correto (UID 1000), inicializa `.env` e
# `openclaw/openclaw.json` a partir dos modelos versionados e valida a
# sintaxe do compose escolhido. No Molde 2, também cria e ajusta o dono de
# `n8n/` (bind mount do n8n, que roda como UID 1000 dentro do container).
#
# IDEMPOTENTE: rodar de novo nunca sobrescreve `.env` nem
# `openclaw/openclaw.json` já existentes — só reforça permissões.
#
#   ./bootstrap.sh            # Molde 1 (default)
#   ./bootstrap.sh molde1     # Molde 1, explícito
#   ./bootstrap.sh molde2     # Molde 2 (Molde 1 + n8n/Postgres)
#
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MOLDE="${1:-molde1}"
case "$MOLDE" in
  molde1|molde2) ;;
  *)
    printf '\n[ERRO] molde inválido: "%s"\n\nUso:\n  ./bootstrap.sh            # Molde 1 (default)\n  ./bootstrap.sh molde1     # Molde 1, explícito\n  ./bootstrap.sh molde2     # Molde 2 (Molde 1 + n8n/Postgres)\n' "$MOLDE" >&2
    exit 1
    ;;
esac

COMPOSE_FILE="$DIR/docker-compose.$MOLDE.yml"
COMPOSE_BASENAME="$(basename "$COMPOSE_FILE")"
ENV_FILE="$DIR/.env"
ENV_EXAMPLE="$DIR/.env.example"
CONFIG_TEMPLATE="$DIR/openclaw.json.template"
CONFIG_FILE="$DIR/openclaw/openclaw.json"

# Bind mounts comuns aos dois moldes, mais `n8n/` no Molde 2 (o container
# n8n roda como UID 1000 dentro da imagem, igual ao gateway).
BIND_MOUNT_DIRS=("$DIR/openclaw" "$DIR/workspace" "$DIR/data")
[ "$MOLDE" = "molde2" ] && BIND_MOUNT_DIRS+=("$DIR/n8n")

# Marcador do phoneNumberId no template. Ver bloco "Nota" na etapa 5:
# este campo NÃO aceita SecretRef "${VAR}" — precisa de valor literal.
PHONE_PLACEHOLDER="__WHATSAPP_CLOUD_PHONE_NUMBER_ID__"

# Número de exemplo que aparece no comentário do .env.example. Se ele chegar
# ao .env é porque alguém copiou a documentação em vez do número real — não
# serve como valor e é recusado na etapa 5.
PHONE_EXAMPLE="123456789012345"

# Marcador do "to" do plugin ask-max (transbordo humano) no template. Mesmo
# mecanismo do phoneNumberId acima: evita um número de operador padrão
# utilizável no template versionado.
ASK_MAX_TO_PLACEHOLDER="__ASK_MAX_OPERATOR_TO__"

# Número de exemplo que já existiu como default literal em versões antigas
# do .env.example — se sobreviver em um .env copiado de fora, é recusado
# na etapa 5 igual ao PHONE_EXAMPLE.
ASK_MAX_TO_EXAMPLE="5541999999999"

RUNTIME_UID=1000
RUNTIME_GID=1000

info()  { printf '  %s\n' "$*"; }
ok()    { printf '  [ok]    %s\n' "$*"; }
warn()  { printf '  [aviso] %s\n' "$*" >&2; }
step()  { printf '\n==> %s\n' "$*"; }
die()   { printf '\n[ERRO] %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------
# 1. Pré-requisitos do host
# ---------------------------------------------------------------------
step "1/6  Checando pré-requisitos"
info "Molde selecionado: $MOLDE ($COMPOSE_BASENAME)"

if ! command -v docker >/dev/null 2>&1; then
  die "docker não encontrado no PATH.
       Instale com:  curl -fsSL https://get.docker.com | sh"
fi
ok "docker encontrado ($(docker --version 2>/dev/null | head -1))"

if ! docker compose version >/dev/null 2>&1; then
  die "'docker compose' (v2) não encontrado.
       O plugin v2 é obrigatório — 'docker-compose' v1 (com hífen) não serve.
       Instale o pacote docker-compose-plugin da sua distro."
fi
ok "docker compose v2 encontrado ($(docker compose version --short 2>/dev/null))"

[ -f "$COMPOSE_FILE" ]    || die "arquivo não encontrado: $COMPOSE_FILE"
[ -f "$ENV_EXAMPLE" ]     || die "arquivo não encontrado: $ENV_EXAMPLE"
[ -f "$CONFIG_TEMPLATE" ] || die "arquivo não encontrado: $CONFIG_TEMPLATE"
ok "modelos versionados presentes (compose, .env.example, openclaw.json.template)"

# ---------------------------------------------------------------------
# 2. Bind mounts
# ---------------------------------------------------------------------
step "2/6  Criando bind mounts"

mkdir -p "${BIND_MOUNT_DIRS[@]}"
if [ "$MOLDE" = "molde2" ]; then
  ok "diretórios openclaw/ workspace/ data/ n8n/ prontos"
else
  ok "diretórios openclaw/ workspace/ data/ prontos"
fi

# ---------------------------------------------------------------------
# 3. Permissões POSIX
# ---------------------------------------------------------------------
# Os containers rodam como UID 1000. Se o Docker criar estes diretórios
# sozinho eles nascem root:root e o primeiro reply morre com EACCES.
step "3/6  Ajustando dono e permissões dos bind mounts"

chmod 755 "${BIND_MOUNT_DIRS[@]}"

chown_targets() { chown -R "$RUNTIME_UID:$RUNTIME_GID" "${BIND_MOUNT_DIRS[@]}"; }

if [ "$(id -u)" -eq 0 ]; then
  chown_targets
  ok "chown -R $RUNTIME_UID:$RUNTIME_GID aplicado (root)"
elif chown_targets 2>/dev/null; then
  ok "chown -R $RUNTIME_UID:$RUNTIME_GID aplicado (já era o dono)"
elif command -v sudo >/dev/null 2>&1 && sudo -n chown -R "$RUNTIME_UID:$RUNTIME_GID" \
       "${BIND_MOUNT_DIRS[@]}" 2>/dev/null; then
  ok "chown -R $RUNTIME_UID:$RUNTIME_GID aplicado (sudo)"
else
  warn "não foi possível aplicar chown para $RUNTIME_UID:$RUNTIME_GID."
  warn "Se os containers falharem com EACCES, rode manualmente:"
  warn "  sudo chown -R $RUNTIME_UID:$RUNTIME_GID ${BIND_MOUNT_DIRS[*]}"
fi

# ---------------------------------------------------------------------
# 4. .env
# ---------------------------------------------------------------------
step "4/6  Inicializando .env"

if [ -f "$ENV_FILE" ]; then
  chmod 600 "$ENV_FILE"
  ok ".env já existe — preservado integralmente (permissão reforçada para 600)"
else
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok ".env criado a partir de .env.example (600)"
fi

# Lê uma chave do .env sem dar `source` no arquivo (evita execução de
# conteúdo arbitrário vindo de um .env editado à mão).
read_env_value() {
  sed -n "s/^[[:space:]]*$1=//p" "$ENV_FILE" 2>/dev/null \
    | tail -1 \
    | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/" \
    | tr -d '[:space:]'
}

# ---------------------------------------------------------------------
# 5. openclaw.json
# ---------------------------------------------------------------------
# Nota (validado no código do OpenClaw, 2026-09-25):
# channels.whatsapp-cloud.{verifyToken,appSecret,accessToken} passam por
# resolveConfiguredSecretInputString() e aceitam SecretRef de ambiente
# "${VAR}" (src/config/types.secrets.ts, ENV_SECRET_TEMPLATE_RE).
# `phoneNumberId` NÃO: extensions/whatsapp-cloud/src/accounts.ts lê o
# campo cru via String(merged.phoneNumberId ?? "").trim(). Um "${VAR}"
# ali viraria a string literal e o agente morreria em silêncio nos dois
# sentidos (URL do Graph inválida no envio; webhook recusado por
# phone_number_id divergente). Por isso o template traz um marcador
# literal, preenchido aqui a partir do .env.
step "5/6  Inicializando openclaw/openclaw.json"

# Troca o marcador do phoneNumberId em $CONFIG_FILE pelo valor do .env.
# Define $phone_number_id para quem chamar. Retorna 0 se substituiu, 1 se o
# .env ainda não tem um valor utilizável (o aviso de pendência cuida disso).
fill_phone_placeholder() {
  phone_number_id="$(read_env_value WHATSAPP_CLOUD_PHONE_NUMBER_ID)"

  [ -n "$phone_number_id" ] || return 1

  if [ "$phone_number_id" = "$PHONE_EXAMPLE" ]; then
    warn "WHATSAPP_CLOUD_PHONE_NUMBER_ID ainda é o número de exemplo do"
    warn ".env.example ($PHONE_EXAMPLE) — ignorado, use o número real."
    return 1
  fi

  # Só dígitos: é o formato que a Meta emite e evita que metacaractere de
  # um .env editado à mão (/, &, \) escape para o sed abaixo.
  case "$phone_number_id" in
    *[!0-9]*)
      warn "WHATSAPP_CLOUD_PHONE_NUMBER_ID='$phone_number_id' não é só dígitos — ignorado."
      return 1
      ;;
  esac

  tmp_config="$(mktemp)"
  sed "s/$PHONE_PLACEHOLDER/$phone_number_id/g" "$CONFIG_FILE" > "$tmp_config"
  cat "$tmp_config" > "$CONFIG_FILE"   # `cat >` preserva inode e permissão
  rm -f "$tmp_config"
  return 0
}

# Troca o marcador do "to" do ask-max em $CONFIG_FILE pelo valor do .env.
# Mesma lógica de fill_phone_placeholder acima, aplicada ao número do
# operador humano do transbordo (plugins.entries.ask-max.config.to).
fill_ask_max_to_placeholder() {
  ask_max_to="$(read_env_value ORCHESTRATOR_ATTENDANT_OPERATOR_TO)"

  [ -n "$ask_max_to" ] || return 1

  if [ "$ask_max_to" = "$ASK_MAX_TO_EXAMPLE" ]; then
    warn "ORCHESTRATOR_ATTENDANT_OPERATOR_TO ainda é o número de exemplo"
    warn "($ASK_MAX_TO_EXAMPLE) — ignorado, use o número real do operador."
    return 1
  fi

  case "$ask_max_to" in
    *[!0-9]*)
      warn "ORCHESTRATOR_ATTENDANT_OPERATOR_TO='$ask_max_to' não é só dígitos — ignorado."
      return 1
      ;;
  esac

  tmp_config="$(mktemp)"
  sed "s/$ASK_MAX_TO_PLACEHOLDER/$ask_max_to/g" "$CONFIG_FILE" > "$tmp_config"
  cat "$tmp_config" > "$CONFIG_FILE"
  rm -f "$tmp_config"
  return 0
}

if [ -f "$CONFIG_FILE" ]; then
  chmod 600 "$CONFIG_FILE"
  ok "openclaw/openclaw.json já existe — preservado integralmente (permissão reforçada para 600)"

  # Caso típico do 2º run: o 1º run gerou a config antes de o operador
  # preencher o .env, então o marcador ficou no arquivo. Agora que o .env
  # tem o número, resolvemos no lugar — sem exigir apagar o JSON nem editar
  # à mão. Só o marcador é tocado; o resto da config editada é preservado.
  if grep -q "$PHONE_PLACEHOLDER" "$CONFIG_FILE" 2>/dev/null && fill_phone_placeholder; then
    ok "phoneNumberId atualizado no openclaw/openclaw.json existente a partir do .env ($phone_number_id)"
  fi
  if grep -q "$ASK_MAX_TO_PLACEHOLDER" "$CONFIG_FILE" 2>/dev/null && fill_ask_max_to_placeholder; then
    ok "ask-max.config.to atualizado no openclaw/openclaw.json existente a partir do .env ($ask_max_to)"
  fi
else
  cp "$CONFIG_TEMPLATE" "$CONFIG_FILE"

  if fill_phone_placeholder; then
    ok "phoneNumberId preenchido a partir do .env ($phone_number_id)"
  fi
  if fill_ask_max_to_placeholder; then
    ok "ask-max.config.to preenchido a partir do .env ($ask_max_to)"
  fi

  chown "$RUNTIME_UID:$RUNTIME_GID" "$CONFIG_FILE" 2>/dev/null || true
  chmod 600 "$CONFIG_FILE"
  ok "openclaw/openclaw.json criado a partir do template (600)"
fi

# Vale para arquivo novo E para arquivo preservado: os marcadores precisam
# sumir antes de subir, senão a falha é silenciosa (phoneNumberId) ou o
# transbordo humano manda mensagem pro contato literal errado (ask-max.to).
phone_pending=0
if grep -q "$PHONE_PLACEHOLDER" "$CONFIG_FILE" 2>/dev/null; then
  phone_pending=1
  warn "openclaw/openclaw.json ainda contém o marcador $PHONE_PLACEHOLDER."
  warn "Este campo NÃO aceita \${VAR} — precisa do número literal."
fi

ask_max_to_pending=0
if grep -q "$ASK_MAX_TO_PLACEHOLDER" "$CONFIG_FILE" 2>/dev/null; then
  ask_max_to_pending=1
  warn "openclaw/openclaw.json ainda contém o marcador $ASK_MAX_TO_PLACEHOLDER."
  warn "Preencha ORCHESTRATOR_ATTENDANT_OPERATOR_TO no .env antes de subir."
fi

# ---------------------------------------------------------------------
# 6. Sanidade do compose
# ---------------------------------------------------------------------
# TUNNEL_TOKEN e ORCHESTRATOR_API_TOKEN (e, no Molde 2, também
# POSTGRES_PASSWORD/N8N_ENCRYPTION_KEY) são obrigatórios no compose
# (`${VAR:?...}`); aqui usamos valores descartáveis só para checar
# SINTAXE, sem exigir os segredos reais.
step "6/6  Validando sintaxe do $COMPOSE_BASENAME"

CHECK_ENV=(TUNNEL_TOKEN=placeholder_check ORCHESTRATOR_API_TOKEN=placeholder_check)
if [ "$MOLDE" = "molde2" ]; then
  CHECK_ENV+=(POSTGRES_PASSWORD=placeholder_check N8N_ENCRYPTION_KEY=placeholder_check)
fi

if env "${CHECK_ENV[@]}" docker compose -f "$COMPOSE_FILE" config -q 2>/dev/null; then
  ok "sintaxe do compose válida"
else
  die "docker compose config falhou. Saída completa:
$(env "${CHECK_ENV[@]}" docker compose -f "$COMPOSE_FILE" config 2>&1 | tail -20)"
fi

# ---------------------------------------------------------------------
# Instruções finais
# ---------------------------------------------------------------------
cat <<INSTRUCTIONS

========================================================================
Bootstrap concluído (molde: $MOLDE). Próximos passos (manuais):
========================================================================

1. Preencher os segredos do cliente no .env:

     nano $DIR/.env

   Obrigatórios para subir:
     - TUNNEL_TOKEN                          (Cloudflare Zero Trust)
     - WHATSAPP_CLOUD_ACCESS_TOKEN           (System User, permanente)
     - WHATSAPP_CLOUD_PHONE_NUMBER_ID        (só dígitos)
     - WHATSAPP_CLOUD_WEBHOOK_VERIFY_TOKEN   (openssl rand -hex 16)
     - WHATSAPP_CLOUD_APP_SECRET             (App Secret do app Meta)
     - ORCHESTRATOR_OPENROUTER_API_KEY       (https://openrouter.ai/keys)
     - OPENCLAW_GATEWAY_TOKEN                (openssl rand -hex 32)
     - ORCHESTRATOR_API_TOKEN                (openssl rand -hex 32)
     - ORCHESTRATOR_ATTENDANT_OPERATOR_TO    (WhatsApp do operador humano,
                                               só dígitos — transbordo via
                                               ask-max)
INSTRUCTIONS

if [ "$MOLDE" = "molde2" ]; then
  cat <<INSTRUCTIONS
     - POSTGRES_PASSWORD                     (openssl rand -hex 24)
     - N8N_ENCRYPTION_KEY                    (openssl rand -hex 24 — NUNCA
                                               troque depois de criar
                                               credenciais no n8n)
     - N8N_PUBLIC_DOMAIN                     (2º Public Hostname do
                                               Cloudflare Tunnel, ex.:
                                               automacoes.<cliente>.com.br)

   NÃO obrigatório para subir (só existe DEPOIS do 1º boot do n8n — ver
   passo 4 no final):
     - ORCHESTRATOR_N8N_API_KEY
INSTRUCTIONS
fi

cat <<INSTRUCTIONS

2. Ajustar a config do gateway:

     nano $DIR/openclaw/openclaw.json
INSTRUCTIONS

if [ "$phone_pending" -eq 1 ]; then
  cat <<INSTRUCTIONS

   >>> OBRIGATÓRIO: trocar $PHONE_PLACEHOLDER
       pelo WHATSAPP_CLOUD_PHONE_NUMBER_ID literal (só dígitos).
       Diferente dos tokens, este campo não resolve \${VAR}: deixá-lo
       assim faz o agente falhar EM SILÊNCIO (não envia e não recebe).
       Alternativa: preencha o .env e recrie a config com
         rm $DIR/openclaw/openclaw.json && $DIR/bootstrap.sh $MOLDE
INSTRUCTIONS
else
  cat <<INSTRUCTIONS

   (phoneNumberId já preenchido a partir do .env.)
INSTRUCTIONS
fi

cat <<INSTRUCTIONS

   >>> ATENÇÃO — política de acesso ao agente:
       O template sobe com "dmPolicy": "open" e "allowFrom": ["*"], ou
       seja, QUALQUER número que mandar mensagem é atendido. Isso é
       proposital: facilita o teste do handshake e o onboarding rápido
       da empresa, sem travar na allowlist.

       Em produção, se o número for restrito ou de uso interno, troque
       em channels.whatsapp-cloud para allowlist explícita:

         "dmPolicy": "allowlist",
         "allowFrom": ["5541999999999", "5511988887777"]

       (DDI+DDD+número, só dígitos, um item por contato autorizado.)
       Mantendo "open" em um número público, o agente responde a
       desconhecidos e consome LLM com quem você não autorizou.

   Nome/assistente do operador (opcional, sem marcador nem obrigatoriedade):
   plugins.entries.ask-max.config.operatorName/assistantName.
INSTRUCTIONS

if [ "$ask_max_to_pending" -eq 1 ]; then
  cat <<INSTRUCTIONS

   >>> OBRIGATÓRIO: trocar $ASK_MAX_TO_PLACEHOLDER
       pelo ORCHESTRATOR_ATTENDANT_OPERATOR_TO literal (só dígitos) em
       plugins.entries.ask-max.config.to. Deixá-lo assim faz o transbordo
       humano tentar enviar para um contato inexistente.
       Alternativa: preencha o .env e recrie a config com
         rm $DIR/openclaw/openclaw.json && $DIR/bootstrap.sh $MOLDE
INSTRUCTIONS
else
  cat <<INSTRUCTIONS

   (ask-max.config.to já preenchido a partir do .env.)
INSTRUCTIONS
fi

cat <<INSTRUCTIONS

3. Subir a stack:

     cd $DIR && docker compose -f $COMPOSE_BASENAME up -d

   Acompanhar o boot:
     docker compose -f $COMPOSE_BASENAME logs -f
INSTRUCTIONS

if [ "$MOLDE" = "molde2" ]; then
  cat <<INSTRUCTIONS

4. Depois do primeiro boot do n8n (não bloqueia o passo 3 acima):

     Acesse o n8n (hostname de N8N_PUBLIC_DOMAIN, ou http://n8n:5678 de
     dentro da rede automacoes-net), crie o usuário owner e gere uma API key
     em Settings > n8n API > Create an API key.

     Adicione a chave ao .env e recrie só o orquestrador para ele passar
     a enxergar o n8n:

       nano $DIR/.env   # ORCHESTRATOR_N8N_API_KEY=<chave gerada>
       cd $DIR && docker compose -f $COMPOSE_BASENAME up -d orchestrator

     Sem essa chave o boot da stack não é afetado, mas o orquestrador evita
     a chamada ao n8n e não dispara automações até ela ser preenchida.
INSTRUCTIONS
fi

cat <<INSTRUCTIONS

========================================================================
INSTRUCTIONS
