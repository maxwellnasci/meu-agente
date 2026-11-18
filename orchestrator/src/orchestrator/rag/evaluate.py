"""Avaliacao offline do retrieval: recall@5 nos 3 modos.

    cd orchestrator && python -m orchestrator.rag.ingest && python -m orchestrator.rag.evaluate

recall@5 (docs/RAG.md, "Metodo de avaliacao"): fracao das perguntas `direta`
e `multi_secao` em que TODAS as fontes (pares arquivo + secao) aparecem entre
os 5 primeiros trechos. Numa `multi_secao`, achar so uma das duas e erro. As
`sem_resposta` ficam de fora: dependem da resposta gerada (Missao 4).

Para cada falha, mostra em que posicao (ate a 50a) a fonte que faltou
apareceu - e a primeira pista do porque.
"""

import argparse
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from orchestrator.rag.embeddings import DEFAULT_MODEL, Embedder, FastEmbedEmbedder
from orchestrator.rag.ingest import (
    DEFAULT_CACHE,
    DEFAULT_COLECAO,
    DEFAULT_DB,
    ORCHESTRATOR_DIR,
)
from orchestrator.rag.search import CANDIDATOS, MODOS, search
from orchestrator.rag.store import open_index, read_meta

DEFAULT_GABARITO = ORCHESTRATOR_DIR / "fixtures" / "rag" / "gabarito.yaml"
TIPOS_AVALIADOS = ("direta", "multi_secao")


@dataclass
class ResultadoPergunta:
    id: str
    tipo: str
    modo: str
    acertou: bool
    top: list[tuple[str, str]]
    posicao_das_fontes: dict[str, int | None] = field(default_factory=dict)  # "arquivo :: secao" -> posicao


def fontes(pergunta: dict) -> set[tuple[str, str]]:
    return set(zip(pergunta["arquivo_fonte"], pergunta["secao_fonte"], strict=True))


def recall_hit(esperadas: Iterable[tuple[str, str]], recuperadas: Sequence[tuple[str, str]], k: int = 5) -> bool:
    """Acerto so se TODAS as fontes esperadas estao nos k primeiros."""
    esperadas = set(esperadas)
    if not esperadas:
        raise ValueError("pergunta sem fonte nao entra no recall")
    return esperadas <= set(recuperadas[:k])


def carregar_perguntas(gabarito: Path) -> list[dict]:
    perguntas = yaml.safe_load(Path(gabarito).read_text(encoding="utf-8"))["perguntas"]
    return [p for p in perguntas if p["tipo"] in TIPOS_AVALIADOS]


def avaliar(conn, perguntas: Sequence[dict], embedder: Embedder | None, *, k: int = 5, colecao: str = DEFAULT_COLECAO,
            modos: Sequence[str] = MODOS) -> list[ResultadoPergunta]:
    resultados = []
    for modo in modos:
        for p in perguntas:
            ranking = [h.chave for h in search(conn, p["pergunta"], modo=modo, embedder=embedder,
                                               k=CANDIDATOS, colecao=colecao)]
            esperadas = fontes(p)
            posicoes = {f"{a} :: {s}": (ranking.index((a, s)) + 1 if (a, s) in ranking else None)
                        for a, s in sorted(esperadas)}
            resultados.append(ResultadoPergunta(p["id"], p["tipo"], modo, recall_hit(esperadas, ranking, k),
                                                ranking[:k], posicoes))
    return resultados


def resumo(resultados: Sequence[ResultadoPergunta]) -> dict[str, dict[str, tuple[int, int]]]:
    """modo -> {"total"|"direta"|"multi_secao": (acertos, total)}."""
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for r in resultados:
        grupo = out.setdefault(r.modo, {})
        for chave in ("total", r.tipo):
            acertos, total = grupo.get(chave, (0, 0))
            grupo[chave] = (acertos + int(r.acertou), total + 1)
    return out


def _fmt(par: tuple[int, int]) -> str:
    acertos, total = par
    return f"{acertos}/{total} ({acertos / total:.0%})" if total else "-"


def relatorio_markdown(resultados: Sequence[ResultadoPergunta], k: int = 5) -> str:
    nomes = {"vetorial": "Só vetorial", "bm25": "Só BM25 (FTS5)", "hibrido": "Híbrido (RRF)"}
    linhas = [
        f"| Configuração | recall@{k} | Diretas | Multi-seção |",
        "|---|---|---|---|",
    ]
    for modo, grupo in resumo(resultados).items():
        linhas.append(f"| {nomes.get(modo, modo)} | {_fmt(grupo['total'])} | {_fmt(grupo.get('direta', (0, 0)))} "
                      f"| {_fmt(grupo.get('multi_secao', (0, 0)))} |")
    falhas = [r for r in resultados if not r.acertou]
    linhas += ["", f"Falhas (fonte fora do top {k}; posição até a {CANDIDATOS}ª, '—' = não apareceu):", ""]
    if not falhas:
        linhas.append("- nenhuma")
    for r in falhas:
        faltou = "; ".join(f"{fonte} → {pos if pos else '—'}" for fonte, pos in r.posicao_das_fontes.items()
                           if pos is None or pos > k)
        linhas.append(f"- **{r.id}** ({r.tipo}, {r.modo}): {faltou}")
    return "\n".join(linhas)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--gabarito", type=Path, default=DEFAULT_GABARITO)
    p.add_argument("--colecao", default=DEFAULT_COLECAO)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--json", type=Path, help="grava o resultado detalhado por pergunta/modo neste arquivo")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    conn = open_index(args.db)
    try:
        meta = read_meta(conn)
        embedder = FastEmbedEmbedder(args.model, cache_dir=args.cache_dir)
        resultados = avaliar(conn, carregar_perguntas(args.gabarito), embedder, k=args.k, colecao=args.colecao)
    finally:
        conn.close()
    print(f"indice: {args.db} | modelo {meta.get('model_name')} | {meta.get('n_chunks')} chunks\n")
    print(relatorio_markdown(resultados, args.k))
    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in resultados], ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
