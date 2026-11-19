"""Portugues no BM25 (Missao 4): stopwords, stemming e as 4 variantes.

Embedder falso (o de test_rag_engine); nada de modelo real. A comparacao
real das variantes roda fora do pytest:
`python -m orchestrator.rag.evaluate --comparar-variantes`.
"""

from pathlib import Path

import pytest
from test_rag_engine import FakeEmbedder

from orchestrator.rag import evaluate, ingest
from orchestrator.rag.chunking import chunk_corpus
from orchestrator.rag.search import fts_query_normalizada, search
from orchestrator.rag.store import build_index, open_index, read_bm25_config
from orchestrator.rag.text import (
    DEFAULT_BM25,
    PRESERVADAS,
    STOPWORDS,
    VARIANTES,
    Bm25Config,
    normalizar,
    tokens,
)

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "rag" / "supermercado"
GABARITO = CORPUS.parent / "gabarito.yaml"
SO_STOP = Bm25Config(stopwords=True, stemming=False)
SO_STEM = Bm25Config(stopwords=False, stemming=True)
AMBOS = Bm25Config(stopwords=True, stemming=True)
BASELINE = Bm25Config(stopwords=False, stemming=False)


@pytest.fixture(scope="module")
def chunks():
    return chunk_corpus(CORPUS, "supermercado")


def _indice(tmp_path, chunks, cfg):
    db = tmp_path / f"{cfg.nome}.sqlite"
    build_index(chunks, FakeEmbedder(), db, cfg)
    return open_index(db)


# --- stopwords ------------------------------------------------------------------


@pytest.mark.parametrize(
    "palavra", ["não", "nao", "nunca", "sem", "só", "so", "antes", "depois", "até", "ate", "acima", "abaixo"]
)
def test_negacao_e_limite_nunca_sao_stopword(palavra):
    """Num manual, "nao aceitar" e "aceitar" sao opostos."""
    assert [t for t, _ in tokens(palavra, SO_STOP)] == [normalizar(palavra, BASELINE)]


def test_lista_de_preservadas_nao_cruza_com_stopwords():
    assert not (PRESERVADAS & STOPWORDS)
    assert {"nao", "nunca", "sem", "so", "antes", "depois", "ate", "acima", "abaixo"} <= PRESERVADAS


def test_negacao_sobrevive_no_contexto():
    assert normalizar("Não aceitar a carga acima de −12 °C", SO_STOP) == "nao aceitar carga acima 12 c"


def test_stopwords_comparadas_sem_acento():
    assert normalizar("você está aí? voce esta ai", SO_STOP) == ""


# --- stemming e normalizacao ------------------------------------------------------


def test_stemming_junta_flexoes_e_ignora_acento():
    assert normalizar("troca trocar trocas trocou", SO_STEM) == "troc troc troc troc"
    # com acento (indice) e sem acento (pergunta de WhatsApp) dao o mesmo radical
    assert normalizar("diluição", SO_STEM) == normalizar("diluicao", SO_STEM)


@pytest.mark.parametrize("cfg", VARIANTES)
def test_codigos_passam_intactos_em_todas_as_variantes(cfg):
    termos = tokens("veja o POP-06, o F-18 e a Q-22 e o P-05", cfg)
    assert [t for t, codigo in termos if codigo] == ["pop 06", "f 18", "q 22", "p 05"]


@pytest.mark.parametrize("cfg", [SO_STOP, SO_STEM, AMBOS])
def test_query_normalizada_e_segura(cfg):
    q = fts_query_normalizada('NEAR("x" * -y) : AND OR "', cfg)
    assert '""' not in q and q.count('"') % 2 == 0
    for parte in q.split(" OR "):
        assert parte.startswith('"') and parte.endswith('"') and '"' not in parte[1:-1]


# --- indice e consulta usam a MESMA variante --------------------------------------


@pytest.mark.parametrize("cfg", VARIANTES)
def test_variante_fica_na_meta_do_indice(tmp_path, chunks, cfg):
    conn = _indice(tmp_path, chunks, cfg)
    try:
        assert read_bm25_config(conn) == cfg
    finally:
        conn.close()


def test_indice_da_missao_3_sem_chaves_na_meta_e_baseline(tmp_path, chunks):
    import sqlite3

    db = tmp_path / "antigo.sqlite"
    build_index(chunks, FakeEmbedder(), db, BASELINE)
    with sqlite3.connect(db) as w:
        w.execute("DELETE FROM meta WHERE chave LIKE 'bm25_%'")
    w.close()
    conn = open_index(db)
    try:
        assert read_bm25_config(conn) == BASELINE
    finally:
        conn.close()


def test_busca_aplica_na_consulta_a_variante_do_indice(tmp_path, chunks):
    """"trocar" (pergunta) so casa com "troca" (manual) se o stemming rodar
    nos DOIS lados - a busca le a variante da meta, nao de um parametro."""
    alvo = ("pop-03-troca-e-devolucao.md", "1. Onde é feita a troca")
    for cfg, acha in ((BASELINE, False), (SO_STEM, True)):
        conn = _indice(tmp_path, chunks, cfg)
        try:
            achados = [h.chave for h in search(conn, "trocar", modo="bm25", k=50)]
        finally:
            conn.close()
        assert (alvo in achados) is acha, cfg


def test_padrao_e_so_stemming_e_ingest_usa_o_padrao():
    assert DEFAULT_BM25 == SO_STEM
    args = ingest.parse_args([])
    assert (args.stopwords, args.stemming) == (DEFAULT_BM25.stopwords, DEFAULT_BM25.stemming)
    args = ingest.parse_args(["--stopwords", "--no-stemming"])
    assert (args.stopwords, args.stemming) == (True, False)


# --- "onde fica o F-18?" -----------------------------------------------------------


@pytest.mark.parametrize("cfg", [SO_STOP, AMBOS])
def test_f18_com_onde_acerta_nas_variantes_com_stopwords(tmp_path, chunks, cfg):
    """O xfail strict de test_rag_engine continua (o padrao, so stemming, nao
    tira o "onde"); aqui fica provado que as stopwords resolvem o caso."""
    conn = _indice(tmp_path, chunks, cfg)
    try:
        topo = search(conn, "onde fica o F-18?", modo="bm25")[0].chave
    finally:
        conn.close()
    assert topo == ("pop-07-precos-e-promocoes.md", "3. Divergência entre etiqueta e caixa")


# --- comparacao das variantes ------------------------------------------------------


def test_comparar_variantes_vetorial_e_controle(chunks):
    """O vetorial nao depende da variante do BM25: se mudar, algo esta errado."""
    perguntas = evaluate.carregar_perguntas(GABARITO)
    por_variante = evaluate.comparar_variantes(chunks, perguntas, FakeEmbedder())
    assert list(por_variante) == ["baseline", "stopwords", "stemming", "stopwords+stemming"]
    vetorial = {
        nome: [(r.id, r.top, r.posicao_das_fontes) for r in rs if r.modo == "vetorial"]
        for nome, rs in por_variante.items()
    }
    assert all(v == vetorial["baseline"] for v in vetorial.values())
    md = evaluate.relatorio_variantes(por_variante)
    assert md.count("\n| ") >= 4 and "Mudancas em relacao ao baseline" in md
