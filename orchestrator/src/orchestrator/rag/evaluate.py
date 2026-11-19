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
import re
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from orchestrator.rag.chunking import chunk_corpus
from orchestrator.rag.contextualize import DEFAULT_CONTEXTOS, carregar_contextos
from orchestrator.rag.embeddings import DEFAULT_MODEL, Embedder, FastEmbedEmbedder
from orchestrator.rag.ingest import (
    DEFAULT_CACHE,
    DEFAULT_COLECAO,
    DEFAULT_CORPUS,
    DEFAULT_DB,
    ORCHESTRATOR_DIR,
)
from orchestrator.rag.search import CANDIDATOS, MODOS, search
from orchestrator.rag.store import build_index, open_index, read_bm25_config, read_meta
from orchestrator.rag.text import DEFAULT_BM25, VARIANTES, Bm25Config

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


def comparar_variantes(chunks, perguntas, embedder: Embedder, *, k: int = 5, colecao: str = DEFAULT_COLECAO,
                       variantes: Sequence[Bm25Config] = VARIANTES) -> dict[str, list[ResultadoPergunta]]:
    """Monta um indice temporario por variante do BM25 (mesmos chunks, mesmo
    embedder) e avalia os 3 modos em cada um. O vetorial nao depende da
    variante: e o controle (se mudar, algo esta errado)."""
    out: dict[str, list[ResultadoPergunta]] = {}
    with tempfile.TemporaryDirectory(prefix="rag-variantes-") as d:
        for cfg in variantes:
            db = Path(d) / f"{cfg.nome}.sqlite"
            build_index(chunks, embedder, db, cfg)
            conn = open_index(db)
            try:
                assert read_bm25_config(conn) == cfg
                out[cfg.nome] = avaliar(conn, perguntas, embedder, k=k, colecao=colecao)
            finally:
                conn.close()
    return out


VARIANTES_CONTEXTO = (
    ("sem contexto", "nenhum"),
    ("contexto so no BM25", "bm25"),
    ("contexto no BM25 + embedding", "ambos"),
)


def comparar_contexto(chunks, perguntas, embedder: Embedder, contextos, *, k: int = 5,
                      colecao: str = DEFAULT_COLECAO, bm25: Bm25Config = DEFAULT_BM25) -> dict[str, list[ResultadoPergunta]]:
    """Contextual retrieval, uma variavel por vez: mesmos chunks, embedder,
    variante do BM25 (padrao da Missao 4) e gabarito; muda so ONDE entra o
    contexto. Controles: "sem contexto" reproduz a Missao 4, e na variante "so
    no BM25" o vetorial tem de sair identico ao "sem contexto"."""
    out: dict[str, list[ResultadoPergunta]] = {}
    with tempfile.TemporaryDirectory(prefix="rag-contexto-") as d:
        for nome, onde in VARIANTES_CONTEXTO:
            db = Path(d) / f"{onde}.sqlite"
            build_index(chunks, embedder, db, bm25, contextos if onde != "nenhum" else None, onde)
            conn = open_index(db)
            try:
                assert read_meta(conn)["contexto_em"] == onde
                out[nome] = avaliar(conn, perguntas, embedder, k=k, colecao=colecao)
            finally:
                conn.close()
    return out


_CODIGO = re.compile(r"\b(?:POP|F|Q|P)-\d{2}\b")


def estatisticas_tokens(chunks, contextos, contar, janela: int = 128) -> dict:
    """Quanto do texto do PROPRIO chunk cabe na janela do modelo de embedding
    quando o contexto vai na frente (o resto e truncado e nao entra no vetor)."""
    sem = [contar(c.texto_indexado()) for c in chunks]
    com = [contar(f"{contextos[c.chave]}\n{c.texto_indexado()}") for c in chunks]
    ctx = [contar(contextos[c.chave]) for c in chunks]
    frac_sem = [min(s_, janela) / s_ for s_ in sem]
    frac_com = [min(s_, max(0, janela - t)) / s_ for s_, t in zip(sem, ctx, strict=True)]
    novos = [c.chave for c in chunks if set(_CODIGO.findall(contextos[c.chave])) - set(_CODIGO.findall(c.texto))]
    return {
        "janela": janela,
        "acima_sem_contexto": sum(t > janela for t in sem),
        "acima_com_contexto": sum(t > janela for t in com),
        "tokens_contexto_medio": sum(ctx) / len(ctx),
        "fracao_do_chunk_na_janela_sem": sum(frac_sem) / len(frac_sem),
        "fracao_do_chunk_na_janela_com": sum(frac_com) / len(frac_com),
        "fracao_minima_com": min(frac_com),
        "contextos_com_codigo_ausente_do_chunk": novos,
    }


