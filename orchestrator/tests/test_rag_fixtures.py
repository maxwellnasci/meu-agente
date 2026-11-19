"""Consistencia do corpus ficticio e do gabarito do RAG MVP (fixtures/rag/).

Nao testa RAG nenhum - so garante que o gabarito usado para medir recall@5
aponta para arquivos e secoes que existem de verdade, com a distribuicao
combinada (14 diretas, 3 multi_secao, 3 sem_resposta), e que as perguntas
medem o que dizem medir:

- nenhuma pergunta copia o manual (comparacao sem acento, sem pontuacao e
  sem caixa, inclusive para perguntas curtas);
- todo codigo citado no gabarito (POP-xx, F-xx, Q-xx, P-xx) existe no corpus,
  e os citados na resposta de uma pergunta com fonte estao nas secoes-fonte;
- cada secao de uma `multi_secao` tem um trecho EXCLUSIVO e indispensavel na
  resposta (achar so uma das duas secoes nao basta para responder);
- cada `sem_resposta` declara o criterio de acerto.

Se alguem editar um titulo de secao no corpus, este teste quebra antes da
avaliacao mentir.
"""

import re
import unicodedata
from collections import Counter
from pathlib import Path

import pytest
import yaml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rag"
CORPUS = FIXTURES / "supermercado"
GABARITO = FIXTURES / "gabarito.yaml"

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_CODIGO = re.compile(r"\b(?:POP|F|Q|P)-\d{2}\b")
_JANELA = 6  # palavras seguidas iguais ao manual = copia


