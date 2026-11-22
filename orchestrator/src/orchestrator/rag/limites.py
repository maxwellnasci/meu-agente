"""Ferramenta de limites - Parte 1: temperaturas (docs/RAG.md, "Ferramenta de limites").

Python puro: nenhuma chamada a LLM, nada de grafo, nada de prompt. A
comparacao de numero sai do modelo e vem para ca (o mini-teste de 21/11 viu a
v1 aceitar frango congelado a −10 °C em 7 de 10; o limite e −12 °C).

- `ler_temperatura(texto)`: tira UM numero de temperatura de um texto, ou
  devolve None. Na duvida, None. Nunca chuta.
- `verificar_temperatura(contexto, categoria, valor)`: compara com a regra da
  tabela `fixtures/rag/limites/temperaturas_v1.yaml`. Categoria ou contexto
  desconhecido -> SEM_REGRA (o "nao sei"), nunca a regra mais parecida.

Tudo em `Decimal`: o valor, os limites e a comparacao. `float` e recusado na
entrada (TypeError) e o YAML tem de trazer os limites como string.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml

ORCHESTRATOR_DIR = Path(__file__).resolve().parents[3]
DEFAULT_TABELA = (
    ORCHESTRATOR_DIR / "fixtures" / "rag" / "limites" / "temperaturas_v1.yaml"
)

CONTEXTOS = ("recebimento", "armazenamento")
TIPOS = ("maximo", "faixa")
_FIM_DA_FRASE = {
    "recebimento": ("aceitar", "recusar"),
    "armazenamento": ("dentro da faixa", "fora da faixa"),
}
_NOME_DO_CONTEXTO = {
    "recebimento": "no recebimento",
    "armazenamento": "no armazenamento",
}


class Veredito(str, Enum):
    DENTRO = "DENTRO"
    FORA = "FORA"
    SEM_REGRA = "SEM_REGRA"


@dataclass(frozen=True)
class Limite:
    tipo: str  # "maximo" | "faixa"
    min: Decimal | None
    max: Decimal
    inclusivo: bool


@dataclass(frozen=True)
class Regra:
    id: str
    pop: str
    arquivo: str
    secao: str
    contexto: str
    categoria: str
    rotulo: str
    sinonimos: tuple[str, ...]
    limite: Limite
    trecho_literal: tuple[str, ...]
    ressalvas: tuple[str, ...]


@dataclass(frozen=True)
class Resultado:
    veredito: Veredito
    valor: Decimal
    contexto: str
    categoria: str
    limite: Limite | None
    frase: str
    pop: str | None
    secao: str | None
    regra_id: str | None
    ressalvas: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tabela:
    versao: str
    regras: tuple[Regra, ...]
    # (contexto, nome normalizado) -> regra
    indice: dict[tuple[str, str], Regra]


# --- normalizacao de nomes ---------------------------------------------------


def normalizar_nome(texto: str) -> str:
    """Sem acento, sem caixa, "_" vira espaco, espacos colapsados. So isso:
    nada de plural, radical ou semelhanca (isso seria "a regra mais parecida")."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.casefold().replace("_", " ").split())


# --- carga da tabela -----------------------------------------------------------


def _decimal_do_yaml(valor: object, campo: str, regra_id: str) -> Decimal:
    if not isinstance(valor, str):
        # tabela malformada e erro de DADO: um tipo so de excecao (ValueError) para o carregador
        raise ValueError(  # noqa: TRY004
            f"regra {regra_id}: '{campo}' tem de ser string no YAML (ex.: \"-12\"), veio {type(valor).__name__}"
        )
    try:
        d = Decimal(valor.strip())
    except InvalidOperation as e:
        raise ValueError(f"regra {regra_id}: '{campo}' nao e numero: {valor!r}") from e
    if not d.is_finite():
        raise ValueError(f"regra {regra_id}: '{campo}' nao e finito: {valor!r}")
    return d


