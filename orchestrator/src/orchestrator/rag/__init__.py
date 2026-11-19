"""Busca em manuais de procedimento (RAG MVP, docs/RAG.md).

Ainda NAO esta ligado ao grafo (Missao 4). Partes:

- `chunking`: um chunk por secao `##` dos POPs, mais o preambulo do titulo `#`;
- `embeddings`: protocolo `Embedder` e o `FastEmbedEmbedder` (import preguicoso
  do fastembed - importar este pacote nao carrega o modelo nem o onnxruntime);
- `store`: indice SQLite proprio (sqlite-vec + FTS5), separado do checkpoints;
- `search`: busca vetorial, BM25 e hibrida (RRF);
- `ingest` / `evaluate`: scripts offline (`python -m orchestrator.rag.ingest`).
"""

from orchestrator.rag.chunking import Chunk, chunk_corpus, chunk_markdown
from orchestrator.rag.embeddings import Embedder
from orchestrator.rag.search import SearchHit, search
from orchestrator.rag.store import build_index, open_index

__all__ = [
    "Chunk",
    "Embedder",
    "SearchHit",
    "build_index",
    "chunk_corpus",
    "chunk_markdown",
    "open_index",
    "search",
]
