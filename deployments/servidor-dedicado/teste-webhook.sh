#!/usr/bin/env bash
#
# teste-webhook.sh — Simula webhook da WhatsApp Cloud API para o gateway OpenClaw
#
# Não requer túnel nem Meta: calcula o HMAC-SHA256 (X-Hub-Signature-256)
# diretamente dentro do container do gateway usando o WHATSAPP_CLOUD_APP_SECRET
# já presente no ambiente, e dispara a chamada pela rede interna.
#
# Uso:
#   ./teste-webhook.sh [projeto]                               # Assinatura válida
#   ./teste-webhook.sh [projeto] --invalid-sig                 # Assinatura inválida
#   ./teste-webhook.sh [projeto] --permitir-chamadas-reais     # Ignora trava de teste
#   ./teste-webhook.sh [projeto] "Mensagem custom"
#
set -euo pipefail

PROJETO="teste-molde1"
INVALID_SIG=0
PERMITIR_REAIS=0
TEXTO="Olá, teste de integração do Amigão"

# Processa argumentos
for arg in "$@"; do
  case "$arg" in
    --invalid-sig)
      INVALID_SIG=1
      ;;
    --permitir-chamadas-reais)
      PERMITIR_REAIS=1
      ;;
    -*)
      echo "Opção desconhecida: $arg" >&2
      exit 1
      ;;
    *)
      if [ "$PROJETO" = "teste-molde1" ] && [ "$arg" != "teste-molde1" ]; then
        PROJETO="$arg"
      else
        TEXTO="$arg"
      fi
      ;;
  esac
done

# Localiza containers do projeto
GW_CID=$(docker ps -q --filter "label=com.docker.compose.project=$PROJETO" --filter "label=com.docker.compose.service=openclaw-gateway" | head -1)
if [ -z "$GW_CID" ]; then
  GW_CID=$(docker ps -q --filter "name=${PROJETO}.*gateway" | head -1)
fi

if [ -z "$GW_CID" ]; then
  echo "❌ Container do gateway não encontrado para o projeto $PROJETO" >&2
  exit 1
fi

ORCH_CID=$(docker ps -q --filter "label=com.docker.compose.project=$PROJETO" --filter "label=com.docker.compose.service=orchestrator" | head -1)
if [ -z "$ORCH_CID" ]; then
  ORCH_CID=$(docker ps -q --filter "name=${PROJETO}.*orchestrator" | head -1)
fi

