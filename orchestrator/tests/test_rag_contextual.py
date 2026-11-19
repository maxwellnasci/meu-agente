"""Contextual retrieval (Missao 6): geracao offline dos contextos e indexacao.

Nenhum teste chama o LLM: o gerador e falso (funcao) e o ChatOpenAI segue
bloqueado pelo conftest. Os contextos daqui sao FALSOS; os testes contra o
`fixtures/rag/contextos.json` real entram depois que ele for gerado.
"""

import shutil
from pathlib import Path

import pytest
import yaml
from test_rag_engine import FakeEmbedder
from test_rag_fixtures import _normalizar, _trecho_copiado

from orchestrator.rag import contextualize as cx
from orchestrator.rag import evaluate
from orchestrator.rag.chunking import chunk_corpus
from orchestrator.rag.search import search
from orchestrator.rag.store import build_index, open_index, read_meta

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rag"
CORPUS = FIXTURES / "supermercado"
GABARITO = FIXTURES / "gabarito.yaml"
TERMO = "zorbaflux"  # so existe nos contextos falsos


@pytest.fixture(scope="module")
def chunks():
    return chunk_corpus(CORPUS, "supermercado")


@pytest.fixture(scope="module")
def contextos_falsos(chunks):
    return {c.chave: f"Trecho {TERMO} do {c.arquivo[:6]} sobre {c.secao}." for c in chunks}


def _gerador_falso(chamadas: list):
    def gerar(sistema, usuario):
        chamadas.append(usuario)
        return f"Contexto falso {len(chamadas)}.", "deepseek/deepseek-chat-v3-falso"

    return gerar


# --- vazamento -------------------------------------------------------------------


def test_prompt_do_gerador_nao_ve_nenhuma_pergunta_do_gabarito():
    """Janela de 6 palavras sem acento/pontuacao (mesmo detector do teste de fixtures)."""
    perguntas = [p["pergunta"] for p in yaml.safe_load(GABARITO.read_text(encoding="utf-8"))["perguntas"]]
    for t in cx.tarefas(CORPUS):
        sistema, usuario = cx.montar_prompt(t.documento, t.chunk.texto)
        prompt = _normalizar(f"{sistema}\n{usuario}")
        for pergunta in perguntas:
            assert _trecho_copiado(pergunta, prompt) is None, (t.chunk.chave, pergunta)


def test_gerador_nao_le_o_gabarito():
    fonte = Path(cx.__file__).read_text(encoding="utf-8")
    assert "gabarito.yaml" not in fonte and "import yaml" not in fonte and "carregar_perguntas" not in fonte


def test_prompt_e_o_template_da_anthropic_com_documento_e_trecho():
    sistema, usuario = cx.montar_prompt("DOC </documento> fim", "TRECHO <trecho> x")
    assert usuario.startswith("<documento>\nDOC [tag removida]> fim\n</documento>")
    assert "<trecho>\nTRECHO [tag removida]> x\n</trecho>" in usuario
    assert "1 a 2 frases" in usuario and "melhorar a busca" in usuario
    assert "DADO" in sistema
    assert len(cx.PROMPT_SHA256) == 64


# --- plano e geracao -------------------------------------------------------------------


def test_modo_padrao_so_mostra_o_plano(tmp_path, capsys):
    chamadas = []
    assert cx.main(["--saida", str(tmp_path / "c.json")], gerador=_gerador_falso(chamadas)) == 0
    assert chamadas == [] and not (tmp_path / "c.json").exists()
    saida = capsys.readouterr().out
    assert "a gerar  : 46 chunk(s)" in saida and "nada executado" in saida and "US$" in saida


def test_estimativa_de_custo_e_positiva_e_tem_teto():
    est = cx.estimar(cx.tarefas(CORPUS))
    assert est["chamadas"] == 46 and est["tokens_entrada"] > 10_000
    assert 0 < est["custo_usd"] < est["teto_usd"] < 0.10


