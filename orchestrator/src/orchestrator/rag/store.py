"""Indice do RAG: um arquivo SQLite PROPRIO (nunca o checkpoints.sqlite).

Tabelas:

- `meta`: modelo e dimensao do embedding usados na ingestao. A busca recusa
  um embedder diferente: sem isso, vetores de modelos distintos (ou do
  embedder falso dos testes) se misturariam em silencio;
- `chunks`: arquivo, secao, colecao, texto (o que volta como fonte);
- `chunks_fts`: FTS5 (BM25), tokenizer `unicode61 remove_diacritics 2`
  porque as perguntas de WhatsApp chegam sem acento ("ferias", "termometro").
  Com stopwords/stemming ligados (`text.Bm25Config`, padrao), a coluna guarda
  o texto JA normalizado por `text.normalizar`; a variante fica na `meta`
  (`bm25_stopwords`, `bm25_stemming`) e a busca aplica a mesma na consulta;
- `chunks_vec`: sqlite-vec `vec0`, distancia cosseno, com `colecao` como
  coluna de metadado (filtro dentro da propria busca KNN).

O indice e DERIVADO do corpus: `build_index` monta tudo num arquivo
temporario ao lado e so no fim troca pelo destino (`os.replace`). Uma
ingestao que falhe no meio nunca deixa um indice pela metade.
"""

import os
import sqlite3
import tempfile
from collections.abc import Sequence
from pathlib import Path

import sqlite_vec

from orchestrator.rag.chunking import Chunk
from orchestrator.rag.embeddings import Embedder
from orchestrator.rag.text import DEFAULT_BM25, Bm25Config, normalizar

SCHEMA_VERSION = "2"  # 2: variante do BM25 na meta


class IndexMismatchError(RuntimeError):
    """O embedder da busca nao e o mesmo da ingestao (modelo ou dimensao)."""


def _connect(path: Path, *, readonly: bool) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)
    return conn


def _criar_schema(conn: sqlite3.Connection, dim: int) -> None:
    dim = int(dim)  # entra no DDL: so inteiro positivo
    if dim <= 0:
        raise ValueError(f"dimensao invalida: {dim}")
    conn.executescript(
        """
        CREATE TABLE meta (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            arquivo TEXT NOT NULL,
            secao TEXT NOT NULL,
            colecao TEXT NOT NULL,
            texto TEXT NOT NULL,
            UNIQUE (colecao, arquivo, secao)
        );
        CREATE VIRTUAL TABLE chunks_fts USING fts5(texto, tokenize = 'unicode61 remove_diacritics 2');
        """
    )
    conn.execute(f"CREATE VIRTUAL TABLE chunks_vec USING vec0(embedding float[{dim}] distance_metric=cosine, colecao text)")


def _texto_fts(chunk: Chunk, bm25: Bm25Config) -> str:
    texto = chunk.texto_indexado()
    return normalizar(texto, bm25) if bm25.normaliza else texto


def build_index(chunks: Sequence[Chunk], embedder: Embedder, path: Path, bm25: Bm25Config = DEFAULT_BM25) -> int:
    """(Re)constroi o indice em `path` e devolve o numero de chunks gravados."""
    if not chunks:
        raise ValueError("nenhum chunk para indexar")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    vetores = embedder.embed_documents([c.texto_indexado() for c in chunks])
    if len(vetores) != len(chunks) or any(len(v) != embedder.dim for v in vetores):
        raise ValueError("o embedder devolveu quantidade ou dimensao de vetores inesperada")

    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.unlink()  # sqlite cria o arquivo do zero
        conn = _connect(tmp, readonly=False)
        try:
            with conn:
                _criar_schema(conn, embedder.dim)
                conn.executemany(
                    "INSERT INTO meta (chave, valor) VALUES (?, ?)",
                    [
                        ("schema_version", SCHEMA_VERSION),
                        ("model_name", embedder.model_name),
                        ("dim", str(embedder.dim)),
                        ("n_chunks", str(len(chunks))),
                        ("bm25_stopwords", str(int(bm25.stopwords))),
                        ("bm25_stemming", str(int(bm25.stemming))),
                    ],
                )
                for i, (chunk, vetor) in enumerate(zip(chunks, vetores, strict=True), start=1):
                    conn.execute(
                        "INSERT INTO chunks (id, arquivo, secao, colecao, texto) VALUES (?, ?, ?, ?, ?)",
                        (i, chunk.arquivo, chunk.secao, chunk.colecao, chunk.texto),
                    )
                    conn.execute("INSERT INTO chunks_fts (rowid, texto) VALUES (?, ?)", (i, _texto_fts(chunk, bm25)))
                    conn.execute(
                        "INSERT INTO chunks_vec (rowid, embedding, colecao) VALUES (?, ?, ?)",
                        (i, sqlite_vec.serialize_float32(vetor), chunk.colecao),
                    )
        finally:
            conn.close()
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return len(chunks)


def open_index(path: Path) -> sqlite3.Connection:
    """Abre o indice SO PARA LEITURA (falha se o arquivo nao existir)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"indice do RAG nao encontrado: {path} (rode python -m orchestrator.rag.ingest)")
    return _connect(path, readonly=True)


def read_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT chave, valor FROM meta").fetchall())


def read_bm25_config(conn: sqlite3.Connection) -> Bm25Config:
    """Variante do BM25 com que o indice foi montado. Indice sem as chaves
    (schema 1, Missao 3) = baseline: texto cru, sem stopwords nem stemming."""
    meta = read_meta(conn)
    return Bm25Config(meta.get("bm25_stopwords") == "1", meta.get("bm25_stemming") == "1")


def check_embedder(conn: sqlite3.Connection, embedder: Embedder) -> None:
    meta = read_meta(conn)
    if meta.get("model_name") != embedder.model_name or meta.get("dim") != str(embedder.dim):
        raise IndexMismatchError(
            f"indice gerado com {meta.get('model_name')!r} (dim {meta.get('dim')}), "
            f"busca com {embedder.model_name!r} (dim {embedder.dim}) - reingira o corpus"
        )
