"""Ingestao offline: POPs -> chunks -> embeddings (fastembed) -> indice SQLite.

    cd orchestrator && python -m orchestrator.rag.ingest

Na primeira execucao baixa o modelo do Hugging Face Hub para
`data/fastembed_cache/`. O indice vai para `data/rag_index.sqlite`, separado
do `data/checkpoints.sqlite` (estado de conversa), e pode ser apagado e
reconstruido a qualquer momento. Nao le `orchestrator.config` nem `.env`.
"""

import argparse
import sys
from pathlib import Path

from orchestrator.rag.chunking import chunk_corpus
from orchestrator.rag.contextualize import DEFAULT_CONTEXTOS, carregar_contextos
from orchestrator.rag.embeddings import DEFAULT_MODEL, FastEmbedEmbedder
from orchestrator.rag.store import CONTEXTO_EM, build_index
from orchestrator.rag.text import DEFAULT_BM25, Bm25Config

ORCHESTRATOR_DIR = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS = ORCHESTRATOR_DIR / "fixtures" / "rag" / "supermercado"
DEFAULT_DB = ORCHESTRATOR_DIR / "data" / "rag_index.sqlite"
DEFAULT_CACHE = ORCHESTRATOR_DIR / "data" / "fastembed_cache"
DEFAULT_COLECAO = "supermercado"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS, help="diretorio com os POPs (*.md)")
    p.add_argument("--colecao", default=DEFAULT_COLECAO)
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="arquivo do indice (NUNCA o checkpoints.sqlite)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    p.add_argument("--stopwords", action=argparse.BooleanOptionalAction, default=DEFAULT_BM25.stopwords,
                   help="stopwords em PT no BM25 (padrao: %(default)s)")
    p.add_argument("--stemming", action=argparse.BooleanOptionalAction, default=DEFAULT_BM25.stemming,
                   help="stemming Snowball PT no BM25 (padrao: %(default)s)")
    # Padrao "ambos" desde a Missao 6 (contexto no BM25 + embedding, 16/17).
    # Exige um contextos.json valido para o corpus atual (POP editado = regerar).
    p.add_argument("--contexto-em", choices=CONTEXTO_EM, default="ambos",
                   help="contextual retrieval: onde o contexto gerado entra (padrao: %(default)s)")
    p.add_argument("--contextos", type=Path, default=DEFAULT_CONTEXTOS, help="arquivo gerado por rag.contextualize")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.db.name == "checkpoints.sqlite":
        print("erro: o indice do RAG nao pode ser o checkpoints.sqlite", file=sys.stderr)
        return 2
    chunks = chunk_corpus(args.corpus, args.colecao)
    # Contextos ANTES do embedder: contextos.json obsoleto falha cedo, sem
    # carregar modelo.
    contextos = carregar_contextos(args.contextos, args.corpus, args.colecao) if args.contexto_em != "nenhum" else None
    embedder = FastEmbedEmbedder(args.model, cache_dir=args.cache_dir)
    bm25 = Bm25Config(stopwords=args.stopwords, stemming=args.stemming)
    n = build_index(chunks, embedder, args.db, bm25, contextos, args.contexto_em)
    arquivos = len({c.arquivo for c in chunks})
    print(f"{n} chunks de {arquivos} arquivos -> {args.db} (modelo {embedder.model_name}, dim {embedder.dim}, "
          f"bm25 {bm25.nome}, contexto {args.contexto_em})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