def _regra(bruta: dict) -> Regra:
    rid = str(bruta.get("id") or "?")
    obrigatorios = (
        "id",
        "pop",
        "arquivo",
        "secao",
        "contexto",
        "categoria",
        "rotulo",
        "tipo",
        "max",
        "inclusivo",
    )
    faltando = [c for c in obrigatorios if c not in bruta]
    if faltando:
        raise ValueError(f"regra {rid}: campos faltando {faltando}")
    contexto, tipo = bruta["contexto"], bruta["tipo"]
    if contexto not in CONTEXTOS:
        raise ValueError(f"regra {rid}: contexto {contexto!r} fora de {CONTEXTOS}")
    if tipo not in TIPOS:
        raise ValueError(f"regra {rid}: tipo {tipo!r} fora de {TIPOS}")
    if not isinstance(bruta["inclusivo"], bool):
        raise ValueError(f"regra {rid}: 'inclusivo' tem de ser true/false")  # noqa: TRY004
    maximo = _decimal_do_yaml(bruta["max"], "max", rid)
    if tipo == "maximo":
        if "min" in bruta:
            raise ValueError(f"regra {rid}: tipo maximo nao tem 'min'")
        minimo = None
    else:
        if "min" not in bruta:
            raise ValueError(f"regra {rid}: tipo faixa precisa de 'min'")
        minimo = _decimal_do_yaml(bruta["min"], "min", rid)
        if not minimo < maximo:
            raise ValueError(
                f"regra {rid}: faixa com min >= max ({minimo} >= {maximo})"
            )
    trechos = tuple(bruta.get("trecho_literal") or ())
    if not trechos or not all(isinstance(t, str) and t for t in trechos):
        raise ValueError(f"regra {rid}: 'trecho_literal' precisa de ao menos um trecho")
    return Regra(
        id=rid,
        pop=bruta["pop"],
        arquivo=bruta["arquivo"],
        secao=bruta["secao"],
        contexto=contexto,
        categoria=bruta["categoria"],
        rotulo=bruta["rotulo"],
        sinonimos=tuple(bruta.get("sinonimos") or ()),
        limite=Limite(tipo=tipo, min=minimo, max=maximo, inclusivo=bruta["inclusivo"]),
        trecho_literal=trechos,
        ressalvas=tuple(bruta.get("ressalvas") or ()),
    )


def carregar_tabela(caminho: Path | str = DEFAULT_TABELA) -> Tabela:
    dados = yaml.safe_load(Path(caminho).read_text(encoding="utf-8"))
    if not isinstance(dados, dict) or dados.get("formato") != 1:
        raise ValueError(f"{caminho}: formato desconhecido (esperado 'formato: 1')")
    fontes = {(s["arquivo"], s["secao"]) for s in dados.get("secoes_fonte") or ()}
    regras = tuple(_regra(r) for r in dados.get("regras") or ())
    if not regras:
        raise ValueError(f"{caminho}: nenhuma regra")
    indice: dict[tuple[str, str], Regra] = {}
    for regra in regras:
        if (regra.arquivo, regra.secao) not in fontes:
            raise ValueError(
                f"regra {regra.id}: secao de origem fora de 'secoes_fonte'"
            )
        for nome in {normalizar_nome(n) for n in (regra.categoria, *regra.sinonimos)}:
            chave = (regra.contexto, nome)
            if chave in indice:
                raise ValueError(
                    f"nome {nome!r} aponta para duas regras no {regra.contexto}: {indice[chave].id} e {regra.id}"
                )
            indice[chave] = regra
    ids = [r.id for r in regras]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{caminho}: ids repetidos")
    return Tabela(versao=str(dados.get("versao")), regras=regras, indice=indice)


@lru_cache(maxsize=4)
def _tabela_padrao(caminho: str) -> Tabela:
    return carregar_tabela(caminho)


# --- leitura de temperatura em texto --------------------------------------------