def relatorio_tokens(est: dict, n: int) -> str:
    linha1 = (
        f"Tokens (MiniLM, janela {est['janela']}): acima da janela sem contexto {est['acima_sem_contexto']}/{n}, "
        f"com contexto {est['acima_com_contexto']}/{n}; contexto medio {est['tokens_contexto_medio']:.0f} tokens."
    )
    linha2 = (
        f"Fracao do texto do proprio chunk dentro da janela: {est['fracao_do_chunk_na_janela_sem']:.0%} sem contexto, "
        f"{est['fracao_do_chunk_na_janela_com']:.0%} com contexto (pior chunk: {est['fracao_minima_com']:.0%})."
    )
    linha3 = (
        "Contextos que citam codigo (POP/F/Q/P) ausente do proprio chunk: "
        f"{len(est['contextos_com_codigo_ausente_do_chunk'])}/{n}."
    )
    return f"{linha1}\n{linha2}\n{linha3}"


def _contador_minilm(model: str, cache_dir: Path):
    """Tokenizer do proprio modelo, SEM truncamento (API interna do fastembed;
    so neste script offline)."""
    from fastembed import TextEmbedding

    tok = TextEmbedding(model_name=model, cache_dir=str(cache_dir)).model.tokenizer
    tok.no_truncation()
    return lambda texto: len(tok.encode(texto).ids)


# --- Missao 7: reranking ------------------------------------------------------------


def posicao_de_todas(ranking: Sequence[tuple[str, str]], esperadas: set[tuple[str, str]]) -> int | None:
    """Posicao (1-based) em que a ULTIMA fonte esperada aparece - so ai a
    pergunta esta respondivel. None se alguma faltar no ranking."""
    if not esperadas <= set(ranking):
        return None
    return max(ranking.index(f) + 1 for f in esperadas)


def metricas(posicoes: Sequence[int | None]) -> dict[str, float]:
    """recall@1/3/5 e MRR (sobre a profundidade do ranking; ausente = 0)."""
    n = len(posicoes)
    out = {f"recall@{k}": sum(p is not None and p <= k for p in posicoes) for k in (1, 3, 5)}
    out["mrr"] = sum(1 / p for p in posicoes if p) / n
    out["n"] = n
    return out


def percentil(valores: Sequence[float], q: float) -> float:
    """Nearest-rank (sem interpolacao)."""
    import math

    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(q * len(ordenados)) - 1)]


def comparar_rerank(conn, perguntas, embedder, reranker, *, candidatos: int = 20, repeticoes: int = 3,
                    colecao: str = DEFAULT_COLECAO, relogio=None) -> dict:
    """Para cada pergunta: o hibrido traz `candidatos`; o reranker reordena OS
    MESMOS candidatos. Metricas sobre os 20 (com e sem rerank, mesma
    profundidade). Latencia: so o `reranker.score` dos 20, 1 aquecimento
    descartado, `repeticoes` por pergunta."""
    import time

    from orchestrator.rag.rerank import reordenar

    relogio = relogio or time.perf_counter
    if perguntas:
        reranker.score(perguntas[0]["pergunta"], ["aquecimento"] * candidatos)
    sem, com, lat, por_pergunta = [], [], [], []
    for p in perguntas:
        hits = search(conn, p["pergunta"], modo="hibrido", embedder=embedder, k=candidatos, colecao=colecao)
        esperadas = fontes(p)
        for _ in range(repeticoes):
            t0 = relogio()
            reranker.score(p["pergunta"], [h.texto for h in hits])
            lat.append(relogio() - t0)
        reordenados = reordenar(p["pergunta"], hits, reranker, k=candidatos)
        a = posicao_de_todas([h.chave for h in hits], esperadas)
        b = posicao_de_todas([h.chave for h in reordenados], esperadas)
        sem.append(a)
        com.append(b)
        por_pergunta.append({"id": p["id"], "tipo": p["tipo"], "sem": a, "com": b,
                             "top5_com": [h.chave for h in reordenados[:5]]})
    return {"sem": metricas(sem), "com": metricas(com), "latencias_s": lat,
            "p50_s": percentil(lat, 0.50) if lat else 0.0, "p95_s": percentil(lat, 0.95) if lat else 0.0,
            "por_pergunta": por_pergunta, "candidatos": candidatos}


