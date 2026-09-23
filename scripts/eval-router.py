#!/usr/bin/env python3
"""Smoke test/eval leve contra o orchestrator REAL rodando (nao mocka nada -
roda o LLM de verdade via OpenRouter, custa chamadas de API reais).

Escopo deliberadamente estreito: so verifica comportamento observavel via a
API publica que NAO depende do julgamento probabilistico do LLM de
roteamento (ex.: "ele decide chamar o especialista cybersec pra esta frase
especifica?" - isso e nao-deterministico por natureza de LLM, e ja coberto
de forma deterministica pela suite de testes com LLM mockado, ver
orchestrator/tests/test_graph_e2e_cybersec_guard.py e afins). Aqui o
objetivo e pegar regressoes de INFRAESTRUTURA/ESTADO do orquestrador em si -
o tipo de bug que so aparece rodando contra o servico de verdade.

Uso:
    python3 scripts/eval-router.py --url http://127.0.0.1:8000
    (com autenticacao: --token $ORCHESTRATOR_API_TOKEN ou env ORCHESTRATOR_API_TOKEN)
    (rodar de dentro do host/container onde a porta 8000 e alcancavel -
    ela nao e exposta publicamente por design)
"""

import argparse
import json
import os
import sys
import uuid

import httpx


def check_health(base_url: str) -> bool:
    try:
        response = httpx.get(f"{base_url}/health", timeout=10)
    except httpx.HTTPError as exc:
        print(f"[health] FALHOU: erro de rede - {exc}")
        return False
    except Exception as exc:
        print(f"[health] FALHOU: erro de rede - {exc}")
        return False
    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"[health] FALHOU - {response.status_code} resposta nao-JSON - {exc}")
        return False
    ok = response.status_code == 200 and isinstance(data, dict) and data.get("status") == "ok"
    print(f"[health] {'OK' if ok else 'FALHOU'} - {response.status_code} {response.text}")
    return ok


def build_auth_headers(token: str | None) -> dict:
    """Header de autenticacao do orquestrador: usa ORCHESTRATOR_API_TOKEN
    (via --token ou env) como `Authorization: Bearer <token>`. Sem token,
    retorna dict vazio (serve o modo dev sem autenticacao)."""
    resolved = (token or os.environ.get("ORCHESTRATOR_API_TOKEN") or "").strip()
    if not resolved:
        return {}
    return {"Authorization": f"Bearer {resolved}"}


def check_multiturn_stability(base_url: str, turns: int, headers: dict | None = None) -> bool:
    """Regressao do bug critico de producao encontrado em 2026-08-24 (ver
    docs/ESTADO_ATUAL.md): a N-esima mensagem numa mesma conversa nunca
    pode virar a mensagem de abort por limite de iteracoes - isso ja
    aconteceu de verdade (a partir da 5a mensagem, permanentemente, ate o
    fix de graph/state.py:fresh_turn_input)."""
    session_key = f"eval-router-multiturn-{uuid.uuid4().hex[:8]}"
    for i in range(turns):
        payload = {
            "session_key": session_key,
            "text": f"mensagem de teste numero {i}, so responda ola",
            "from": "eval-router",
        }
        try:
            response = httpx.post(f"{base_url}/v1/turn", json=payload, headers=headers or {}, timeout=90)
        except httpx.HTTPError as exc:
            print(f"[multiturn] FALHOU no turno {i}: erro de rede - {exc}")
            return False
        if response.status_code != 200:
            print(f"[multiturn] FALHOU no turno {i}: HTTP {response.status_code} - {response.text}")
            return False
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"[multiturn] FALHOU no turno {i}: resposta nao-JSON - {exc}")
            return False
        if not isinstance(data, dict):
            print(f"[multiturn] FALHOU no turno {i}: payload inesperado - {response.text}")
            return False
        raw_reply = data.get("reply_text")
        reply = str(raw_reply or "").strip()
        if not reply:
            print(f"[multiturn] FALHOU no turno {i}: resposta vazia - {response.text}")
            return False
        if "limite de iteracoes" in reply.lower() or "ficou complexa demais" in reply.lower():
            print(f"[multiturn] FALHOU no turno {i}: {reply}")
            return False
        print(f"[multiturn] turno {i}: OK ({reply[:60]!r})")
    print(f"[multiturn] OK - {turns} mensagens seguidas na mesma conversa, sem abort")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL do orchestrator")
    parser.add_argument("--turns", type=int, default=6, help="Quantas mensagens simular na mesma conversa")
    parser.add_argument(
        "--token",
        default=None,
        help="Token de autenticacao (Authorization: Bearer). Default: env ORCHESTRATOR_API_TOKEN.",
    )
    args = parser.parse_args()
    headers = build_auth_headers(args.token)

    results = {
        "health": check_health(args.url),
        "multiturn_stability": check_multiturn_stability(args.url, args.turns, headers),
    }

    print("\n=== resumo ===")
    all_ok = True
    for name, ok in results.items():
        print(f"{name}: {'OK' if ok else 'FALHOU'}")
        all_ok = all_ok and ok

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