# Um numero "de temperatura": ate 3 digitos inteiros e ate 2 decimais, com
# virgula ou ponto. "1.000" ou "10,555" nao passam (milhar? 3 casas?) -> None.
_NUMERO_ESTRITO = re.compile(r"\d{1,3}(?:[.,]\d{1,2})?")
_QUALQUER_NUMERO = re.compile(r"\d+(?:[.,]\d+)*")
_SINAL_MENOS = ("-", "−")  # hifen-menos ASCII e o sinal de menos unicode
_SINAL_MAIS = ("+",)
# Outros tracos: o celular troca "-" por "–" sozinho, mas "–" tambem separa
# faixa ("10–12"). Nao da para ter certeza: None.
_TRACOS_DUVIDOSOS = "‐‑‒–—―﹘﹣－"
# Aproximacao, comparacao ou faixa: a frase nao diz UM valor medido.
_DUVIDA = re.compile(
    r"\b(?:uns|umas|cerca|aproximadamente|aproximado|aprox|mais\s+ou\s+menos|quase|"
    r"por\s+volta|em\s+torno|perto|tipo|acho|talvez|sei\s+la|"
    r"menos\s+de|mais\s+de|abaixo|acima|ate|maximo|minimo|pelo\s+menos|entre)\b"
    r"|[~≈±]"
)
_UNIDADE = re.compile(
    r"\s*(?:(?:°|º)\s*c\b|°|º|graus?\s+celsius\b|graus?\b|celsius\b|c\b)?",
    re.IGNORECASE,
)
_FAHRENHEIT = re.compile(r"(?:°|º)\s*f\b|\bfahrenheit\b|^\s*f\b", re.IGNORECASE)
_NEGATIVOS_DEPOIS = re.compile(r"\s*negativos?\b")
_POSITIVOS_DEPOIS = re.compile(r"\s*positivos?\b")


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c)
    )


def ler_temperatura(texto: str) -> Decimal | None:
    """Le UMA temperatura em °C de um texto. Aceita "-10", "−10", "-10,5",
    "-10.5", "-10 graus", "−10 °C", "menos 10", "10 negativos" (e "10 graus
    negativos"). Devolve None se nao tiver certeza: nenhum numero, mais de um
    numero, numero por extenso, aproximacao ("uns -10"), comparacao ("menos de
    10"), faixa, duplo negativo, traco duvidoso, °F."""
    if not isinstance(texto, str):
        raise TypeError(f"ler_temperatura espera str, veio {type(texto).__name__}")
    # NFD (nao NFKD): tira acento sem decompor "º" em "o" nem mexer no "−".
    t = _sem_acento(texto).casefold()
    numeros = list(_QUALQUER_NUMERO.finditer(t))
    if len(numeros) != 1:
        return None
    m = numeros[0]
    if not _NUMERO_ESTRITO.fullmatch(m.group()):
        return None
    if _DUVIDA.search(t):
        return None

    antes, depois = t[: m.start()], t[m.end() :]
    negativo = False
    explicito = False
    if antes and antes[-1] in _SINAL_MENOS + _SINAL_MAIS:
        negativo = antes[-1] in _SINAL_MENOS
        explicito = True
        antes = antes[:-1]
        if antes and not (antes[-1].isspace() or antes[-1] in "(:=[\"'"):
            return None  # "pop-10", "a-10", "--10": nao e sinal
    elif antes and antes[-1] in _TRACOS_DUVIDOSOS:
        return None
    elif antes and (antes[-1].isalnum() or antes[-1] in ".,"):
        return None  # "x10", ",10"
    resto_antes = antes.rstrip()
    if resto_antes and resto_antes[-1] in _SINAL_MENOS + _SINAL_MAIS + tuple(
        _TRACOS_DUVIDOSOS
    ):
        return None  # "- 10": sinal solto ou marcador de lista? Nao da para saber.
    if re.search(r"\bmenos\s*$", antes):
        if explicito:
            return None  # "menos -10"
        negativo, explicito = True, True
        resto_antes = re.sub(r"\bmenos\s*$", "", antes)
    if re.search(r"\b(?:menos|negativ\w*|positiv\w*)\b", resto_antes):
        return None  # marcador de sinal longe do numero

    u = _UNIDADE.match(depois)
    depois = depois[u.end() :] if u else depois
    if _FAHRENHEIT.search(depois):
        return None
    neg = _NEGATIVOS_DEPOIS.match(depois)
    pos = _POSITIVOS_DEPOIS.match(depois)
    if neg:
        if explicito:
            return None  # "-10 negativos", "menos 10 negativos"
        negativo = True
        depois = depois[neg.end() :]
    elif pos:
        if negativo:
            return None  # "-10 positivos"
        depois = depois[pos.end() :]
    if re.search(r"\b(?:menos|negativ\w*|positiv\w*)\b", depois):
        return None
    if depois[:1].isalnum() or depois[:1] in _SINAL_MENOS + _SINAL_MAIS + tuple(
        _TRACOS_DUVIDOSOS
    ):
        return None  # "10x", "10-12"

    valor = Decimal(m.group().replace(",", "."))
    return -valor if negativo else valor


