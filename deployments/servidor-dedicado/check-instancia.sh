#!/usr/bin/env bash
#
# check-instancia.sh — Validação pós-deploy do Servidor Dedicado
#
# Uso:
#   ./check-instancia.sh [nome-do-projeto-docker] [--cliente]
#   ./check-instancia.sh --test-unit
#
# Exemplo:
#   ./check-instancia.sh teste-molde1
#   ./check-instancia.sh teste-molde1 --cliente
#   CHECK_TOKEN_OVERRIDE="errado" ./check-instancia.sh teste-molde1
#
set -euo pipefail

PROJETO="teste-molde1"
MODO_CLIENTE=0
FALHAS=0

OK="✅"
FAIL="❌"

# Função única e testável para validação de status de container
validar_status_saude() {
  local status_str="$1"
  if [[ "$status_str" =~ unhealthy ]] || [[ "$status_str" =~ restarting ]] || [[ "$status_str" =~ dead ]]; then
    return 1
  fi
  if [[ "$status_str" =~ \(healthy\) ]] || [ "$status_str" = "healthy" ]; then
    return 0
  fi
  if [[ "$status_str" =~ ^running ]] || [[ "$status_str" =~ ^Up ]]; then
    if [[ "$status_str" =~ \(starting\) ]]; then
      return 1
    fi
    return 0
  fi
  return 1
}

# Modo de teste unitário da função de saúde
if [ "${1:-}" = "--test-unit" ]; then
  t1="Up 2 minutes (healthy)"
  t2="Up 2 minutes (unhealthy)"
  res1="FALHA"
  res2="OK"
  validar_status_saude "$t1" && res1="OK"
  validar_status_saude "$t2" || res2="FALHA"
  echo "Teste '$t1': $res1"
  echo "Teste '$t2': $res2"
  [ "$res1" = "OK" ] && [ "$res2" = "FALHA" ] && exit 0 || exit 1
fi

# Parsing de argumentos
for arg in "$@"; do
  case "$arg" in
    --cliente)
      MODO_CLIENTE=1
      ;;
    *)
      PROJETO="$arg"
      ;;
  esac
done

# Localiza containers do projeto
GW_CID=$(docker ps -q --filter "label=com.docker.compose.project=$PROJETO" --filter "label=com.docker.compose.service=openclaw-gateway" | head -1)
if [ -z "$GW_CID" ]; then
  GW_CID=$(docker ps -q --filter "name=${PROJETO}.*gateway" | head -1)
fi

ORCH_CID=$(docker ps -q --filter "label=com.docker.compose.project=$PROJETO" --filter "label=com.docker.compose.service=orchestrator" | head -1)
if [ -z "$ORCH_CID" ]; then
  ORCH_CID=$(docker ps -q --filter "name=${PROJETO}.*orchestrator" | head -1)
fi

# ---------------------------------------------------------------------
# a) Containers do gateway e do orquestrador estão Up/healthy
#    Usa estritamente a função validar_status_saude.
# ---------------------------------------------------------------------
check_a() {
  if [ -z "$GW_CID" ] || [ -z "$ORCH_CID" ]; then
    printf '%s Containers do gateway e/ou orquestrador não encontrados para o projeto "%s"\n' "$FAIL" "$PROJETO"
    FALHAS=$((FALHAS + 1))
    return
  fi

  local gw_status orch_status
  gw_status=$(docker inspect "$GW_CID" --format '{{.State.Status}}{{if .State.Health}} ({{.State.Health.Status}}){{end}}' 2>/dev/null || echo "not_found")
  orch_status=$(docker inspect "$ORCH_CID" --format '{{.State.Status}}{{if .State.Health}} ({{.State.Health.Status}}){{end}}' 2>/dev/null || echo "not_found")

  local gw_ok=0 orch_ok=0
  validar_status_saude "$gw_status" && gw_ok=1
  validar_status_saude "$orch_status" && orch_ok=1

  if [ "$gw_ok" -eq 1 ] && [ "$orch_ok" -eq 1 ]; then
    printf '%s Containers do gateway e do orquestrador ativos e saudáveis\n' "$OK"
  else
    printf '%s Containers não estão saudáveis (gateway: %s, orquestrador: %s)\n' "$FAIL" "$gw_status" "$orch_status"
    FALHAS=$((FALHAS + 1))
  fi
}

