"""Reranking (Missao 7) com reranker FALSO e deterministico.

O cross-encoder real (download + medicao) roda fora do pytest:
`python -m orchestrator.rag.evaluate --comparar-rerank MODELO`.
"""

import logging
from pathlib import Path

import pytest
from test_rag_engine import FakeEmbedder

from orchestrator.config import Settings, settings
from orchestrator.graph import rag_specialist
from orchestrator.graph.nodes import specialist_rag_node
from orchestrator.rag import evaluate
from orchestrator.rag.chunking import chunk_corpus
from orchestrator.rag.rerank import Reranker, buscar_com_rerank, reordenar
from orchestrator.rag.search import SearchHit
from orchestrator.rag.store import build_index, open_index

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "rag" / "supermercado"
GABARITO = CORPUS.parent / "gabarito.yaml"


class RerankerFalso:
    """Score = quantas vezes `palavra` aparece no trecho."""

    def __init__(self, palavra: str = "sangria", model_name: str = "reranker-falso"):
        self.model_name = model_name
        self.palavra = palavra
        self.chamadas = 0

    def score(self, pergunta, textos):
        self.chamadas += 1
        return [float(t.lower().count(self.palavra)) for t in textos]


def _hit(rank, secao, texto="x"):
    return SearchHit(rank, "a.md", secao, "c", texto, 0.0, "hibrido")


@pytest.fixture
def indice(tmp_path, monkeypatch):
    db = tmp_path / "rag_index.sqlite"
    build_index(chunk_corpus(CORPUS, "supermercado"), FakeEmbedder(), db)
    monkeypatch.setattr(settings, "rag_enabled", True)
    monkeypatch.setattr(settings, "rag_index_path", str(db))
    monkeypatch.setattr(settings, "rag_search_mode", "bm25")
    monkeypatch.setattr(rag_specialist, "_rerankers", {})
    return db


# --- reordenacao ----------------------------------------------------------------------


def test_reordena_pelo_score_e_desempata_pela_ordem_original():
    hits = [_hit(1, "A", "nada"), _hit(2, "B", "sangria sangria"), _hit(3, "C", "sangria"), _hit(4, "D", "sangria")]
    out = reordenar("q", hits, RerankerFalso(), k=3)
    assert [h.secao for h in out] == ["B", "C", "D"]  # C e D empatam: vale a ordem da busca
    assert [h.rank for h in out] == [1, 2, 3]
    assert [h.score for h in out] == [2.0, 1.0, 1.0]
    assert all(h.modo == "hibrido+rerank" for h in out)


def test_reordenar_vazio_e_contagem_errada():
    assert reordenar("q", [], RerankerFalso(), 5) == []

    class Quebrado(RerankerFalso):
        def score(self, pergunta, textos):
            return [1.0]

    with pytest.raises(ValueError, match="scores"):
        reordenar("q", [_hit(1, "A"), _hit(2, "B")], Quebrado(), 2)


def test_busca_larga_rerank_estreito(indice):
    conn = open_index(indice)
    try:
        out = buscar_com_rerank(conn, "caixa abertura fechamento sangria", reranker=RerankerFalso(),
                                modo="bm25", k=5, candidatos=20)
    finally:
        conn.close()
    assert len(out) == 5 and out[0].secao == "2. Sangria"
    assert isinstance(RerankerFalso(), Reranker)


# --- metricas e veredito ------------------------------------------------------------------


def test_posicao_de_todas_as_fontes():
    r = [("a", "1"), ("b", "2"), ("c", "3")]
    assert evaluate.posicao_de_todas(r, {("b", "2")}) == 2
    assert evaluate.posicao_de_todas(r, {("a", "1"), ("c", "3")}) == 3  # so respondivel com as duas
    assert evaluate.posicao_de_todas(r, {("z", "9")}) is None


def test_metricas_e_percentil():
    m = evaluate.metricas([1, 2, None, 5])
    assert (m["recall@1"], m["recall@3"], m["recall@5"]) == (1, 2, 3)
    assert m["mrr"] == pytest.approx((1 + 0.5 + 0 + 0.2) / 4)
    assert evaluate.percentil([0.1, 0.2, 0.3, 0.4, 1.0] * 4, 0.95) == 1.0
    assert evaluate.percentil(list(range(1, 101)), 0.95) == 95


def _r(mrr_sem, mrr_com, r5_sem=16, r5_com=16, p95=1.0):
    base = {"recall@1": 0, "recall@3": 0, "n": 17}
    return {"sem": {**base, "recall@5": r5_sem, "mrr": mrr_sem}, "com": {**base, "recall@5": r5_com, "mrr": mrr_com},
            "p95_s": p95}