# ---------------------------------------------------------------------
# Trava de Segurança (Fail-Closed): verifica credenciais antes de envio válido
# Apenas exigida para assinatura válida (que dispara o pipeline do LLM).
# ---------------------------------------------------------------------
if [ "$INVALID_SIG" -eq 0 ] && [ "$PERMITIR_REAIS" -eq 0 ]; then
  # 1. Se orquestrador não for encontrado, falha fechado imediatamente
  if [ -z "$ORCH_CID" ]; then
    printf '❌ Trava de segurança: container do orquestrador não encontrado para "%s". Abortando envio.\n' "$PROJETO" >&2
    exit 1
  fi

  # Simulação forçada de credencial real para teste automatizado
  if [ "${TESTE_WEBHOOK_SIMULAR_REAL:-0}" = "1" ]; then
    printf '❌ Trava de segurança: credenciais não parecem de teste (TESTE_WEBHOOK_SIMULAR_REAL=1). Variável bloqueada: WHATSAPP_CLOUD_ACCESS_TOKEN. Use --permitir-chamadas-reais para forçar.\n' >&2
    exit 1
  fi

  # 2. Inspeciona variáveis do gateway que terminam em API_KEY ou ACCESS_TOKEN
  gw_check=$(docker exec "$GW_CID" node -e "
try {
  const vars = Object.keys(process.env).filter(k => k.endsWith('API_KEY') || k.endsWith('ACCESS_TOKEN'));
  const blocked = [];
  for (const k of vars) {
    const v = (process.env[k] || '').trim();
    if (v && !v.toLowerCase().startsWith('teste')) {
      blocked.push(k);
    }
  }
  console.log(JSON.stringify({ ok: true, checked: vars, blocked }));
} catch (e) {
  console.log(JSON.stringify({ ok: false, error: e.message }));
}
" 2>/dev/null || echo '{"ok":false}')

  gw_ok=$(echo "$gw_check" | python3 -c "import sys, json; d=json.loads(sys.stdin.read()); print('1' if d.get('ok') and not d.get('blocked') else '0')" 2>/dev/null || echo "0")
  gw_blocked=$(echo "$gw_check" | python3 -c "import sys, json; print(', '.join(json.loads(sys.stdin.read()).get('blocked', [])))" 2>/dev/null || echo "")

  if [ "$gw_ok" != "1" ]; then
    if [ -n "$gw_blocked" ]; then
      printf '❌ Trava de segurança: variável(is) no gateway não parecem de teste: %s. Use --permitir-chamadas-reais para forçar.\n' "$gw_blocked" >&2
    else
      printf '❌ Trava de segurança: falha ao inspecionar variáveis do gateway. Abortando envio (fail-closed).\n' >&2
    fi
    exit 1
  fi

  # 3. Inspeciona variáveis do orquestrador que terminam em API_KEY ou ACCESS_TOKEN
  orch_check=$(docker exec "$ORCH_CID" python3 -c "
import os, json
try:
    vars = [k for k in os.environ if k.endswith('API_KEY') or k.endswith('ACCESS_TOKEN')]
    blocked = []
    for k in vars:
        v = os.environ[k].strip()
        if v and not v.lower().startswith('teste'):
            blocked.append(k)
    print(json.dumps({'ok': True, 'checked': vars, 'blocked': blocked}))
except Exception as e:
    print(json.dumps({'ok': False, 'error': str(e)}))
" 2>/dev/null || echo '{"ok":false}')

  orch_ok=$(echo "$orch_check" | python3 -c "import sys, json; d=json.loads(sys.stdin.read()); print('1' if d.get('ok') and not d.get('blocked') else '0')" 2>/dev/null || echo "0")
  orch_blocked=$(echo "$orch_check" | python3 -c "import sys, json; print(', '.join(json.loads(sys.stdin.read()).get('blocked', [])))" 2>/dev/null || echo "")

  if [ "$orch_ok" != "1" ]; then
    if [ -n "$orch_blocked" ]; then
      printf '❌ Trava de segurança: variável(is) no orquestrador não parecem de teste: %s. Use --permitir-chamadas-reais para forçar.\n' "$orch_blocked" >&2
    else
      printf '❌ Trava de segurança: falha ao inspecionar variáveis do orquestrador. Abortando envio (fail-closed).\n' >&2
    fi
    exit 1
  fi
fi

# Gera ID de mensagem aleatório e número de telefone reservado para ficção (12025550142)
MSG_RAND=$(openssl rand -hex 8)
MSG_ID="wamid.${MSG_RAND}"
FROM_PHONE="12025550142"

# Executa dentro do container do gateway para calcular HMAC e enviar POST
RESULT=$(docker exec -e INVALID_SIG="$INVALID_SIG" -e MSG_ID="$MSG_ID" -e FROM_PHONE="$FROM_PHONE" -e MSG_BODY="$TEXTO" "$GW_CID" node -e "
const crypto = require('crypto');
const fs = require('fs');

let phoneId = process.env.WHATSAPP_CLOUD_PHONE_NUMBER_ID;
if (!phoneId) {
  try {
    const raw = fs.readFileSync('/home/node/.openclaw/openclaw.json', 'utf8');
    const cfg = JSON.parse(raw);
    phoneId = cfg.channels?.['whatsapp-cloud']?.phoneNumberId;
  } catch (e) {}
}
phoneId = phoneId || '100000000000001';

const appSecret = process.env.WHATSAPP_CLOUD_APP_SECRET || '';

const payloadObj = {
  object: 'whatsapp_business_account',
  entry: [{
    id: 'WHATSAPP_BUSINESS_ACCOUNT_ID',
    changes: [{
      value: {
        messaging_product: 'whatsapp',
        metadata: {
          display_phone_number: '15550254567',
          phone_number_id: phoneId,
        },
        contacts: [{
          profile: { name: 'Cliente Ficticio' },
          wa_id: process.env.FROM_PHONE,
        }],
        messages: [{
          from: process.env.FROM_PHONE,
          id: process.env.MSG_ID,
          timestamp: Math.floor(Date.now() / 1000).toString(),
          text: { body: process.env.MSG_BODY },
          type: 'text',
        }],
      },
      field: 'messages',
    }],
  }],
};

const payloadStr = JSON.stringify(payloadObj);

let sig = '';
if (process.env.INVALID_SIG === '1') {
  sig = 'sha256=0000000000000000000000000000000000000000000000000000000000000000';
} else {
  const hmac = crypto.createHmac('sha256', appSecret).update(payloadStr).digest('hex');
  sig = 'sha256=' + hmac;
}

fetch('http://127.0.0.1:18789/webhook/whatsapp-cloud', {
  method: 'POST',
  headers: {
    'content-type': 'application/json',
    'x-hub-signature-256': sig,
  },
  body: payloadStr,
}).then(async res => {
  const text = await res.text().catch(() => '');
  console.log(JSON.stringify({ status: res.status, ok: res.ok, body: text }));
}).catch(err => {
  console.log(JSON.stringify({ error: err.message }));
});
")

STATUS=$(echo "$RESULT" | python3 -c "import sys, json; print(json.loads(sys.stdin.read()).get('status', 'erro'))" 2>/dev/null || echo "erro")

if [ "$INVALID_SIG" -eq 1 ]; then
  if [[ "$STATUS" =~ ^4 ]]; then
    printf '✅ Assinatura inválida rejeitada pelo gateway com HTTP %s\n' "$STATUS"
    exit 0
  else
    printf '❌ Gateway aceitou assinatura inválida com HTTP %s (esperado 4xx)\n' "$STATUS"
    exit 1
  fi
else
  if [[ "$STATUS" =~ ^2 ]]; then
    printf '✅ Webhook aceito pelo gateway com HTTP %s\n' "$STATUS"
    exit 0
  else
    printf '❌ Webhook recusado pelo gateway com HTTP %s (esperado 2xx)\n' "$STATUS"
    exit 1
  fi
fi