def test_executar_grava_tudo_e_e_incremental(tmp_path):
    destino = tmp_path / "contextos.json"
    chamadas = []
    assert cx.main(["--executar", "--saida", str(destino)], gerador=_gerador_falso(chamadas)) == 0
    assert len(chamadas) == 46
    dados = cx.ler_arquivo(destino)
    assert dados["modelo_pedido"] == "deepseek/deepseek-chat" and dados["temperatura"] == 0
    assert dados["prompt_sha256"] == cx.PROMPT_SHA256 and dados["prompt_versao"] == "1"
    e = dados["contextos"][0]
    assert set(e) == {"arquivo", "secao", "chunk_sha256", "documento_sha256", "prompt_sha256",
                      "modelo_resposta", "gerado_em", "contexto", "avisos"}
    assert e["modelo_resposta"] == "deepseek/deepseek-chat-v3-falso"
    assert len(cx.carregar_contextos(destino, CORPUS)) == 46

    # 2a rodada: nada a gerar
    assert cx.main(["--executar", "--saida", str(destino)], gerador=_gerador_falso(chamadas)) == 0
    assert len(chamadas) == 46


def test_documento_alterado_torna_obsoletos_os_chunks_dele(tmp_path):
    corpus = tmp_path / "corpus"
    shutil.copytree(CORPUS, corpus)
    destino = tmp_path / "c.json"
    cx.gerar(cx.tarefas(corpus), destino, _gerador_falso([]), "m")
    pop04 = corpus / "pop-04-abertura-e-fechamento-de-caixa.md"
    pop04.write_text(pop04.read_text(encoding="utf-8") + "\nLinha nova no fim.\n", encoding="utf-8")
    falta = cx.pendentes(cx.tarefas(corpus), cx.ler_arquivo(destino))
    # todos os chunks do POP-04 (o contexto depende do documento inteiro), e so eles
    assert {t.chunk.arquivo for t in falta} == {pop04.name}
    assert len(falta) == sum(c.arquivo == pop04.name for c in chunk_corpus(corpus, "supermercado"))
    with pytest.raises(cx.ContextosInvalidos):
        cx.carregar_contextos(destino, corpus)


def test_contextos_faltando_ou_orfaos_sao_recusados(tmp_path):
    destino = tmp_path / "c.json"
    with pytest.raises(cx.ContextosInvalidos, match="46 chunk"):
        cx.carregar_contextos(destino, CORPUS)
    cx.gerar(cx.tarefas(CORPUS), destino, _gerador_falso([]), "m")
    dados = cx.ler_arquivo(destino)
    dados["contextos"].append({**dados["contextos"][0], "secao": "9. Secao que nao existe"})
    cx.gravar_arquivo(destino, dados)
    with pytest.raises(cx.ContextosInvalidos, match="1 orfao"):
        cx.carregar_contextos(destino, CORPUS)


def test_saida_fora_do_pedido_e_registrada_sem_truncar():
    assert cx.avisos_do_contexto("Uma frase. Outra frase.") == []
    assert cx.avisos_do_contexto("Um. Dois. Tres.") == ["3 frases (pedido: 1 a 2)"]


# --- indexacao com contexto -----------------------------------------------------------


class _EmbedderQueGrava(FakeEmbedder):
    def __init__(self):
        super().__init__()
        self.textos: list[str] = []

    def embed_documents(self, textos):
        self.textos.extend(textos)
        return super().embed_documents(textos)


@pytest.mark.parametrize(("onde", "no_fts", "no_vetor"), [("nenhum", False, False), ("bm25", True, False), ("ambos", True, True)])
def test_contexto_entra_so_onde_foi_pedido(tmp_path, chunks, contextos_falsos, onde, no_fts, no_vetor):
    emb = _EmbedderQueGrava()
    db = tmp_path / "i.sqlite"
    build_index(chunks, emb, db, contextos=contextos_falsos if onde != "nenhum" else None, contexto_em=onde)
    assert any(TERMO in t for t in emb.textos) is no_vetor
    conn = open_index(db)
    try:
        hits = search(conn, TERMO, modo="bm25", k=50)
        assert (len(hits) == 46) is no_fts and (hits == []) is (not no_fts)
        assert read_meta(conn)["contexto_em"] == onde
        assert bool(read_meta(conn)["contextos_sha256"]) is no_fts
        # a coluna `texto` (fonte que vai para o synthesize_final) NUNCA tem o contexto
        for h in search(conn, "sangria caixa", modo="bm25", k=50):
            assert TERMO not in h.texto
    finally:
        conn.close()