def _normalizar(texto: str) -> str:
    """Minusculas, sem acento, sem pontuacao/markdown, espacos colapsados."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return " ".join(re.sub(r"[^0-9a-z]+", " ", sem_acento.lower()).split())


def _secoes(path: Path) -> dict[str, str]:
    """Titulo -> texto da secao.

    Uma secao `##` vai do cabecalho ate o proximo `#`/`##`. O titulo `#` vai
    so ate a PRIMEIRA `##` (o preambulo), e nao ate o fim do arquivo: antes,
    "POP-07 — ..." continha o arquivo inteiro, e qualquer codigo de qualquer
    secao do POP-07 passava como "presente na secao-fonte" da q13. Mesmo
    recorte do chunker (`orchestrator.rag.chunking`)."""
    texto = path.read_text(encoding="utf-8")
    cabecalhos = list(_HEADING.finditer(texto))
    secoes = {}
    for i, m in enumerate(cabecalhos):
        corte = max(len(m.group(1)), 2)  # "#" e "##" param no proximo "#"/"##"
        fim = next((c.start() for c in cabecalhos[i + 1 :] if len(c.group(1)) <= corte), len(texto))
        secoes[m.group(2)] = texto[m.start() : fim]
    return secoes


def _corpus_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in CORPUS.glob("*.md"))


def _trecho_copiado(pergunta: str, corpus_normalizado: str) -> str | None:
    """Primeiro trecho da pergunta que aparece literalmente no corpus: janela
    de 6 palavras, ou a pergunta inteira quando ela tem menos de 6."""
    palavras = _normalizar(pergunta).split()
    alvo = f" {corpus_normalizado} "
    janelas = [palavras] if len(palavras) < _JANELA else [
        palavras[i : i + _JANELA] for i in range(len(palavras) - _JANELA + 1)
    ]
    for janela in janelas:
        trecho = " ".join(janela)
        if trecho and f" {trecho} " in alvo:
            return trecho
    return None


@pytest.fixture(scope="module")
def perguntas() -> list[dict]:
    return yaml.safe_load(GABARITO.read_text(encoding="utf-8"))["perguntas"]


def _textos_do_item(p: dict) -> str:
    campos = ("pergunta", "resposta_esperada", "armadilha", "aceita_tambem", "criterio_acerto")
    return " ".join(str(p.get(c, "")) for c in campos) + " " + " ".join(p.get("trecho_exclusivo") or [])


# --- estrutura ----------------------------------------------------------------


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
            assert secao in _secoes(caminho), f"{p['id']}: secao '{secao}' nao existe em {arquivo}"


def test_titulo_do_documento_vai_so_ate_a_primeira_secao(tmp_path):
    preambulo = _secoes(CORPUS / "pop-07-precos-e-promocoes.md")["POP-07 — Preços, Etiquetas e Promoções"]
    assert "POP-06" in preambulo
    assert "## " not in preambulo and "F-18" not in preambulo  # F-18 mora na secao 3

    md = tmp_path / "x.md"
    md.write_text("# T\npre\n## 1. A\na\n### 1.1 sub\ns\n## 2. B\nb\n", encoding="utf-8")
    assert _secoes(md) == {
        "T": "# T\npre\n",
        "1. A": "## 1. A\na\n### 1.1 sub\ns\n",  # a ### fica dentro da ##
        "1.1 sub": "### 1.1 sub\ns\n",
        "2. B": "## 2. B\nb\n",
    }


def test_multi_secao_junta_duas_secoes_distintas(perguntas):
    for p in perguntas:
        if p["tipo"] == "multi_secao":
            assert len(set(zip(p["arquivo_fonte"], p["secao_fonte"], strict=True))) == 2, p["id"]


# --- multi_secao: cada secao e indispensavel ---------------------------------


def test_multi_secao_cada_secao_tem_trecho_exclusivo_na_resposta(perguntas):
    """Achado da revisao (q15/q16): uma das secoes sozinha respondia tudo, e o
    recall de "as duas secoes" nao media nada. Cada secao precisa ter um
    trecho que SO ela contem e que a resposta esperada exige."""
    for p in perguntas:
        if p["tipo"] != "multi_secao":
            continue
        trechos = p.get("trecho_exclusivo")
        assert trechos and len(trechos) == 2, f"{p['id']}: trecho_exclusivo precisa ter 1 item por secao"
        secoes = [
            _normalizar(_secoes(CORPUS / a)[s]) for a, s in zip(p["arquivo_fonte"], p["secao_fonte"], strict=True)
        ]
        resposta = _normalizar(p["resposta_esperada"])
        for i, trecho in enumerate(trechos):
            alvo = _normalizar(trecho)
            outra = secoes[1 - i]
            assert alvo in secoes[i], f"{p['id']}: '{trecho}' nao esta em {p['secao_fonte'][i]}"
            assert alvo not in outra, f"{p['id']}: '{trecho}' tambem esta em {p['secao_fonte'][1 - i]}"
            assert alvo in resposta, f"{p['id']}: a resposta esperada nao exige '{trecho}'"


# --- sem_resposta: criterio de acerto declarado ------------------------------


def test_sem_resposta_declara_criterio_de_acerto(perguntas):
    for p in perguntas:
        if p["tipo"] == "sem_resposta":
            assert str(p.get("criterio_acerto", "")).strip(), f"{p['id']} sem criterio_acerto"


@pytest.mark.parametrize("qid", ["q19", "q20"])
def test_quase_acerto_aceita_regra_relacionada_sem_inventar(perguntas, qid):
    """q19/q20: vale "nao sei" OU dizer que o manual nao preve aquilo citando a
    regra relacionada - desde que nao invente valor ou numero."""
    p = next(p for p in perguntas if p["id"] == qid)
    criterio = _normalizar(p["criterio_acerto"])
    assert "nao sei" in criterio and "inventa" in criterio, qid
    alternativa = p.get("aceita_tambem", "")
    assert _CODIGO.search(alternativa), f"{qid}: aceita_tambem precisa citar a regra relacionada (codigo do POP)"


# --- codigos citados ----------------------------------------------------------


def test_todo_codigo_citado_no_gabarito_existe_no_corpus(perguntas):
    corpus = set(_CODIGO.findall(_corpus_text()))
    for p in perguntas:
        faltando = set(_CODIGO.findall(_textos_do_item(p))) - corpus
        assert not faltando, f"{p['id']} cita codigo(s) inexistente(s) no corpus: {sorted(faltando)}"


def test_codigos_da_resposta_estao_nas_secoes_fonte(perguntas):
    for p in perguntas:
        if not p["secao_fonte"]:
            continue
        fontes = " ".join(
            _secoes(CORPUS / a)[s] for a, s in zip(p["arquivo_fonte"], p["secao_fonte"], strict=True)
        )
        # O codigo do proprio POP-fonte (ex.: "(POP-02)" como atribuicao) vale
        # mesmo que so apareca no titulo do arquivo.
        proprios = {a.split("-", 2)[0].upper() + "-" + a.split("-", 2)[1] for a in p["arquivo_fonte"]}
        faltando = set(_CODIGO.findall(p["resposta_esperada"])) - set(_CODIGO.findall(fontes)) - proprios
        assert not faltando, f"{p['id']}: resposta cita {sorted(faltando)} fora das secoes-fonte"


# --- anti-copia ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("pergunta", "copia"),
    [
        # acento e pontuacao diferentes do manual nao escondem a copia
        ("divergencia acima de 2 produto trocado ou preco?", True),
        ("DIVERGÊNCIA ACIMA DE 2%... produto trocado", True),
        # pergunta curta (< 6 palavras) copiada inteira
        ("Horário da doca", True),
        ("Sangria", True),
        # paráfrase de WhatsApp: nao e copia
        ("minha gaveta ta com quase 900 conto", False),
        ("qual o horario pra entregar?", False),
    ],
)
def test_detector_de_copia(pergunta, copia):
    corpus = _normalizar(_corpus_text())
    assert (_trecho_copiado(pergunta, corpus) is not None) is copia


def test_perguntas_nao_copiam_o_manual(perguntas):
    """Pergunta de WhatsApp, nao trecho do manual."""
    corpus = _normalizar(_corpus_text())
    for p in perguntas:
        trecho = _trecho_copiado(p["pergunta"], corpus)
        assert trecho is None, f"{p['id']} copia o manual: '{trecho}'"