# Pre-registro da Missao 7 (docs/RAG.md): TODAS precisam ser verdadeiras.
LIMITE_P95_S = 1.5
LIMITE_RAM_MB = 2048


def veredito_rerank(r: dict, ram_mb: float) -> dict[str, bool]:
    return {
        "a) MRR estritamente maior": r["com"]["mrr"] > r["sem"]["mrr"],
        "b) recall@5 nao cai (>= 16/17)": r["com"]["recall@5"] >= max(16, r["sem"]["recall@5"]),
        f"c) p95 <= {LIMITE_P95_S} s": r["p95_s"] <= LIMITE_P95_S,
        f"d) RAM <= {LIMITE_RAM_MB} MB": ram_mb <= LIMITE_RAM_MB,
    }


def relatorio_rerank(r: dict, ram_mb: float, modelo: str) -> str:
    n = r["sem"]["n"]

    def linha(nome, m, lat="—", ram="—"):
        return (f"| {nome} | {m['recall@1']}/{n} | {m['recall@3']}/{n} | {m['recall@5']}/{n} | {m['mrr']:.3f} | "
                f"{lat} | {ram} |")

    out = [
        f"| Configuracao | recall@1 | recall@3 | recall@5 | MRR@{r['candidatos']} | latencia rerank p50 / p95 | RAM do reranker |",
        "|---|---|---|---|---|---|---|",
        linha("hibrido + contexto (sem rerank)", r["sem"]),
        linha(f"+ rerank {modelo}", r["com"], f"{r['p50_s']:.2f} s / {r['p95_s']:.2f} s", f"{ram_mb:.0f} MB"),
        "",
        f"Latencia: {len(r['latencias_s'])} medicoes ({n} perguntas x repeticoes) do score de {r['candidatos']} candidatos.",
        "",
        "Veredito (regra pre-registrada; TODAS precisam ser verdadeiras):",
    ]
    v = veredito_rerank(r, ram_mb)
    out += [f"- {'OK   ' if ok else 'FALHA'} {crit}" for crit, ok in v.items()]
    out += [f"=> rerank {'VIRA' if all(v.values()) else 'NAO vira'} padrao", "", "Posicao (todas as fontes) que mudou:"]
    mud = [x for x in r["por_pergunta"] if x["sem"] != x["com"]]
    out += [f"- {x['id']} ({x['tipo']}): {x['sem'] or '—'} -> {x['com'] or '—'}" for x in mud] or ["- nenhuma"]
    return "\n".join(out)


def _rss_mb() -> float:
    with open("/proc/self/status") as fh:
        for linha in fh:
            if linha.startswith("VmRSS"):
                return int(linha.split()[1]) / 1024
    return 0.0


