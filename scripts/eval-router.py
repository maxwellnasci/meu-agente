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
    (rodar de dentro do host/container onde a porta 8000 e alcancavel -
    ela nao e exposta publicamente por design)
"""

import argparse
import sys
import uuid

import httpx


def check_health(base_url: str) -> bool:
    response = httpx.get(f"{base_url}/health", timeout=10)
    ok = response.status_code == 200 and response.json().get("status") == "ok"
    print(f"[health] {'OK' if ok else 'FALHOU'} - {response.status_code} {response.text}")
    return ok


def check_multiturn_stability(base_url: str, turns: int) -> bool:
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
        response = httpx.post(f"{base_url}/v1/turn", json=payload, timeout=90)
        reply = response.json().get("reply_text", "")
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
    args = parser.parse_args()

    results = {
        "health": check_health(args.url),
        "multiturn_stability": check_multiturn_stability(args.url, args.turns),
    }

    print("\n=== resumo ===")
    all_ok = True
    for name, ok in results.items():
        print(f"{name}: {'OK' if ok else 'FALHOU'}")
        all_ok = all_ok and ok

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
