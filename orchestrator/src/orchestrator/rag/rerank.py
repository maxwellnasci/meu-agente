"""Reranking: "busque largo, rerankeie estreito" (Missao 7).

A busca padrao (hibrido + contexto) traz `candidatos` trechos (20) e um
cross-encoder le PERGUNTA + TRECHO juntos, reordena e devolve os `k` (5)
melhores. O reranker pontua o `texto` do trecho, o mesmo que vai como fonte
para o synthesize_final (nunca o contexto gerado da Missao 6).

`Reranker` e o contrato; o real e o `FastEmbedReranker` (cross-encoder ONNX
em CPU, import preguicoso do fastembed). Os testes usam um falso.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol, runtime_checkable

from orchestrator.rag.search import SearchHit, search

CANDIDATOS_RERANK = 20


@runtime_checkable
class Reranker(Protocol):
    model_name: str

    def score(self, pergunta: str, textos: Sequence[str]) -> list[float]: ...


class FastEmbedReranker:
    def __init__(self, model_name: str, cache_dir=None):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model_name = model_name
        self._modelo = TextCrossEncoder(model_name=model_name, cache_dir=str(cache_dir) if cache_dir else None)

    def score(self, pergunta: str, textos: Sequence[str]) -> list[float]:
        return [float(s) for s in self._modelo.rerank(pergunta, list(textos))]


def reordenar(pergunta: str, hits: Sequence[SearchHit], reranker: Reranker, k: int) -> list[SearchHit]:
    """Reordena pelo score do cross-encoder (maior = melhor). Empate: a ordem
    da busca original (deterministico)."""
    if not hits:
        return []
    scores = reranker.score(pergunta, [h.texto for h in hits])
    if len(scores) != len(hits):
        raise ValueError(f"reranker devolveu {len(scores)} scores para {len(hits)} trechos")
    ordem = sorted(range(len(hits)), key=lambda i: (-scores[i], hits[i].rank))
    return [
        replace(hits[i], rank=pos, score=float(scores[i]), modo=f"{hits[i].modo}+rerank")
        for pos, i in enumerate(ordem[:k], start=1)
    ]


def buscar_com_rerank(
    conn,
    pergunta: str,
    *,
    reranker: Reranker,
    modo: str = "hibrido",
    embedder=None,
    k: int = 5,
    candidatos: int = CANDIDATOS_RERANK,
    colecao: str = "supermercado",
) -> list[SearchHit]:
    hits = search(conn, pergunta, modo=modo, embedder=embedder, k=max(candidatos, k), colecao=colecao)
    return reordenar(pergunta, hits, reranker, k)