def relatorio_variantes(por_variante: dict[str, list[ResultadoPergunta]], k: int = 5,
                        titulo: str = "Variante do BM25") -> str:
    modos = list(MODOS)
    linhas = [f"| {titulo} | " + " | ".join(modos) + " |", "|---|" + "---|" * len(modos)]
    for nome, resultados in por_variante.items():
        r = resumo(resultados)
        linhas.append(f"| {nome} | " + " | ".join(_fmt(r[m]["total"]) for m in modos) + " |")
    base = {(r.id, r.modo): r for r in next(iter(por_variante.values()))}
    linhas += ["", "Mudancas em relacao ao baseline (posicao de cada fonte, '—' = fora do top 50):", ""]
    mudou = False
    for nome, resultados in list(por_variante.items())[1:]:
        for r in resultados:
            b = base[(r.id, r.modo)]
            if r.acertou != b.acertou or r.posicao_das_fontes != b.posicao_das_fontes:
                mudou = True
                pos = "; ".join(
                    f"{f.split(' :: ')[1]}: {b.posicao_das_fontes[f] or '—'} → {r.posicao_das_fontes[f] or '—'}"
                    for f in r.posicao_das_fontes)
                virou = "" if r.acertou == b.acertou else (" **ACERTO NOVO**" if r.acertou else " **PERDEU**")
                linhas.append(f"- {nome} / {r.modo} / {r.id}{virou}: {pos}")
    if not mudou:
        linhas.append("- nenhuma")
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
    p.add_argument("--comparar-variantes", action="store_true",
                   help="ignora --db: monta 1 indice temporario por variante do BM25 (a partir de --corpus) e compara")
    p.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    p.add_argument("--comparar-contexto", action="store_true",
                   help="ignora --db: sem contexto x contexto so no BM25 x contexto no BM25 + embedding")
    p.add_argument("--contextos", type=Path, default=DEFAULT_CONTEXTOS)
    p.add_argument("--comparar-rerank", metavar="MODELO_RERANKER",
                   help="indice padrao (hibrido + contexto em ambos) sem x com rerank deste cross-encoder")
    p.add_argument("--repeticoes", type=int, default=3)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.comparar_rerank:
        import resource

        from orchestrator.rag.rerank import FastEmbedReranker

        chunks = chunk_corpus(args.corpus, args.colecao)
        contextos = carregar_contextos(args.contextos, args.corpus, args.colecao)
        embedder = FastEmbedEmbedder(args.model, cache_dir=args.cache_dir)
        perguntas = carregar_perguntas(args.gabarito)
        with tempfile.TemporaryDirectory(prefix="rag-rerank-") as d:
            db = Path(d) / "padrao.sqlite"
            build_index(chunks, embedder, db, DEFAULT_BM25, contextos, "ambos")
            conn = open_index(db)
            try:
                antes = _rss_mb()
                reranker = FastEmbedReranker(args.comparar_rerank, cache_dir=args.cache_dir)
                r = comparar_rerank(conn, perguntas, embedder, reranker, repeticoes=args.repeticoes,
                                    colecao=args.colecao)
                pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            finally:
                conn.close()
        ram = max(0.0, pico - antes)
        print(f"indice padrao (hibrido + contexto em ambos, bm25 {DEFAULT_BM25.nome}) | reranker {args.comparar_rerank}")
        print(f"RAM: RSS antes de carregar o reranker {antes:.0f} MB, pico do processo {pico:.0f} MB\n")
        print(relatorio_rerank(r, ram, args.comparar_rerank))
        if args.json:
            args.json.write_text(json.dumps({**r, "ram_mb": ram}, ensure_ascii=False, indent=2, default=list),
                                 encoding="utf-8")
        return 0
    if args.comparar_contexto:
        chunks = chunk_corpus(args.corpus, args.colecao)
        contextos = carregar_contextos(args.contextos, args.corpus, args.colecao)
        embedder = FastEmbedEmbedder(args.model, cache_dir=args.cache_dir)
        por_variante = comparar_contexto(chunks, carregar_perguntas(args.gabarito), embedder, contextos,
                                         k=args.k, colecao=args.colecao)
        est = estatisticas_tokens(chunks, contextos, _contador_minilm(args.model, args.cache_dir))
        print(f"modelo {embedder.model_name} | bm25 {DEFAULT_BM25.nome} | contextos {args.contextos}\n")
        print(relatorio_tokens(est, len(chunks)) + "\n")
        print(relatorio_variantes(por_variante, args.k, titulo="Contexto"))
        if args.json:
            dados = {"tokens": est, **{n: [asdict(r) for r in rs] for n, rs in por_variante.items()}}
            args.json.write_text(json.dumps(dados, ensure_ascii=False, indent=2, default=list), encoding="utf-8")
        return 0
    if args.comparar_variantes:
        embedder = FastEmbedEmbedder(args.model, cache_dir=args.cache_dir)
        por_variante = comparar_variantes(chunk_corpus(args.corpus, args.colecao), carregar_perguntas(args.gabarito),
                                          embedder, k=args.k, colecao=args.colecao)
        print(f"modelo {embedder.model_name} | corpus {args.corpus}\n")
        print(relatorio_variantes(por_variante, args.k))
        if args.json:
            dados = {n: [asdict(r) for r in rs] for n, rs in por_variante.items()}
            args.json.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    conn = open_index(args.db)
    try:
        meta = read_meta(conn)
        embedder = FastEmbedEmbedder(args.model, cache_dir=args.cache_dir)
        resultados = avaliar(conn, carregar_perguntas(args.gabarito), embedder, k=args.k, colecao=args.colecao)
    finally:
        conn.close()
    print(f"indice: {args.db} | modelo {meta.get('model_name')} | {meta.get('n_chunks')} chunks | "
          f"bm25 {Bm25Config(meta.get('bm25_stopwords') == '1', meta.get('bm25_stemming') == '1').nome}\n")
    print(relatorio_markdown(resultados, args.k))
    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in resultados], ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
