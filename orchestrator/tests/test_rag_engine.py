"""Motor de busca do RAG (chunking, indice, 3 modos de busca, avaliacao).

Tudo com um embedder FALSO e deterministico (hash de palavras): nenhum
modelo e baixado nem carregado. O conftest torna `import fastembed` /
`import onnxruntime` um ImportError na suite inteira, entao um teste que use
o embedder real por engano falha - em vez de passar offline com o modelo do
cache em data/. Avaliacao real: `python -m orchestrator.rag.evaluate`.
"""

import hashlib
import math
import re
import sqlite3
from pathlib import Path

import pytest
import yaml
from test_rag_fixtures import _secoes

from orchestrator.rag import chunking, evaluate, ingest
from orchestrator.rag.chunking import Chunk, chunk_corpus, chunk_markdown
from orchestrator.rag.embeddings import Embedder, FastEmbedEmbedder
from orchestrator.rag.search import fts_query, rrf_fuse, search
from orchestrator.rag.store import (
    IndexMismatchError,
    build_index,
    open_index,
    read_meta,
)
from orchestrator.rag.text import DEFAULT_BM25

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rag"
CORPUS = FIXTURES / "supermercado"
GABARITO = FIXTURES / "gabarito.yaml"


class FakeEmbedder:
    """Bag-of-words com hash (sha256) em `dim` posicoes, normalizado.
    Deterministico entre processos (nao usa `hash()`, que e aleatorizado)."""

    def __init__(self, model_name: str = "fake-hash-embedder", dim: int = 64):
        self.model_name = model_name
        self.dim = dim
        self.chamadas = 0

    def _vetor(self, texto: str) -> list[float]:
        v = [0.0] * self.dim
        for palavra in re.findall(r"\w+", texto.lower()):
            v[int(hashlib.sha256(palavra.encode()).hexdigest(), 16) % self.dim] += 1.0
        norma = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norma for x in v]

    def embed_documents(self, textos):
        self.chamadas += 1
        return [self._vetor(t) for t in textos]

    def embed_query(self, texto):
        return self._vetor(texto)


@pytest.fixture(scope="module")
def chunks() -> list[Chunk]:
    return chunk_corpus(CORPUS, "supermercado")


@pytest.fixture
def indice(tmp_path, chunks):
    db = tmp_path / "rag_index.sqlite"
    build_index(chunks, FakeEmbedder(), db)
    conn = open_index(db)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def perguntas_com_fonte() -> list[dict]:
    return [p for p in yaml.safe_load(GABARITO.read_text(encoding="utf-8"))["perguntas"] if p["secao_fonte"]]


# --- chunking -----------------------------------------------------------------


def test_um_chunk_por_secao_mais_o_preambulo(chunks):
    for caminho in sorted(CORPUS.glob("*.md")):
        texto = caminho.read_text(encoding="utf-8")
        n_secoes = len(re.findall(r"^## ", texto, re.MULTILINE))
        do_arquivo = [c for c in chunks if c.arquivo == caminho.name]
        assert len(do_arquivo) == n_secoes + 1, caminho.name  # +1 = preambulo
        titulo = re.search(r"^# (.+)$", texto, re.MULTILINE).group(1).strip()
        assert do_arquivo[0].secao == titulo


def test_preambulo_do_pop07_e_chunk_proprio_com_a_revogacao_do_pop06(chunks):
    """q13: a resposta mora entre o titulo # e a primeira ##."""
    pre = next(c for c in chunks if c.chave == ("pop-07-precos-e-promocoes.md", "POP-07 — Preços, Etiquetas e Promoções"))
    assert "POP-06" in pre.texto and "revogado em 2025" in pre.texto
    assert "## " not in pre.texto  # termina antes da primeira secao


def test_chunk_guarda_arquivo_secao_texto_colecao(chunks):
    sangria = next(c for c in chunks if c.secao == "2. Sangria")
    assert sangria.arquivo == "pop-04-abertura-e-fechamento-de-caixa.md"
    assert sangria.colecao == "supermercado"
    assert sangria.texto.startswith("## 2. Sangria")
    assert "## 3." not in sangria.texto
    assert sangria.texto_indexado().startswith("POP-04 — Abertura e Fechamento de Caixa\n## 2. Sangria")