# ---------------------------------------------------------------------
# b) /health do orquestrador = 200
# ---------------------------------------------------------------------
check_b() {
  if [ -z "$ORCH_CID" ]; then
    printf '%s /health do orquestrador inacessível (container ausente)\n' "$FAIL"
    FALHAS=$((FALHAS + 1))
    return
  fi

  local code
  code=$(docker exec "$ORCH_CID" python3 -c "
import urllib.request, sys
try:
    c = urllib.request.urlopen('http://127.0.0.1:8000/health').getcode()
    print(c)
except Exception:
    print('err')
" 2>/dev/null || echo "err")

  if [ "$code" = "200" ]; then
    printf '%s /health do orquestrador retornou 200\n' "$OK"
  else
    printf '%s /health do orquestrador falhou (código: %s)\n' "$FAIL" "$code"
    FALHAS=$((FALHAS + 1))
  fi
}

# ---------------------------------------------------------------------
# c) ORCHESTRATOR_API_TOKEN CARREGADO no gateway e no orquestrador, com
#    sha256 IGUAL nos dois (nunca imprimir valor nem hash)
# ---------------------------------------------------------------------
check_c() {
  if [ -z "$GW_CID" ] || [ -z "$ORCH_CID" ]; then
    printf '%s Verificação de token impossível (containers ausentes)\n' "$FAIL"
    FALHAS=$((FALHAS + 1))
    return
  fi

  local h_orch h_gw
  h_orch=$(docker exec "$ORCH_CID" python3 -c "
import os, hashlib, sys
t = os.environ.get('ORCHESTRATOR_API_TOKEN', '')
if not t:
    sys.exit(1)
print(hashlib.sha256(t.encode('utf-8')).hexdigest())
" 2>/dev/null || true)

  h_gw=$(docker exec "$GW_CID" node -e "
const crypto = require('crypto');
const t = process.env.ORCHESTRATOR_API_TOKEN || '';
if (!t) process.exit(1);
console.log(crypto.createHash('sha256').update(t).digest('hex'));
" 2>/dev/null || true)

  if [ -n "$h_orch" ] && [ -n "$h_gw" ] && [ "$h_orch" = "$h_gw" ]; then
    printf '%s ORCHESTRATOR_API_TOKEN carregado e idêntico nos dois containers\n' "$OK"
  else
    printf '%s ORCHESTRATOR_API_TOKEN ausente ou divergente entre gateway e orquestrador\n' "$FAIL"
    FALHAS=$((FALHAS + 1))
  fi
  unset h_orch h_gw
}

# ---------------------------------------------------------------------
# d) POST /v1/turn sem token = 401; com token e corpo inválido = 422
#    Usa corpo propositalmente inválido para NUNCA chamar modelo de IA.
# ---------------------------------------------------------------------
check_d() {
  if [ -z "$ORCH_CID" ]; then
    printf '%s Teste de POST /v1/turn impossível (orquestrador ausente)\n' "$FAIL"
    FALHAS=$((FALHAS + 1))
    return
  fi

  local res
  res=$(docker exec -e CHECK_TOKEN_OVERRIDE="${CHECK_TOKEN_OVERRIDE:-}" "$ORCH_CID" python3 -c "
import urllib.request, urllib.error, json, os, sys

def call(token, body):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request('http://127.0.0.1:8000/v1/turn', data=body.encode('utf-8'), headers=headers)
    try:
        r = urllib.request.urlopen(req)
        return r.getcode()
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0

# Teste 1: sem token (esperado 401)
c_no_token = call(None, '{}')

# Teste 2: com token e corpo propositalmente inválido (esperado 422)
tok = os.environ.get('CHECK_TOKEN_OVERRIDE') or os.environ.get('ORCHESTRATOR_API_TOKEN', '')
c_with_token = call(tok, json.dumps({'corpo_invalido_teste_auth': True}))

print(f'{c_no_token}:{c_with_token}')
" 2>/dev/null || echo "err:err")

  if [ "$res" = "401:422" ]; then
    printf '%s POST /v1/turn sem token = 401 e com token + corpo inválido = 422\n' "$OK"
  else
    printf '%s POST /v1/turn validação falhou (obtido: %s, esperado: 401:422)\n' "$FAIL" "$res"
    FALHAS=$((FALHAS + 1))
  fi
}

# ---------------------------------------------------------------------
# e) Nenhuma porta publicada fora de 127.0.0.1
# ---------------------------------------------------------------------
check_e() {
  local bad_ports=0
  local all_cids
  all_cids=$(docker ps -q --filter "label=com.docker.compose.project=$PROJETO")

  for cid in $all_cids; do
    local ports_json
    ports_json=$(docker inspect "$cid" --format '{{json .NetworkSettings.Ports}}' 2>/dev/null || echo "{}")
    local is_bad
    is_bad=$(python3 -c "
import json, sys
try:
    data = json.loads('''$ports_json''')
    bad = False
    if data:
        for p, bindings in data.items():
            if bindings:
                for b in bindings:
                    ip = b.get('HostIp', '')
                    if ip not in ('127.0.0.1', 'localhost', '::1') and ip != '':
                        bad = True
    print('1' if bad else '0')
except Exception:
    print('0')
")
    if [ "$is_bad" = "1" ]; then
      bad_ports=$((bad_ports + 1))
    fi
  done

  if [ "$bad_ports" -eq 0 ]; then
    printf '%s Nenhuma porta publicada fora de 127.0.0.1\n' "$OK"
  else
    printf '%s Encontradas portas publicadas em interfaces públicas/0.0.0.0\n' "$FAIL"
    FALHAS=$((FALHAS + 1))
  fi
}

# ---------------------------------------------------------------------
# f) Verificação de dmPolicy e allowFrom (Aviso / Falha se --cliente)
#    Lê diretamente de /home/node/.openclaw/openclaw.json no container.
# ---------------------------------------------------------------------
check_f() {
  if [ -z "$GW_CID" ]; then
    return
  fi

  local policy_info
  policy_info=$(docker exec "$GW_CID" node -e "
const fs = require('fs');
try {
  const cfg = JSON.parse(fs.readFileSync('/home/node/.openclaw/openclaw.json', 'utf8'));
  const wc = cfg.channels?.['whatsapp-cloud'] || {};
  console.log(JSON.stringify({
    dmPolicy: wc.dmPolicy || 'unknown',
    allowFrom: wc.allowFrom || []
  }));
} catch (e) {
  console.log(JSON.stringify({ error: e.message }));
}
" 2>/dev/null || echo "{}")

  local is_open
  is_open=$(python3 -c "
import json, sys
try:
    d = json.loads('''$policy_info''')
    policy = d.get('dmPolicy', '')
    allow = d.get('allowFrom', [])
    if policy == 'open' and '*' in allow:
        print('OPEN')
    else:
        print('RESTRICTED')
except Exception:
    print('UNKNOWN')
" 2>/dev/null || echo "UNKNOWN")

  if [ "$is_open" = "OPEN" ]; then
    if [ "$MODO_CLIENTE" -eq 1 ]; then
      printf '%s Política aberta em ambiente de cliente: dmPolicy=open e allowFrom=[\"*\"] (qualquer número será atendido e gasta a conta de IA)\n' "$FAIL"
      FALHAS=$((FALHAS + 1))
    else
      printf '⚠️  Política aberta: dmPolicy=open e allowFrom=[\"*\"] (qualquer número será atendido e gasta a conta de IA)\n'
    fi
  else
    printf '%s Política de acesso restrita configurada no gateway\n' "$OK"
  fi
}

check_a
check_b
check_c
check_d
check_e
check_f

if [ "$FALHAS" -eq 0 ]; then
  echo "INSTÂNCIA OK"
  exit 0
else
  echo "INSTÂNCIA COM PROBLEMA ($FALHAS falhas)"
  exit 1
fi
