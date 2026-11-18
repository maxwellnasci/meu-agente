"""Embeddings do RAG.

`Embedder` e o contrato que o indice e a busca usam. O real e o
`FastEmbedEmbedder` (ONNX em CPU, sem API). Os testes usam um embedder falso
e deterministico: download de modelo e inferencia real so rodam fora do
pytest (`python -m orchestrator.rag.ingest` / `evaluate`).

O fastembed e importado so dentro do `FastEmbedEmbedder`: importar
`orchestrator.rag` nao carrega fastembed nem onnxruntime.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@runtime_checkable
class Embedder(Protocol):
    model_name: str
    dim: int

    def embed_documents(self, textos: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, texto: str) -> list[float]: ...


class FastEmbedEmbedder:
    """Embedder real. Na primeira vez baixa o modelo para `cache_dir`
    (Hugging Face Hub); depois roda offline a partir do cache."""

    def __init__(self, model_name: str = DEFAULT_MODEL, cache_dir: Path | None = None):
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir) if cache_dir else None)
        self.dim = len(next(iter(self._model.query_embed(["dimensao"]))))

    def embed_documents(self, textos: Sequence[str]) -> list[list[float]]:
        # passage_embed/query_embed aplicam os prefixos que o modelo exigir
        # (ex.: "passage:"/"query:" do e5); para o MiniLM sao identicos a embed.
        return [v.tolist() for v in self._model.passage_embed(list(textos))]

    def embed_query(self, texto: str) -> list[float]:
        return next(iter(self._model.query_embed([texto]))).tolist()
