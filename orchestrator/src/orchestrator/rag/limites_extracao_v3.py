"""Ferramenta de limites - Parte 2.2: o modelo PROPOE, o codigo CONFERE (so veta).

O modelo faz a extracao da Parte 2 (v1): o MESMO prompt e o MESMO schema (os
hashes da v1 nao mudam). As travas da v1 (literalidade, vizinhanca, enums e o
indice da tabela) rodam iguais, pelo proprio `limites_extracao.interpretar`.
Depois disso o codigo so pode VETAR: transformar um campo em vazio, com motivo.
O codigo NUNCA preenche um campo nem troca um valor (docs/RAG.md, "Parte 2.2").

Vetos (deterministas, cada um com o seu motivo):

1. Contexto sem sustentacao: o contexto proposto precisa de pelo menos uma
   pista DAQUELE contexto em qualquer lugar da pergunta (tabela de lugares do
   sinonimos_v1.yaml, com a tolerancia de digitacao do E-7). Sem pista -> vazio.
2. Contexto em conflito: pistas dos DOIS contextos na pergunta -> vazio.
3. Categoria sem sustentacao: a categoria proposta precisa de pelo menos uma
   palavra da tabela de produtos (com o E-7), em qualquer lugar da pergunta,
   que de AQUELA categoria no contexto FINAL (depois dos vetos 1 e 2), pela
   mesma regra da v2: `contextos` da entrada e indice da tabela de temperaturas
   (no armazenamento, iogurte da laticinios_e_frios; sem contexto, da laticinios).
4. Produto ambiguo: a pergunta tem uma palavra de `fora_de_proposito.produtos`
   que NAO vem seguida (palavra seguinte) de uma palavra da tabela de produtos
   que resolva ("frango congelado" resolve; "frango" sozinho nao) -> categoria
   vazia. Palavra de fora dentro de uma forma da tabela ("presunto" em
   "presunto fatiado") nao e ambigua.
5. Dois numeros: mais de um numero de temperatura na pergunta, contado pelo
   codigo (`numeros_de_temperatura` da v2) -> valor vazio.
6. O `aplica` e do modelo. O codigo so veta: `aplica` true SEM valor legivel E
   SEM pista de produto ou de lugar -> ficha vazia segura (contexto, categoria e
   valor vazios; o `aplica` fica como o modelo deu, porque trocar true por false
   seria trocar um valor). "Valor legivel" e a pista de temperatura da regra 1
   da v2: o trecho lido tem um numero que o codigo conta como temperatura, ou,
   sem digito, uma palavra de temperatura. Pista de produto ou de lugar: palavra
   das tabelas (com o E-7) OU do `fora_de_proposito`.

E-7 aqui vale na PERGUNTA INTEIRA (na v2 valia so nas copias): cada palavra e
lida com os mesmos parametros (distancia <= 1, 6 letras, casamento unico) e so
para a classe do veto (lugar nos vetos 1-2, produto nos 3-4).

Ficha invalida pelas travas da v1 continua invalida (marcar valida nao e veto).
`aplica` false: nada a vetar. Campo vazio na proposta leva o motivo
"vazio na proposta"; campo vetado leva o motivo de cada veto que disparou.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from orchestrator.rag import limites
from orchestrator.rag import limites_extracao as lx1
from orchestrator.rag import limites_extracao_v2 as lx2

# Chamada, prompt e schema: os da v1, sem copia (os hashes sao os mesmos).
NOME_FERRAMENTA = lx1.NOME_FERRAMENTA
TOOL_CHOICE = lx1.TOOL_CHOICE
TEMPERATURA = lx1.TEMPERATURA
prompt_sistema = lx1.prompt_sistema
schema_ferramenta = lx1.schema_ferramenta
mensagens = lx1.mensagens
hashes = lx1.hashes
categorias = lx1.categorias
chamar_openrouter = lx1.chamar_openrouter
DEFAULT_SINONIMOS = lx2.DEFAULT_SINONIMOS
carregar_sinonimos = lx2.carregar_sinonimos

VAZIO_NA_PROPOSTA = "vazio na proposta (modelo + travas da v1)"
CAMPOS = ("contexto", "categoria", "valor")


# --- o que o codigo le da pergunta (uma vez por pergunta) -----------------------------


@dataclass(frozen=True)
class Analise:
    lugares: dict  # contexto -> termos da tabela de lugares achados na pergunta
    produtos: tuple  # (inicio, fim, Entrada) no texto lido para produto
    ambiguos: tuple[str, ...]  # motivos do fora_de_proposito sem palavra que resolva
    numeros: tuple[tuple[int, int], ...]  # numeros de temperatura (spans na pergunta)
    tem_pista: bool  # alguma palavra de produto ou de lugar (tabelas ou de fora)
    notas: tuple[str, ...]  # E-7 na pergunta inteira


def _ocorrencias(texto: str, termo: str) -> list[tuple[int, int]]:
    return [
        m.span()
        for m in re.finditer(
            rf"(?<!\w){re.escape(termo)}(?!\w)", lx2._normalizar(texto)
        )
    ]


def analisar(pergunta: str, sin: lx2.Sinonimos) -> Analise:
    lida_lugar, notas_lugar = lx2.corrigir_digitacao(pergunta, "lugar", sin)
    lida_produto, notas_produto = lx2.corrigir_digitacao(pergunta, "produto", sin)
    lida_produto = lx2._normalizar(lida_produto)

    lugares: dict[str, list[str]] = {}
    for _, _, e in lx2._achados(lida_lugar, sin.lugares):
        termos = lugares.setdefault(e.destino, [])
        if e.termo not in termos:
            termos.append(e.termo)

    produtos = tuple(lx2._achados(lida_produto, sin.produtos))
    ambiguos: list[str] = []
    for termo, motivo in sin.fora_produtos.items():
        for a, b in _ocorrencias(lida_produto, termo):
            if any(pa <= a and b <= pb for pa, pb, _ in produtos):
                continue  # dentro de uma forma da tabela ("presunto fatiado")
            if any(pa == b + 1 for pa, _, _ in produtos):
                continue  # a palavra seguinte resolve ("frango congelado")
            if motivo not in ambiguos:
                ambiguos.append(motivo)

    tem_pista = bool(lugares or produtos) or any(
        _ocorrencias(pergunta, termo)
        for termo in (*sin.fora_produtos, *sin.fora_lugares)
    )
    return Analise(
        lugares={k: tuple(v) for k, v in lugares.items()},
        produtos=produtos,
        ambiguos=tuple(ambiguos),
        numeros=tuple(lx2.numeros_de_temperatura(pergunta)),
        tem_pista=tem_pista,
        notas=tuple(dict.fromkeys((*notas_lugar, *notas_produto))),
    )


def _categoria_da_palavra(
    e: lx2.Entrada, contexto: str | None, tab: limites.Tabela
) -> str | None:
    """A categoria que a palavra da no contexto (a mesma regra da v2)."""
    if e.contextos and contexto not in e.contextos:
        return None
    if contexto is None:
        return e.destino
    regra = tab.indice.get((contexto, limites.normalizar_nome(e.destino)))
    return None if regra is None else regra.categoria


def valor_legivel(
    pergunta: str, trecho_ini_fim: tuple[int, int] | None, numeros
) -> bool:
    """A pista de temperatura da regra 1 da v2, no trecho que a v1 leu."""
    if trecho_ini_fim is None:
        return False
    ini, fim = trecho_ini_fim
    if any(c.isdigit() for c in pergunta[ini:fim]):
        return any(a < fim and ini < b for a, b in numeros)
    return bool(lx2._PALAVRA_DE_TEMPERATURA.search(pergunta[ini:fim]))


# --- a ficha v3 ---------------------------------------------------------------------


@dataclass(frozen=True)
class FichaV3:
    valida: bool
    aplica: bool | None
    contexto: str | None
    categoria: str | None
    valor: Decimal | None
    valor_texto: str | None
    trecho: str | None
    motivos: dict = field(default_factory=dict)  # campo -> por que ficou vazio
    vetos: tuple[int, ...] = ()  # os vetos que dispararam
    proposta: dict = field(default_factory=dict)  # a ficha da v1, antes dos vetos
    notas: tuple[str, ...] = ()  # E-7
    problemas: tuple[str, ...] = ()
    bruto: dict | None = field(default=None, compare=False)

    def como_dict(self) -> dict:
        return {
            "valida": self.valida,
            "aplica": self.aplica,
            "contexto": self.contexto,
            "categoria": self.categoria,
            "valor": None if self.valor is None else str(self.valor),
            "valor_texto": self.valor_texto,
            "trecho": self.trecho,
            "motivos": dict(self.motivos),
            "vetos": list(self.vetos),
            "proposta": dict(self.proposta),
            "notas": list(self.notas),
            "problemas": list(self.problemas),
        }


def _posicao_do_trecho(pergunta: str, ficha: lx1.Ficha) -> tuple[int, int] | None:
    if not ficha.valor_texto:
        return None
    pos = lx1.localizar(pergunta, ficha.valor_texto)
    return pos if isinstance(pos, tuple) else None


def vetar(
    pergunta: str,
    ficha: lx1.Ficha,
    analise: Analise,
    tabela: limites.Tabela | None = None,
) -> FichaV3:
    """Aplica os 6 vetos a ficha da v1. So esvazia: nunca preenche, nunca troca."""
    tab = tabela or limites.carregar_tabela()
    proposta = {
        "aplica": ficha.aplica,
        "contexto": ficha.contexto,
        "categoria": ficha.categoria,
        "valor": None if ficha.valor is None else str(ficha.valor),
    }
    campos = {
        "contexto": ficha.contexto,
        "categoria": ficha.categoria,
        "valor": ficha.valor,
    }
    motivos: dict[str, list[str]] = {}
    vetos: list[int] = []

    def veta(campo: str, n: int, motivo: str) -> None:
        campos[campo] = None
        motivos.setdefault(campo, []).append(f"veto {n}: {motivo}")
        if n not in vetos:
            vetos.append(n)

    if ficha.valida and ficha.aplica:
        # veto 6 (olha a proposta): aplica true sem valor legivel e sem pista
        if not analise.tem_pista and not valor_legivel(
            pergunta, _posicao_do_trecho(pergunta, ficha), analise.numeros
        ):
            motivo = "aplica=true sem valor legivel nem pista de produto ou de lugar: ficha vazia segura"
            motivos["aplica"] = [f"veto 6: {motivo}"]
            vetos.append(6)
            for c in CAMPOS:
                if campos[c] is not None:
                    veta(c, 6, motivo)
        # vetos 1 e 2: contexto
        ctx = campos["contexto"]
        if ctx is not None:
            if len(analise.lugares) > 1:
                veta(
                    "contexto",
                    2,
                    "pistas dos dois contextos na pergunta: "
                    + "; ".join(
                        f"{c} ({', '.join(repr(t) for t in ts)})"
                        for c, ts in sorted(analise.lugares.items())
                    ),
                )
            if ctx not in analise.lugares:
                veta("contexto", 1, f"contexto {ctx!r} sem pista de lugar na pergunta")
        # vetos 3 e 4: categoria (pelo contexto FINAL)
        cat = campos["categoria"]
        if cat is not None:
            sustentam = {
                _categoria_da_palavra(e, campos["contexto"], tab)
                for _, _, e in analise.produtos
            }
            if cat not in sustentam:
                onde = campos["contexto"] or "sem contexto"
                veta(
                    "categoria",
                    3,
                    f"nenhuma palavra de produto da pergunta da {cat!r} ({onde})",
                )
            for motivo in analise.ambiguos:
                veta("categoria", 4, motivo)
        # veto 5: valor
        if campos["valor"] is not None and len(analise.numeros) > 1:
            veta(
                "valor",
                5,
                "a pergunta tem {} numeros de temperatura ({}): qual e o medido?".format(
                    len(analise.numeros),
                    ", ".join(repr(pergunta[a:b]) for a, b in analise.numeros),
                ),
            )
        for c in CAMPOS:
            if proposta[c] is None:
                motivos.setdefault(c, []).append(VAZIO_NA_PROPOSTA)

    return FichaV3(
        valida=ficha.valida,
        aplica=ficha.aplica,
        contexto=campos["contexto"],
        categoria=campos["categoria"],
        valor=campos["valor"],
        valor_texto=ficha.valor_texto,
        trecho=ficha.trecho,
        motivos={k: "; ".join(v) for k, v in motivos.items()},
        vetos=tuple(sorted(vetos)),
        proposta=proposta,
        notas=analise.notas,
        problemas=ficha.problemas,
        bruto=ficha.bruto,
    )


def interpretar(
    pergunta: str,
    resposta,
    *,
    tabela: limites.Tabela | None = None,
    sinonimos: lx2.Sinonimos | None = None,
    analise: Analise | None = None,
) -> FichaV3:
    """A ficha da v1 (travas iguais), depois os vetos."""
    tab = tabela or limites.carregar_tabela()
    sin = sinonimos or lx2._sinonimos_padrao(str(DEFAULT_SINONIMOS))
    ficha = lx1.interpretar(pergunta, resposta, tab)
    return vetar(pergunta, ficha, analise or analisar(pergunta, sin), tab)
