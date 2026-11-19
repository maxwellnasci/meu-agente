"""Normalizacao de texto em portugues para o BM25 (FTS5).

A MESMA funcao (`normalizar`) roda na indexacao e na consulta. A variante
usada na ingestao fica gravada na tabela `meta` do indice, e a busca le de la
(`store.read_bm25_config`): indice e consulta nunca divergem.

Ordem dos passos, por token:

1. minusculas e SEM acento (as perguntas de WhatsApp chegam sem acento);
2. codigos (`POP-06`, `F-18`, `Q-22`, `P-05`) passam intactos, sem stopword
   nem stemming, e viram frase na consulta (`"pop 06"`);
3. stopwords (lista propria abaixo, sem download);
4. stemming Snowball portugues (`snowballstemmer`, Python puro, sem download).
   Ele roda DEPOIS de tirar o acento: com acento, "diluição" vira "diluiçã" e
   a pergunta "diluicao" vira "diluica", e as duas formas nunca casariam. Sem
   acento, as duas viram "diluica".
"""

import re
import unicodedata
from dataclasses import dataclass

import snowballstemmer

_TOKEN = re.compile(r"\b(pop|f|q|p)-(\d{2})\b|(\w+)", re.UNICODE)


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


# Palavras que NUNCA sao stopword. Num manual de procedimento, "nao aceitar" e
# "aceitar" sao opostos, e "ate 30 minutos" e "acima de 2%" sao a regra. As 9
# primeiras foram pedidas explicitamente; "mais", "menos", "apos" e "entre"
# entram pelo mesmo motivo (limite: "mais de 2%", "apos 18h", "entre 0 e 4").
PRESERVADAS = frozenset(
    sem_acento(p)
    for p in ("não", "nunca", "sem", "só", "antes", "depois", "até", "acima", "abaixo", "mais", "menos", "após", "entre")
)

# Lista propria: artigos, preposicoes/contracoes, pronomes, conjuncoes e
# formas comuns de ser/estar/ter/haver/ir. Comparada SEM acento.
_STOPWORDS_BRUTAS = """
a o as os um uma uns umas
de do da dos das d em no na nos nas num numa nuns numas
ao aos à às pelo pela pelos pelas por para pra pro pras pros com
dum duma deste desta destes destas desse dessa desses dessas daquele daquela
neste nesta nestes nestas nesse nessa nesses nessas naquele naquela
e ou mas nem que se como quando onde porque porquê pois
eu tu ele ela nós vós eles elas você vocês voce voces me te lhe nos vos lhes
meu minha meus minhas teu tua seu sua seus suas nosso nossa nossos nossas
este esta estes estas esse essa esses essas aquele aquela aqueles aquelas isto isso aquilo
qual quais quem cujo cuja o que
é ser sou somos são era eram foi foram será serão seja sejam sendo sido
está estou estamos estão estava estavam esteve estar
tem têm ter tenho temos tinha tinham teve tido
há haver havia houve
vai vou vão ir
ta tá to tô né aí aqui ali lá já também tambem
muito muita muitos muitas pouco pouca
algum alguma alguns algumas todo toda todos todas outro outra outros outras
"""
STOPWORDS = frozenset(sem_acento(p) for p in _STOPWORDS_BRUTAS.split()) - PRESERVADAS

_stemmer = snowballstemmer.stemmer("portuguese")


@dataclass(frozen=True)
class Bm25Config:
    stopwords: bool = True
    stemming: bool = True

    @property
    def normaliza(self) -> bool:
        return self.stopwords or self.stemming

    @property
    def nome(self) -> str:
        partes = [n for n, on in (("stopwords", self.stopwords), ("stemming", self.stemming)) if on]
        return "+".join(partes) if partes else "baseline"


# Padrao do indice, escolhido pela comparacao das 4 variantes (docs/RAG.md,
# Resultados, Missao 4): so stemming foi a unica que subiu o recall@5 (BM25
# 14 -> 15/17; hibrido empata em 14 nas 4). Stopwords+stemming perdeu a q15.
DEFAULT_BM25 = Bm25Config(stopwords=False, stemming=True)
VARIANTES = (
    Bm25Config(False, False),
    Bm25Config(True, False),
    Bm25Config(False, True),
    Bm25Config(True, True),
)


def tokens(texto: str, cfg: Bm25Config) -> list[tuple[str, bool]]:
    """(termo, e_codigo). Codigo vem como "pop 06" (frase de 2 tokens)."""
    out: list[tuple[str, bool]] = []
    for m in _TOKEN.finditer(sem_acento(texto).lower()):
        if m.group(1):
            out.append((f"{m.group(1)} {m.group(2)}", True))
            continue
        palavra = m.group(3)
        if cfg.stopwords and palavra in STOPWORDS:
            continue
        out.append((_stemmer.stemWord(palavra) if cfg.stemming else palavra, False))
    return out


def normalizar(texto: str, cfg: Bm25Config) -> str:
    """Texto que vai para a coluna do FTS5 (indexacao)."""
    return " ".join(termo for termo, _ in tokens(texto, cfg))