def test_contrato_cada_fonte_do_gabarito_e_exatamente_um_chunk(chunks, perguntas_com_fonte):
    """Sem isto o recall mente: uma fonte que nao vira chunk (ou vira dois)
    nunca casa, ou casa por acaso."""
    assert len(perguntas_com_fonte) == 17
    for p in perguntas_com_fonte:
        for chave in zip(p["arquivo_fonte"], p["secao_fonte"], strict=True):
            assert sum(c.chave == chave for c in chunks) == 1, f"{p['id']}: {chave}"


def test_chunker_concorda_com_as_secoes_do_teste_de_fixtures(chunks):
    """Mesmo recorte nos dois lados: o `_secoes` (que valida o gabarito) e o
    chunker de producao (que alimenta o indice)."""
    for c in chunks:
        assert _secoes(CORPUS / c.arquivo)[c.secao].strip() == c.texto, c.chave


def test_preambulo_vazio_subsecao_e_bloco_de_codigo():
    md = "# Titulo\n## 1. A\ntexto a\n### 1.1 sub\ntexto sub\n```\n## nao e cabecalho\n```\n## 2. B\ntexto b\n"
    out = chunk_markdown(md, "x.md", "c")
    assert [c.secao for c in out] == ["1. A", "2. B"]  # sem preambulo; ### e ``` ficam dentro de "1. A"
    assert "texto sub" in out[0].texto and "## nao e cabecalho" in out[0].texto


def test_secao_duplicada_no_corpus_e_recusada(tmp_path):
    (tmp_path / "a.md").write_text("# T\n## 1. X\na\n## 1. X\nb\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicadas"):
        chunk_corpus(tmp_path, "c")


# --- indice -------------------------------------------------------------------


def test_indice_grava_meta_e_todos_os_chunks(indice, chunks):
    meta = read_meta(indice)
    assert meta["model_name"] == "fake-hash-embedder" and meta["dim"] == "64"
    assert int(meta["n_chunks"]) == len(chunks) == 46
    for tabela in ("chunks", "chunks_fts", "chunks_vec"):
        assert indice.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0] == 46


def test_indice_aberto_so_para_leitura(indice):
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        indice.execute("DELETE FROM chunks")


def test_rebuild_falho_no_meio_nao_estraga_o_indice_anterior(tmp_path, chunks):
    """A falha acontece DENTRO da escrita, com o arquivo temporario ja criado
    e parcialmente gravado: o chunk repetido viola o UNIQUE (colecao,
    arquivo, secao) no segundo INSERT. O indice antigo tem de sair intacto e
    o temporario tem de sumir."""
    db = tmp_path / "rag_index.sqlite"
    build_index(chunks, FakeEmbedder(), db)
    antes = db.read_bytes()

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        build_index([chunks[0], chunks[0]], FakeEmbedder("outro"), db)

    assert db.read_bytes() == antes
    conn = open_index(db)
    assert read_meta(conn)["model_name"] == "fake-hash-embedder" and read_meta(conn)["n_chunks"] == "46"
    conn.close()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rag_index.sqlite"]  # sem .tmp sobrando


def test_embedder_com_dimensao_errada_e_recusado_antes_de_escrever(tmp_path, chunks):
    class Quebrado(FakeEmbedder):
        def embed_documents(self, textos):
            return [[0.0] * (self.dim - 1) for _ in textos]

    with pytest.raises(ValueError, match="dimensao"):
        build_index(chunks[:3], Quebrado(), tmp_path / "rag_index.sqlite")
    assert list(tmp_path.iterdir()) == []


def test_rebuild_substitui_o_indice(tmp_path, chunks):
    db = tmp_path / "rag_index.sqlite"
    build_index(chunks, FakeEmbedder(), db)
    build_index(chunks[:5], FakeEmbedder("outro", dim=32), db)
    conn = open_index(db)
    assert read_meta(conn) == {
        "schema_version": "2",
        "model_name": "outro",
        "dim": "32",
        "n_chunks": "5",
        "bm25_stopwords": str(int(DEFAULT_BM25.stopwords)),
        "bm25_stemming": str(int(DEFAULT_BM25.stemming)),
    }
    conn.close()