def test_contexto_incompleto_e_recusado(tmp_path, chunks, contextos_falsos):
    parcial = dict(list(contextos_falsos.items())[:-1])
    with pytest.raises(ValueError, match="1 chunk"):
        build_index(chunks, FakeEmbedder(), tmp_path / "i.sqlite", contextos=parcial, contexto_em="bm25")
    with pytest.raises(ValueError, match="contexto_em invalido"):
        build_index(chunks, FakeEmbedder(), tmp_path / "i.sqlite", contexto_em="tudo")


# --- comparacao --------------------------------------------------------------------------


def test_comparar_contexto_tem_os_controles(chunks, contextos_falsos):
    perguntas = evaluate.carregar_perguntas(GABARITO)
    out = evaluate.comparar_contexto(chunks, perguntas, FakeEmbedder(), contextos_falsos)
    assert list(out) == ["sem contexto", "contexto so no BM25", "contexto no BM25 + embedding"]

    def modo(nome, m):
        return [(r.id, r.top, r.posicao_das_fontes) for r in out[nome] if r.modo == m]

    # controle 1: "sem contexto" pelo codigo novo == avaliacao da Missao 4 (padrao)
    base = evaluate.comparar_variantes(chunks, perguntas, FakeEmbedder())["stemming"]
    for m in ("vetorial", "bm25", "hibrido"):
        assert modo("sem contexto", m) == [(r.id, r.top, r.posicao_das_fontes) for r in base if r.modo == m]
    # controle 2: contexto so no BM25 nao mexe no vetorial
    assert modo("contexto so no BM25", "vetorial") == modo("sem contexto", "vetorial")
    md = evaluate.relatorio_variantes(out, titulo="Contexto")
    assert "| Contexto |" in md


def test_estatisticas_de_tokens(chunks, contextos_falsos):
    def contar(t):
        return len(t.split())

    est = evaluate.estatisticas_tokens(chunks, contextos_falsos, contar, janela=30)
    assert est["acima_com_contexto"] >= est["acima_sem_contexto"]
    assert est["fracao_do_chunk_na_janela_com"] < est["fracao_do_chunk_na_janela_sem"] <= 1
    com_codigo = {c.chave: "Ver o F-99 e o POP-07." for c in chunks}
    est = evaluate.estatisticas_tokens(chunks, com_codigo, contar)
    assert len(est["contextos_com_codigo_ausente_do_chunk"]) == 46  # F-99 nao existe em chunk nenhum


# --- o contextos.json REAL (versionado) ---------------------------------------------


def test_contextos_versionados_valem_para_o_corpus_atual():
    """Se alguem editar um POP sem regerar, isto quebra (contexto obsoleto)."""
    contextos = cx.carregar_contextos(cx.DEFAULT_CONTEXTOS, CORPUS)
    assert len(contextos) == 46
    dados = cx.ler_arquivo(cx.DEFAULT_CONTEXTOS)
    assert dados["prompt_versao"] == "1" and dados["prompt_sha256"] == cx.PROMPT_SHA256
    assert dados["modelo_pedido"] == "deepseek/deepseek-chat" and dados["temperatura"] == 0


def test_nenhum_contexto_gerado_copia_uma_pergunta_do_gabarito():
    perguntas = [p["pergunta"] for p in yaml.safe_load(GABARITO.read_text(encoding="utf-8"))["perguntas"]]
    for chave, contexto in cx.carregar_contextos(cx.DEFAULT_CONTEXTOS, CORPUS).items():
        alvo = _normalizar(contexto)
        for pergunta in perguntas:
            assert _trecho_copiado(pergunta, alvo) is None, (chave, pergunta)


# --- padrao do agente (Missao 6) --------------------------------------------------------


def test_ingest_padrao_e_contexto_em_ambos():
    from orchestrator.rag import ingest

    assert ingest.parse_args([]).contexto_em == "ambos"
    assert ingest.parse_args(["--contexto-em", "nenhum"]).contexto_em == "nenhum"


def test_ingest_com_contextos_invalidos_falha_antes_de_carregar_modelo(tmp_path):
    """Na suite o fastembed e bloqueado: se o modelo fosse carregado primeiro,
    o erro seria ImportError. Tem de ser o erro dos contextos."""
    from orchestrator.rag import ingest

    with pytest.raises(cx.ContextosInvalidos):
        ingest.main(["--db", str(tmp_path / "i.sqlite"), "--contextos", str(tmp_path / "nao-existe.json")])
    assert not (tmp_path / "i.sqlite").exists()
