"""Consistencia do corpus ficticio e do gabarito do RAG MVP (fixtures/rag/).

Nao testa RAG nenhum - so garante que o gabarito usado para medir recall@5
aponta para arquivos e secoes que existem de verdade, com a distribuicao
combinada (14 diretas, 3 multi_secao, 3 sem_resposta). Se alguem editar um
titulo de secao no corpus, este teste quebra antes da avaliacao mentir.
"""

import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rag"
CORPUS = FIXTURES / "supermercado"
GABARITO = FIXTURES / "gabarito.yaml"

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _headings(path: Path) -> set[str]:
    return set(_HEADING.findall(path.read_text(encoding="utf-8")))


def _corpus_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in CORPUS.glob("*.md"))


@pytest.fixture(scope="module")
def perguntas() -> list[dict]:
    return yaml.safe_load(GABARITO.read_text(encoding="utf-8"))["perguntas"]


def test_corpus_tem_5_a_6_arquivos_md():
    assert 5 <= len(list(CORPUS.glob("*.md"))) <= 6


def test_corpus_tem_tabela_e_codigos_exatos():
    texto = _corpus_text()
    assert re.search(r"^\|.+\|\s*$\n^\|[-| :]+\|\s*$", texto, re.MULTILINE), "nenhuma tabela Markdown"
    for codigo in ("POP-07", "F-12"):
        assert codigo in texto


def test_gabarito_tem_20_perguntas_com_distribuicao_combinada(perguntas):
    assert len(perguntas) == 20
    assert Counter(p["tipo"] for p in perguntas) == {"direta": 14, "multi_secao": 3, "sem_resposta": 3}


def test_ids_unicos_e_campos_obrigatorios(perguntas):
    assert len({p["id"] for p in perguntas}) == 20
    for p in perguntas:
        for campo in ("pergunta", "resposta_esperada", "arquivo_fonte", "secao_fonte"):
            assert campo in p, f"{p['id']} sem {campo}"
        assert p["pergunta"].strip() and p["resposta_esperada"].strip()


def test_quantidade_de_fontes_por_tipo(perguntas):
    esperado = {"direta": 1, "multi_secao": 2, "sem_resposta": 0}
    for p in perguntas:
        assert len(p["arquivo_fonte"]) == len(p["secao_fonte"]) == esperado[p["tipo"]], p["id"]


def test_fontes_existem_no_corpus(perguntas):
    for p in perguntas:
        for arquivo, secao in zip(p["arquivo_fonte"], p["secao_fonte"], strict=True):
            caminho = CORPUS / arquivo
            assert caminho.is_file(), f"{p['id']}: arquivo inexistente {arquivo}"
            assert secao in _headings(caminho), f"{p['id']}: secao '{secao}' nao existe em {arquivo}"


def test_multi_secao_junta_duas_secoes_distintas(perguntas):
    for p in perguntas:
        if p["tipo"] == "multi_secao":
            assert len(set(zip(p["arquivo_fonte"], p["secao_fonte"], strict=True))) == 2, p["id"]


def test_perguntas_nao_copiam_o_manual(perguntas):
    """Pergunta de WhatsApp, nao trecho do manual: nenhuma sequencia de 6
    palavras seguidas da pergunta aparece literalmente no corpus."""
    corpus = " ".join(_corpus_text().lower().split())
    for p in perguntas:
        palavras = p["pergunta"].lower().split()
        for i in range(len(palavras) - 5):
            trecho = " ".join(palavras[i : i + 6])
            assert trecho not in corpus, f"{p['id']} copia o manual: '{trecho}'"