def test_busca_recusa_embedder_diferente_do_da_ingestao(indice):
    for outro in (FakeEmbedder("outro-modelo", 64), FakeEmbedder("fake-hash-embedder", 32)):
        for modo in ("vetorial", "hibrido"):
            with pytest.raises(IndexMismatchError):
                search(indice, "sangria", modo=modo, embedder=outro)


def test_indice_inexistente_da_erro_claro(tmp_path):
    with pytest.raises(FileNotFoundError, match="rag.ingest"):
        open_index(tmp_path / "nao-existe.sqlite")


def test_ingest_recusa_o_checkpoints_e_fica_fora_dele(tmp_path):
    assert ingest.main(["--db", str(tmp_path / "checkpoints.sqlite")]) == 2
    assert not (tmp_path / "checkpoints.sqlite").exists()
    assert ingest.DEFAULT_DB.name == "rag_index.sqlite"
    assert ingest.DEFAULT_DB.parent.name == "data"


# --- busca --------------------------------------------------------------------


def test_fts_query_codigo_vira_frase_e_operadores_nao_passam():
    assert fts_query("olha o POP-06 e o f-12") == '"pop 06" OR "f 12" OR "olha" OR "o" OR "e"'
    q = fts_query('NEAR(x* -y : "z") AND OR')
    assert q == '"near" OR "x" OR "y" OR "z" OR "and" OR "or"'


@pytest.mark.parametrize("pergunta", ['"', "*", "-:()", "", "   ", 'NEAR("a" "b")', "a AND", "^x", "col:valor"])
def test_bm25_nao_quebra_com_entrada_hostil(indice, pergunta):
    search(indice, pergunta, modo="bm25")


def test_bm25_sem_termo_devolve_vazio(indice):
    assert search(indice, "?!", modo="bm25") == []


@pytest.mark.parametrize(
    ("pergunta", "esperado"),
    [
        ("alguem falou do POP-06", ("pop-07-precos-e-promocoes.md", "POP-07 — Preços, Etiquetas e Promoções")),
        pytest.param(
            "onde fica o F-18?",
            ("pop-07-precos-e-promocoes.md", "3. Divergência entre etiqueta e caixa"),
            marks=pytest.mark.xfail(strict=True, reason="BM25 sem stopwords em português: 'onde' puxa outra seção"),
        ),
        ("sangria", ("pop-04-abertura-e-fechamento-de-caixa.md", "2. Sangria")),
        ("ferias diluicao", ("pop-05-higienizacao-e-seguranca-alimentar.md", "2. Diluição dos produtos de limpeza")),
    ],
)
def test_bm25_acha_codigo_exato_e_ignora_acento(indice, pergunta, esperado):
    assert search(indice, pergunta, modo="bm25")[0].chave == esperado


def test_vetorial_acha_o_proprio_texto_do_chunk(indice, chunks):
    alvo = next(c for c in chunks if c.secao == "6. Descongelamento")
    hits = search(indice, alvo.texto_indexado(), modo="vetorial", embedder=FakeEmbedder())
    assert hits[0].chave == alvo.chave
    assert hits[0].score == pytest.approx(0.0, abs=1e-5)  # distancia cosseno


def test_rrf_soma_pela_posicao_e_desempata_deterministico():
    fused = rrf_fuse([[1, 2, 3], [3, 1]], k_rrf=60)
    assert [doc for doc, _ in fused] == [1, 3, 2]
    assert dict(fused)[1] == pytest.approx(1 / 61 + 1 / 62)
    assert dict(fused)[3] == pytest.approx(1 / 63 + 1 / 61)
    assert dict(fused)[2] == pytest.approx(1 / 62)
    # empate exato de score: ganha a melhor posicao individual, depois o menor id
    assert [d for d, _ in rrf_fuse([[7, 8], [8, 7]])] == [7, 8]


def test_hibrido_junta_os_dois_rankings(indice):
    """Codigo exato (forte no BM25) + texto: o hibrido tem de trazer o chunk
    do F-18 no topo mesmo com o vetorial do embedder falso espalhado."""
    hits = search(indice, "F-18", modo="hibrido", embedder=FakeEmbedder())
    assert hits[0].chave == ("pop-07-precos-e-promocoes.md", "3. Divergência entre etiqueta e caixa")
    assert len(hits) == 5 and len({h.chave for h in hits}) == 5
    assert [h.rank for h in hits] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("modo", ["vetorial", "bm25", "hibrido"])