# --- a conta -------------------------------------------------------------------


def formatar_celsius(valor: Decimal) -> str:
    """-12 -> "−12 °C"; -12.10 -> "−12,1 °C"; 0 e -0 -> "0 °C"."""
    if valor == 0:
        return "0 °C"
    texto = format(valor.normalize(), "f").replace("-", "−").replace(".", ",")
    return f"{texto} °C"


def _sem_regra(contexto: str, categoria: str, valor: Decimal) -> Resultado:
    return Resultado(
        veredito=Veredito.SEM_REGRA,
        valor=valor,
        contexto=contexto,
        categoria=categoria,
        limite=None,
        frase=(
            f"Não há regra de temperatura para {categoria!r} no contexto {contexto!r} "
            "na tabela de limites: não sei."
        ),
        pop=None,
        secao=None,
        regra_id=None,
    )


def _comparar(valor: Decimal, lim: Limite) -> tuple[bool, str]:
    """(dentro?, como o valor se compara ao limite), so com Decimal."""
    v = formatar_celsius(valor)
    mx = formatar_celsius(lim.max)
    if lim.tipo == "maximo":
        if valor > lim.max:
            return False, f"{v} está ACIMA de {mx}, o máximo"
        if valor == lim.max:
            if lim.inclusivo:
                return True, f"{v} é IGUAL a {mx}, o máximo (inclusive)"
            return False, f"{v} é IGUAL a {mx}, o limite (exclusive)"
        return True, f"{v} está ABAIXO de {mx}, o máximo"
    assert lim.min is not None
    mn = formatar_celsius(lim.min)
    faixa = f"da faixa de {mn} a {mx}"
    if valor > lim.max:
        return False, f"{v} está ACIMA de {mx}, o máximo {faixa}"
    if valor < lim.min:
        return False, f"{v} está ABAIXO de {mn}, o mínimo {faixa}"
    if valor == lim.max:
        if lim.inclusivo:
            return True, f"{v} é IGUAL a {mx}, o máximo (inclusive) {faixa}"
        return False, f"{v} é IGUAL a {mx}, o máximo (exclusive) {faixa}"
    if valor == lim.min:
        if lim.inclusivo:
            return True, f"{v} é IGUAL a {mn}, o mínimo (inclusive) {faixa}"
        return False, f"{v} é IGUAL a {mn}, o mínimo (exclusive) {faixa}"
    return True, f"{v} está ENTRE {mn} e {mx}, a faixa"


def verificar_temperatura(
    contexto: str, categoria: str, valor: Decimal | int, *, tabela: Tabela | None = None
) -> Resultado:
    """Compara `valor` (°C) com a regra de (contexto, categoria).

    Recebimento: a frase termina em "aceitar" ou "recusar". Armazenamento:
    em "dentro da faixa" ou "fora da faixa". Contexto ou categoria fora da
    tabela: SEM_REGRA."""
    if isinstance(valor, bool) or not isinstance(valor, (Decimal, int)):
        raise TypeError(
            f"valor tem de ser Decimal (ou int), veio {type(valor).__name__}: use ler_temperatura"
        )
    valor = Decimal(valor)
    if not valor.is_finite():
        raise ValueError(f"valor nao finito: {valor}")
    if not isinstance(contexto, str) or not isinstance(categoria, str):
        raise TypeError("contexto e categoria sao str")
    tab = tabela if tabela is not None else _tabela_padrao(str(DEFAULT_TABELA))
    ctx = normalizar_nome(contexto)
    regra = (
        tab.indice.get((ctx, normalizar_nome(categoria))) if ctx in CONTEXTOS else None
    )
    if regra is None:
        return _sem_regra(contexto, categoria, valor)

    dentro, comparacao = _comparar(valor, regra.limite)
    sim, nao = _FIM_DA_FRASE[regra.contexto]
    frase = f"{comparacao} para {regra.rotulo} {_NOME_DO_CONTEXTO[regra.contexto]}: {sim if dentro else nao}"
    return Resultado(
        veredito=Veredito.DENTRO if dentro else Veredito.FORA,
        valor=valor,
        contexto=regra.contexto,
        categoria=regra.categoria,
        limite=regra.limite,
        frase=frase,
        pop=regra.pop,
        secao=regra.secao,
        regra_id=regra.id,
        ressalvas=regra.ressalvas,
    )