def test_veredito_exige_os_quatro_criterios():
    assert all(evaluate.veredito_rerank(_r(0.5, 0.6), 1000).values())
    casos = {
        "a)": _r(0.6, 0.6),  # MRR igual nao basta (estritamente maior)
        "b)": _r(0.5, 0.7, r5_com=15),
        "c)": _r(0.5, 0.7, p95=1.51),
    }
    for criterio, r in casos.items():
        v = evaluate.veredito_rerank(r, 1000)
        assert [c for c, ok in v.items() if not ok] == [next(c for c in v if c.startswith(criterio))]
    v = evaluate.veredito_rerank(_r(0.5, 0.7), 2049)
    assert [c for c, ok in v.items() if not ok] == [next(c for c in v if c.startswith("d)"))]


def test_comparar_rerank_mesmos_candidatos_e_latencia(indice):
    tempos = iter(range(10_000))
    perguntas = evaluate.carregar_perguntas(GABARITO)
    conn = open_index(indice)
    try:
        r = evaluate.comparar_rerank(conn, perguntas, FakeEmbedder(), RerankerFalso("caixa"), repeticoes=2,
                                     relogio=lambda: float(next(tempos)))
    finally:
        conn.close()
    assert r["sem"]["n"] == r["com"]["n"] == 17
    assert len(r["latencias_s"]) == 34 and r["p95_s"] == 1.0  # relogio falso: cada medicao = 1 s
    md = evaluate.relatorio_rerank(r, 900.0, "falso")
    assert "MRR@20" in md and "Veredito" in md


# --- no do grafo: liga/desliga e fallback -----------------------------------------------------


def test_config_rerank_desligado_por_padrao():
    s = Settings(_env_file=None)
    assert s.rag_rerank_model is None and s.rag_rerank_candidatos == 20
    assert Settings(_env_file=None, rag_rerank_model="  ").rag_rerank_model is None


def test_no_aplica_o_rerank_configurado(indice, monkeypatch):
    falso = RerankerFalso("sangria")
    monkeypatch.setattr(settings, "rag_rerank_model", "modelo-x")
    monkeypatch.setattr(rag_specialist, "reranker_factory", lambda nome, cache: falso)
    hits = rag_specialist.buscar_trechos("caixa abertura fechamento sangria")
    assert hits[0].secao == "2. Sangria" and hits[0].modo == "bm25+rerank" and len(hits) == 5
    rag_specialist.buscar_trechos("caixa")
    assert falso.chamadas == 2  # carregado 1 vez, usado 2


def test_modelo_que_nao_carrega_cai_para_a_busca_sem_rerank(indice, monkeypatch, caplog):
    monkeypatch.setattr(settings, "rag_rerank_model", "modelo-quebrado")
    sem = rag_specialist.buscar_trechos("caixa abertura fechamento sangria")

    def falha(nome, cache):
        raise ImportError("sem fastembed")

    monkeypatch.setattr(rag_specialist, "reranker_factory", falha)
    with caplog.at_level(logging.WARNING, logger="orchestrator.graph.rag_specialist"):
        com_falha = rag_specialist.buscar_trechos("caixa abertura fechamento sangria")
    assert [h.chave for h in com_falha] == [h.chave for h in sem[:5]]
    assert "nao carregou" in caplog.text and "SEM rerank" in caplog.text


def test_score_que_falha_cai_para_a_busca_sem_rerank(indice, monkeypatch, caplog):
    class Explode(RerankerFalso):
        def score(self, pergunta, textos):
            raise RuntimeError("onnx")

    monkeypatch.setattr(settings, "rag_rerank_model", "modelo-x")
    monkeypatch.setattr(rag_specialist, "reranker_factory", lambda nome, cache: Explode())
    with caplog.at_level(logging.WARNING, logger="orchestrator.graph.rag_specialist"):
        hits = rag_specialist.buscar_trechos("caixa abertura fechamento sangria")
    assert len(hits) == 5 and all(h.modo == "bm25" for h in hits)
    assert "reranker falhou" in caplog.text


def test_sem_modelo_configurado_nada_e_carregado(indice, monkeypatch):
    monkeypatch.setattr(rag_specialist, "reranker_factory", lambda *a: pytest.fail("carregou reranker"))
    assert len(rag_specialist.buscar_trechos("caixa abertura fechamento sangria")) == 5


@pytest.mark.asyncio
async def test_rag_desligado_nunca_carrega_o_reranker(indice, monkeypatch):
    monkeypatch.setattr(settings, "rag_enabled", False)
    monkeypatch.setattr(settings, "rag_rerank_model", "modelo-x")
    monkeypatch.setattr(rag_specialist, "reranker_factory", lambda *a: pytest.fail("carregou com o rag desligado"))
    out = await specialist_rag_node({"messages": [], "pending_specialists": [{"specialist": "rag", "instructions": "q"}]})
    assert out["last_error"] == "especialista rag desligado neste ambiente"
