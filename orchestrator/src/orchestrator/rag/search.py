"""Busca no indice do RAG: so vetorial, so BM25 (FTS5) ou hibrida (RRF).

- **vetorial**: KNN cosseno no `chunks_vec` (sqlite-vec), filtrado por colecao.
- **bm25**: FTS5. A pergunta vira uma query SEGURA: codigos (`POP-06`,
  `F-12`, `Q-22`, `P-05`) viram frase (`"pop 06"`, para nao virar `pop OR 06`)
  e o resto vira palavras entre aspas unidas por OR. Nenhum operador do FTS5
  (`NEAR`, `*`, `-`, `:`, parenteses) chega cru ao MATCH.
- **hibrido**: Reciprocal Rank Fusion dos dois rankings, `1/(k_rrf + posicao)`
  somado por chunk. Junta pela POSICAO, sem calibrar escalas de score.
"""

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import sqlite_vec

from orchestrator.rag.embeddings import Embedder
from orchestrator.rag.store import check_embedder, read_bm25_config
from orchestrator.rag.text import Bm25Config, tokens

Modo = Literal["vetorial", "bm25", "hibrido"]
MODOS: tuple[Modo, ...] = ("vetorial", "bm25", "hibrido")
RRF_K = 60
CANDIDATOS = 50  # profundidade de cada ranking antes da fusao

_CODIGO = re.compile(r"\b(POP|F|Q|P)-(\d{2})\b", re.IGNORECASE)
_PALAVRA = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class SearchHit:
    rank: int
    arquivo: str
    secao: str
    colecao: str
    texto: str
    score: float
    modo: str

    @property
    def chave(self) -> tuple[str, str]:
        return (self.arquivo, self.secao)


def fts_query(pergunta: str) -> str:
    """Pergunta livre -> expressao FTS5 segura ('' se nao sobrar termo)."""
    termos: list[str] = []
    for m in _CODIGO.finditer(pergunta):
        frase = f'"{m.group(1).lower()} {m.group(2)}"'
        if frase not in termos:
            termos.append(frase)
    resto = _CODIGO.sub(" ", pergunta)
    for palavra in _PALAVRA.findall(resto):
        termo = f'"{palavra.lower()}"'
        if termo not in termos:
            termos.append(termo)
    return " OR ".join(termos)


def fts_query_normalizada(pergunta: str, cfg: Bm25Config) -> str:
    """Mesma normalizacao da indexacao (`text.tokens`), em query segura:
    codigo vira frase, o resto vira termos entre aspas unidos por OR. Os
    termos saem de `\\w+` (e codigos "pop 06"): nunca contem aspas, entao
    nenhum operador do FTS5 escapa."""
    termos: list[str] = []
    for termo, _ in tokens(pergunta, cfg):
        q = f'"{termo}"'
        if q not in termos:
            termos.append(q)
    return " OR ".join(termos)


def rrf_fuse(rankings: Sequence[Sequence[int]], k_rrf: int = RRF_K) -> list[tuple[int, float]]:
    """Funde rankings de ids (melhor primeiro). Empate: melhor posicao
    individual, depois menor id (deterministico)."""
    scores: dict[int, float] = {}
    melhor: dict[int, int] = {}
    for ranking in rankings:
        for posicao, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k_rrf + posicao)
            melhor[doc_id] = min(melhor.get(doc_id, posicao), posicao)
    return sorted(scores.items(), key=lambda item: (-item[1], melhor[item[0]], item[0]))


def _bm25_ids(conn: sqlite3.Connection, pergunta: str, colecao: str, limite: int) -> list[tuple[int, float]]:
    cfg = read_bm25_config(conn)
    query = fts_query_normalizada(pergunta, cfg) if cfg.normaliza else fts_query(pergunta)
    if not query:
        return []
    # bm25() do FTS5: quanto MENOR, melhor.
    return conn.execute(
        """
        SELECT c.id, bm25(chunks_fts) AS s
        FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
        WHERE chunks_fts MATCH ? AND c.colecao = ?
        ORDER BY s, c.id
        LIMIT ?
        """,
        (query, colecao, limite),
    ).fetchall()


def _vetorial_ids(
    conn: sqlite3.Connection, pergunta: str, embedder: Embedder, colecao: str, limite: int
) -> list[tuple[int, float]]:
    vetor = embedder.embed_query(pergunta)
    linhas = conn.execute(
        "SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ? AND colecao = ?",
        (sqlite_vec.serialize_float32(vetor), limite, colecao),
    ).fetchall()
    return sorted(linhas, key=lambda linha: (linha[1], linha[0]))


def search(
    conn: sqlite3.Connection,
    pergunta: str,
    *,
    modo: Modo = "hibrido",
    embedder: Embedder | None = None,
    k: int = 5,
    colecao: str = "supermercado",
) -> list[SearchHit]:
    if modo not in MODOS:
        raise ValueError(f"modo invalido: {modo!r} (use {MODOS})")
    if modo != "bm25":
        if embedder is None:
            raise ValueError(f"modo {modo!r} precisa de embedder")
        check_embedder(conn, embedder)
    limite = max(k, CANDIDATOS)

    if modo == "bm25":
        ranqueados = _bm25_ids(conn, pergunta, colecao, limite)
    elif modo == "vetorial":
        ranqueados = _vetorial_ids(conn, pergunta, embedder, colecao, limite)
    else:
        bm25 = [doc_id for doc_id, _ in _bm25_ids(conn, pergunta, colecao, limite)]
        vetorial = [doc_id for doc_id, _ in _vetorial_ids(conn, pergunta, embedder, colecao, limite)]
        ranqueados = rrf_fuse([vetorial, bm25])

    hits: list[SearchHit] = []
    for posicao, (doc_id, score) in enumerate(ranqueados[:k], start=1):
        arquivo, secao, col, texto = conn.execute(
            "SELECT arquivo, secao, colecao, texto FROM chunks WHERE id = ?", (doc_id,)
        ).fetchone()
        hits.append(SearchHit(posicao, arquivo, secao, col, texto, float(score), modo))
    return hits