def test_colecao_filtra_nos_tres_modos(tmp_path, chunks, modo):
    outra = [Chunk(c.arquivo, c.secao, c.texto, "outra", c.titulo_documento) for c in chunks[:4]]
    db = tmp_path / "rag_index.sqlite"
    build_index([*chunks, *outra], FakeEmbedder(), db)
    conn = open_index(db)
    try:
        hits = search(conn, "POP-01 recebimento doca", modo=modo, embedder=FakeEmbedder(), k=10, colecao="outra")
        assert hits and {h.colecao for h in hits} == {"outra"} and len(hits) == 4
        assert search(conn, "sangria", modo=modo, embedder=FakeEmbedder(), colecao="inexistente") == []
    finally:
        conn.close()


def test_modo_que_usa_vetor_exige_embedder(indice):
    with pytest.raises(ValueError, match="precisa de embedder"):
        search(indice, "sangria", modo="hibrido")
    with pytest.raises(ValueError, match="modo invalido"):
        search(indice, "sangria", modo="semantico", embedder=FakeEmbedder())


# --- avaliacao ----------------------------------------------------------------


def test_recall_exige_todas_as_fontes_e_compara_pelo_par_arquivo_secao():
    a, b = ("a.md", "2. X"), ("b.md", "2. X")
    assert evaluate.recall_hit({a}, [b, a])
    assert not evaluate.recall_hit({a}, [b])  # mesma secao, arquivo errado
    assert not evaluate.recall_hit({a, b}, [a, ("c.md", "1"), ("d.md", "1"), ("e.md", "1"), ("f.md", "1"), b])
    assert evaluate.recall_hit({a, b}, [a, b], k=2)
    with pytest.raises(ValueError):
        evaluate.recall_hit(set(), [a])


def test_avaliacao_usa_as_17_com_fonte_nos_3_modos(indice):
    perguntas = evaluate.carregar_perguntas(GABARITO)
    assert len(perguntas) == 17 and not {"q18", "q19", "q20"} & {p["id"] for p in perguntas}
    resultados = evaluate.avaliar(indice, perguntas, FakeEmbedder())
    assert len(resultados) == 51
    resumo = evaluate.resumo(resultados)
    for modo in ("vetorial", "bm25", "hibrido"):
        assert resumo[modo]["total"][1] == 17
        assert resumo[modo]["direta"][1] == 14 and resumo[modo]["multi_secao"][1] == 3
    for r in resultados:
        assert r.acertou == all(pos is not None and pos <= 5 for pos in r.posicao_das_fontes.values())
    md = evaluate.relatorio_markdown(resultados)
    assert "| Só vetorial |" in md and "| Só BM25 (FTS5) |" in md and "| Híbrido (RRF) |" in md


# --- isolamento ---------------------------------------------------------------


def test_embedder_real_e_bloqueado_na_suite():
    """O modelo pode estar no cache (data/fastembed_cache): sem este bloqueio,
    um teste com o embedder real rodaria offline e passaria escondido."""
    with pytest.raises(ImportError):
        FastEmbedEmbedder()


def test_importar_o_rag_nao_carrega_fastembed(tmp_path):
    """Processo filho limpo (na suite o conftest ja bloqueia o import). cwd
    vazio: nada de `.env` por perto."""
    import subprocess
    import sys

    codigo = (
        "import sys, orchestrator.rag, orchestrator.rag.evaluate, orchestrator.rag.ingest; "
        "print(sorted(m for m in ('fastembed', 'onnxruntime') if m in sys.modules))"
    )
    saida = subprocess.run(
        [sys.executable, "-c", codigo], capture_output=True, text=True, check=True, timeout=60, cwd=tmp_path
    )
    assert saida.stdout.strip() == "[]"


def test_fake_embedder_cumpre_o_protocolo():
    assert isinstance(FakeEmbedder(), Embedder)
    assert chunking.Chunk is Chunk
