"""Ferramenta de limites - Parte 3: a ficha (v3) e a conta (Parte 1) ligadas no agente.

As 5 etapas do caminho: 1 supervisor -> 2 busca (rag) -> 3 ficha (v3) ->
4 conta (`limites.verificar_temperatura`) -> 5 redator (synthesize_final).
Este modulo e a 3 e a 4. Roda DENTRO do `specialist_rag_node`, depois da busca e
so quando ha trechos e `settings.rag_limites` esta ligado (padrao: desligado).
Desligado, o no e byte a byte o de antes (docs/RAG.md, "Parte 3").

Por que dentro do no do rag e nao num no proprio: a verificacao so faz sentido
quando o manual foi consultado, usa a MESMA pergunta original que a busca, e
assim nada muda no roteamento (supervisor, `route_after_specialist`, schema do
despacho e prompt do supervisor ficam iguais). O supervisor ve so uma linha fixa
no lugar da nota (`rag_specialist.scratchpad_para_supervisor`).

Uma nota `[limite]` por pergunta, ou nenhuma:

- o CODIGO acha temperatura na pergunta (pre-filtro, sem LLM) -> roda a ficha v3
  (o modelo propoe, o codigo so veta; prompt, schema e travas da Parte 2.2);
  sem nenhum numero nem palavra de temperatura, nenhuma chamada e nenhuma nota;
- ficha completa (aplica, contexto, categoria e valor) -> a conta da Parte 1 ->
  nota com a DECISAO, a fonte (POP e secao da tabela) e a ressalva da regra,
  sempre que a regra tiver uma (descongelamento, nos congelados do recebimento);
- ficha incompleta, mas o codigo acha temperatura (inclusive com aplica=false,
  como no i04 e no i10 da Parte 2.2) -> nota NAO VERIFICAVEL, com o motivo do
  campo vazio e o que perguntar ao funcionario (pendencia OBRIGATORIA);
- falha da extracao (excecao, infra, ficha sem a ferramenta) -> NAO VERIFICAVEL,
  nunca silencio.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable

from orchestrator.config import settings
from orchestrator.rag import limites
from orchestrator.rag import limites_extracao_v2 as lx2
from orchestrator.rag import limites_extracao_v3 as lx3

_logger = logging.getLogger(__name__)

LIMITE_TAG = "[limite]"
NAO_VERIFICAVEL = "NÃO VERIFICÁVEL"
# (contexto, dentro?) -> rotulo da decisao. A regra 6 da v5 cita ESTAS constantes.
DECISOES = {
    ("recebimento", True): "ACEITAR",
    ("recebimento", False): "RECUSAR",
    ("armazenamento", True): "DENTRO DA FAIXA",
    ("armazenamento", False): "FORA DA FAIXA",
}
ROTULOS_DE_DECISAO = tuple(dict.fromkeys(DECISOES.values()))

# O que perguntar ao funcionario, por campo vazio da ficha.
FALTA = {
    "valor": "qual foi a temperatura medida (um número só)",
    "categoria": "qual é o produto (por exemplo: congelado, resfriado, laticínio ou frios fatiados)",
    "contexto": "se o produto está chegando (recebimento) ou já está guardado ou exposto na loja (armazenamento)",
}
_NOME_DO_CAMPO = {"contexto": "contexto", "categoria": "produto", "valor": "temperatura"}
_ORDEM_DOS_CAMPOS = ("valor", "categoria", "contexto")

_DELIMITADOR_FORJADO = re.compile(r"<\s*/?\s*trecho", re.IGNORECASE)


# --- o que o CODIGO acha na pergunta (sem LLM) -------------------------------------


def _com_sinal(pergunta: str, ini: int) -> bool:
    """O numero que comeca em `ini` tem sinal explicito? ("-16", "−16", "+4", "menos 18")."""
    antes = pergunta[:ini].rstrip()
    return antes.endswith(("-", "−", "+")) or bool(re.search(r"\bmenos$", antes, re.IGNORECASE))


def tem_temperatura(pergunta: str) -> bool:
    """A pergunta fala de temperatura, contado SO pelo codigo: uma palavra ou simbolo
    de temperatura ("graus", "negativo", "celsius", "abaixo de zero", "°") ou um
    numero de temperatura com sinal explicito. E o gatilho da nota NAO VERIFICAVEL
    quando a ficha vem incompleta ou com aplica=false."""
    if lx2._PALAVRA_DE_TEMPERATURA.search(pergunta):
        return True
    return any(_com_sinal(pergunta, ini) for ini, _ in lx2.numeros_de_temperatura(pergunta))


def precisa_de_ficha(pergunta: str) -> bool:
    """Pre-filtro: so chama o extrator se a pergunta tiver um numero que pode ser
    temperatura (`numeros_de_temperatura` da v2) ou temperatura pelo `tem_temperatura`.
    Sem isso, nenhuma chamada e nenhuma nota."""
    return bool(lx2.numeros_de_temperatura(pergunta)) or tem_temperatura(pergunta)


# --- a ficha -----------------------------------------------------------------------

Chamar = Callable[[list], object]  # mensagens -> AIMessage


def _chamar_padrao() -> Chamar:
    """A MESMA chamada medida na Parte 2.2 (modelo, temperatura 0, tool_choice)."""
    return lx3.chamar_openrouter(settings)


# Ponto de injecao dos testes (LLM falso); em producao, o ChatOpenAI da v1.
fabrica_chamar: Callable[[], Chamar] = _chamar_padrao


def _tabela() -> limites.Tabela:
    return limites._tabela_padrao(str(limites.DEFAULT_TABELA))


def extrair_ficha_v3(pergunta: str, *, chamar: Chamar) -> lx3.FichaV3:
    """A ficha da Parte 2.2: a resposta do modelo, as travas da v1 e os 6 vetos."""
    return lx3.interpretar(pergunta, chamar(lx3.mensagens(pergunta)), tabela=_tabela())


def ficha_completa(ficha: lx3.FichaV3) -> bool:
    return bool(ficha.valida) and ficha.aplica is True and None not in (
        ficha.contexto, ficha.categoria, ficha.valor
    )


# --- as notas ----------------------------------------------------------------------


def _limpo(texto: object) -> str:
    """Uma linha so, sem tag forjada: os motivos podem trazer pedacos da pergunta."""
    t = " ".join(str(texto).replace("**", "").split())
    t = t.replace(LIMITE_TAG, "[tag removida]")
    return _DELIMITADOR_FORJADO.sub("[delimitador removido]", t)


def nota_decisao(res: limites.Resultado) -> str:
    """Ficha completa e regra na tabela: a decisao da conta, a fonte e a ressalva."""
    rotulo = DECISOES[(res.contexto, res.veredito is limites.Veredito.DENTRO)]
    comparacao = res.frase.rsplit(": ", 1)[0]
    nota = f'{LIMITE_TAG} {rotulo}: {comparacao} ({res.pop}, seção "{res.secao}").'
    for ressalva in res.ressalvas:
        nota += f" Ressalva do manual: {_limpo(ressalva)}"
    return nota


def nota_nao_verificavel(motivo: str, faltando: list[str] | None = None) -> str:
    """Sem decisao: o redator NUNCA decide aceitar/recusar sozinho."""
    if faltando:
        fim = "pergunte ao funcionário " + " e ".join(FALTA[c] for c in faltando) + "."
    else:
        fim = "diga que não consegue verificar."
    return f"{LIMITE_TAG} {NAO_VERIFICAVEL}: {_limpo(motivo).rstrip('.')}. Não decida aceitar/recusar; {fim}"


def nota_falha(exc: BaseException) -> str:
    """Falha da extracao: so o TIPO da excecao (a mensagem pode trazer texto do provedor)."""
    return (
        f"{LIMITE_TAG} {NAO_VERIFICAVEL}: a verificação da temperatura falhou agora ({type(exc).__name__}). "
        "Não decida aceitar/recusar; diga que não consegue verificar agora e peça ao funcionário que "
        "confirme com o encarregado."
    )


def nota_da_ficha(pergunta: str, ficha: lx3.FichaV3) -> str | None:
    """A nota de uma ficha ja extraida (deterministico; sem LLM)."""
    if ficha_completa(ficha):
        res = limites.verificar_temperatura(ficha.contexto, ficha.categoria, ficha.valor, tabela=_tabela())
        if res.veredito is limites.Veredito.SEM_REGRA:
            return nota_nao_verificavel(res.frase)
        return nota_decisao(res)
    if not ficha.valida:
        motivo = "a ficha da pergunta saiu inválida (" + "; ".join(ficha.problemas or ("sem motivo",)) + ")"
        if ficha.aplica is None:
            return nota_nao_verificavel(motivo)  # o modelo nem preencheu: falha, nunca silencio
        faltando = [c for c in _ORDEM_DOS_CAMPOS if getattr(ficha, c) is None]  # a v1 zera o valor
        return nota_nao_verificavel(motivo, faltando)
    if ficha.aplica is True:
        faltando = [c for c in _ORDEM_DOS_CAMPOS if getattr(ficha, c) is None]
        motivo = "; ".join(
            f"{_NOME_DO_CAMPO[c]} vazio ({ficha.motivos.get(c) or 'sem motivo'})" for c in faltando
        )
        return nota_nao_verificavel(motivo, faltando)
    # aplica=false: so vira nota se o CODIGO acha temperatura (i04, i10)
    if tem_temperatura(pergunta):
        return nota_nao_verificavel(
            "a ficha veio com aplica=false, mas a pergunta tem temperatura (contada pelo código)",
            list(_ORDEM_DOS_CAMPOS),
        )
    return None


async def nota_de_limite(pergunta: str) -> str | None:
    """O passo inteiro (3 e 4). None = nenhuma nota (pergunta sem temperatura, ou
    aplica=false sem temperatura pelo codigo). Nunca levanta."""
    if not precisa_de_ficha(pergunta):
        return None
    try:
        chamar = fabrica_chamar()
        ficha = await asyncio.to_thread(extrair_ficha_v3, pergunta, chamar=chamar)
        return nota_da_ficha(pergunta, ficha)
    except Exception as exc:  # noqa: BLE001 - falha vira NAO VERIFICAVEL, nunca silencio
        _logger.warning("rag_limites: a ficha falhou (%s) - nota NAO VERIFICAVEL", type(exc).__name__)
        return nota_falha(exc)
