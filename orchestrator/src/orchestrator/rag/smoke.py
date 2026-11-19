"""Smoke test MANUAL: uma pergunta real pelo grafo (supervisor -> rag ->
synthesize_final), com o LLM REAL do OpenRouter. Custa dinheiro: so roda
com `--executar`.

    cd orchestrator
    python -m orchestrator.rag.ingest                       # se ainda nao houver indice
    python -m orchestrator.rag.smoke "pergunta"             # so mostra o plano
    python -m orchestrator.rag.smoke --executar "pergunta"  # roda de verdade

Liga `rag_enabled` so no proprio processo (o padrao e desligado).

Isolamento: le a chave do OpenRouter do `orchestrator/.env` (cwd), mas
NEUTRALIZA os especialistas com efeito externo direto no `settings`: n8n
sem URL (o no aborta sem chamar a API) e gateway do OpenClaw/cybersec num
host `.invalid` sem token (um roteamento errado falha sem tocar nada).
Estado em MemorySaver (nunca o data/checkpoints.sqlite).
"""

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

_GATEWAY_NEUTRO = "http://openclaw-gateway.smoke.invalid:1"


def neutralizar_efeitos_externos(settings) -> None:
    """Desliga, no `settings` global, todo especialista com efeito externo.
    Os clientes (N8nClient, OpenClawClient) leem o settings na hora da
    chamada, entao basta chamar isto antes de rodar o grafo."""
    settings.n8n_url = None
    settings.n8n_api_key = None
    settings.openclaw_gateway_url = _GATEWAY_NEUTRO
    settings.openclaw_gateway_token = None


def _parse(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pergunta")
    p.add_argument("--executar", action="store_true", help="chama o LLM real (custo no OpenRouter)")
    return p.parse_args(argv)


async def _rodar(pergunta: str) -> int:
    from langgraph.checkpoint.memory import MemorySaver

    from orchestrator.config import settings
    from orchestrator.graph import builder
    from orchestrator.graph.state import fresh_turn_input

    neutralizar_efeitos_externos(settings)
    # Liga o rag SO neste processo (em memoria): o .env continua como esta.
    settings.rag_enabled = True
    graph = builder.build_graph(MemorySaver())
    config = {"configurable": {"thread_id": f"smoke-rag-{uuid.uuid4().hex[:8]}"}}
    nos = []
    async for raw in graph.astream_events(fresh_turn_input(pergunta), config=config, version="v2"):
        if raw["event"] == "on_chain_start" and raw.get("metadata", {}).get("langgraph_node") == raw["name"]:
            nos.append(raw["name"])
    estado = (await graph.aget_state(config)).values

    print(f"caminho no grafo : {' -> '.join(nos)}")
    print(f"rag acionado     : {'sim' if 'specialist_rag' in nos else 'NAO (o supervisor escolheu outro caminho)'}")
    for nota in estado.get("internal_scratchpad") or []:
        print(f"nota             : {nota.splitlines()[0]}")
    if estado.get("last_error"):
        print(f"last_error       : {estado['last_error']}")
    print(f"\nresposta final:\n{estado.get('final_result')}")
    return 0


def main(argv=None) -> int:
    args = _parse(argv)
    from orchestrator.config import settings

    indice = Path(settings.rag_index_path)
    print(f"indice  : {indice} ({'ok' if indice.is_file() else 'AUSENTE - rode python -m orchestrator.rag.ingest'})")
    print(f"modo    : {settings.rag_search_mode}, top_k {settings.rag_top_k}, colecao {settings.rag_colecao}")
    print(f"rag     : ORCHESTRATOR_RAG_ENABLED={settings.rag_enabled} no ambiente; o smoke liga so no proprio processo")
    print(f"modelos : supervisor {settings.router_model} (2 chamadas), resposta {settings.general_model} (1 chamada)")
    tracing = any(os.environ.get(v, "").lower() == "true" for v in ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING"))
    if tracing:
        print("AVISO   : tracing do LangSmith ligado no ambiente - pergunta e trechos vao para o LangSmith")
    if not settings.openrouter_api_key:
        print("erro: ORCHESTRATOR_OPENROUTER_API_KEY ausente (rode de dentro de orchestrator/, com o .env)", file=sys.stderr)
        return 2
    if not indice.is_file():
        return 2
    if not args.executar:
        print("\nnada executado: acrescente --executar para chamar o LLM real")
        return 0
    return asyncio.run(_rodar(args.pergunta))


if __name__ == "__main__":
    raise SystemExit(main())
