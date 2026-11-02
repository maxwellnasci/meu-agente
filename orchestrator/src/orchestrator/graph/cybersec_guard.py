"""Gate de autorizacao do Especialista de Ciberseguranca.

Camada de defesa em profundidade, em Python puro, que roda ANTES de
qualquer chamada ao Especialista (LLM/agente) - nao depende do LLM
respeitar a instrucao do system prompt. Isto NAO substitui o prompt de
autorizacao enviado ao especialista (ver `nodes.py`); e um bloqueio
adicional, incontornavel, para os alvos mais criticos conhecidos
(infra de producao propria), que nunca devem ser tocados por este
especialista independentemente do que a instrucao diga.

Limite assumido (leia antes de confiar): isto e uma DENYLIST heuristica
sobre texto livre. Ela fecha as evasoes triviais e baratas, mas nao
substitui controles de rede: o isolamento real do alvo vem do sandbox do
especialista (sem acesso a rede de producao) e, idealmente, de uma
ALLOWLIST de alvos autorizados (ver SECURITY.md). Nao ha heuristica de
texto que resolva sozinha prompt injection (OWASP LLM01).

Duas camadas:

1. Alvos protegidos configuraveis (`Settings.protected_targets`: IPs e
   dominios de producao). Bloqueiam SEMPRE, sem a excecao de negacao: nao
   ha eco legitimo de um IP no system prompt do supervisor, entao nao ha
   motivo para tolerar "nao esqueca de escanear <IP>".

2. Nomes de servicos de producao (Contabo, Amigao, chatwoot...). Aqui a
   excecao de negacao existe por um motivo real: o
   `_SUPERVISOR_SYSTEM_PROMPT` instrui o supervisor a lembrar o
   especialista de "nunca testar Contabo/Amigao/...". Se o LLM ecoa essa
   advertencia na instrucao delegada, um match ingenuo bloqueia uma
   instrucao que PROIBE o alvo, e a mensagem de recusa (que repete as
   keywords) realimenta o supervisor ate o limite de iteracoes (bug real
   observado em producao).

   Mas a excecao so vale quando a negacao GOVERNA a keyword (achado da
   auditoria de 2026-11-02: antes, qualquer "nao " na sentenca, antes OU
   depois da keyword, liberava "escaneie o Contabo e nao pare"):

   - a negacao precisa PRECEDER a keyword, na mesma frase (; : e
     conjuncoes adversativas como "mas" encerram o escopo);
   - todo verbo de acao entre a negacao e a keyword precisa estar no
     infinitivo/participio ("nunca testar, escanear ou tocar em ...",
     que e o formato real dos prompts). Um imperativo so e aceito
     IMEDIATAMENTE apos a negacao ("nao escaneie o Contabo"); um
     imperativo mais adiante ("nao precisa de relatorio, escaneie o
     Contabo") quebra o escopo e bloqueia.

   - negacao POSPOSTA so vale como participio que qualifica a keyword
     ("o alvo Contabo deve ser ignorado") e desde que a keyword nao seja
     objeto de um verbo de acao finito ("escaneie o Contabo, que sera
     ignorado" bloqueia). Adverbio solto depois da keyword ("... e nao
     pare") nunca libera.

   A comparacao ignora acento, caixa, caracteres invisiveis, leetspeak
   (c0ntabo) e separadores entre letras (con-tabo, con.tabo).
"""

import re
import unicodedata

from orchestrator.config import settings

# Frases: pontuacao final, quebra de linha e - de proposito - ";" e ":",
# que encerram o escopo de uma negacao ("nunca falha: escaneie o Contabo").
_SENTENCE_SPLIT_RE = re.compile(r"[.!?\n;:]+")
# Conjuncoes adversativas / sequenciais tambem encerram o escopo.
_CONTRAST_RE = re.compile(r"\s+(?:mas|porem|contudo|entao|depois|so que)\s+")

# Marcadores de negacao/proibicao (ja sem acento, ver `_fold`).
_NEGATION_RE = re.compile(
    r"\b(?:nunca|jamais|nao|evite|evitar|proibid[oa]s?|ignorad[oa]s?|ignorar|"
    r"excluir|excluid[oa]s?|desconsidere|desconsiderar|sem autorizacao)\b"
)

# Participios que QUALIFICAM a keyword que veio ANTES ("o alvo Contabo deve ser
# ignorado") - eco real do supervisor. Diferente de "nao", que e um adverbio
# solto: "escaneie o Contabo e nao pare" NAO deve ser liberado por ele.
_POST_NEGATION_RE = re.compile(r"\b(?:ignorad[oa]s?|excluid[oa]s?|desconsiderad[oa]s?|proibid[oa]s?|fora de escopo)\b")

# Palavras-chave da infraestrutura de producao propria (servidor Contabo:
# Amigao/OpenClaw gateway, n8n, chatwoot, evolution-api, WhatsApp Cloud).
# Atualizar esta lista sempre que um novo servico de producao entrar no ar.
# Formas ja sem acento, em minusculas; variantes sem separador cobrem
# "evolution-api"/"evolution_api"/"evolution.api" apos `_strip_separators`.
# "n8n" sozinho e comum demais (nome de ferramenta generica) - so bloqueia
# quando aparece junto de um termo que amarra a producao propria.
_PRODUCTION_INFRA_KEYWORDS = (
    "contabo",
    "amigao",
    "evolution-api",
    "evolution api",
    "evolutionapi",
    "whatsapp cloud",
    "whatsapp-cloud",
    "whatsappcloud",
    "chatwoot",
)
_KEYWORD_RE = re.compile("|".join(re.escape(k) for k in _PRODUCTION_INFRA_KEYWORDS))

# Verbos/termos de acao ofensiva. Infinitivo/participio sao aceitos dentro
# do escopo de uma negacao; formas finitas/imperativas, so logo apos ela.
_ACTION_STEM_RE = re.compile(
    r"^(?:escan|scan|nmap|pentest|test|explor|exploit|ataq|varr|fuzz|hack|invad|"
    r"brute|toc|mex|acess|rod|execut|enumer|sond|ping)\w*$"
)
_NON_FINITE_SUFFIX_RE = re.compile(r"(?:ar|er|ir|or|ando|endo|indo|ado|ados|ada|adas|ido|idos)$")

_LEET_TABLE = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_SEPARATORS_RE = re.compile(r"(?<=[a-z0-9])[._\-*](?=[a-z0-9])")

_REFUSAL_MESSAGE = (
    "RECUSADO: a instrucao menciona infraestrutura de producao propria "
    "(Contabo/Amigao/n8n/chatwoot/evolution-api/WhatsApp Cloud), que este "
    "especialista nunca pode escanear, testar ou explorar - regra dura, "
    "sem excecao. Se a intencao era outra, reformule a instrucao apontando "
    "claramente para um alvo de teste que voce controla e autoriza."
)


def _fold(text: str) -> str:
    """Minusculas, sem acento e sem caracteres invisiveis (zero-width etc.)."""
    decomposed = unicodedata.normalize("NFKD", text)
    kept = (c for c in decomposed if unicodedata.category(c) not in ("Mn", "Cf"))
    return "".join(kept).lower()


def _strip_separators(text: str) -> str:
    return _SEPARATORS_RE.sub("", text)


def _variants(folded: str) -> tuple[str, ...]:
    leet = folded.translate(_LEET_TABLE)
    return (folded, leet, _strip_separators(folded), _strip_separators(leet))


def _protected_targets() -> list[str]:
    return [t for t in (part.strip().lower() for part in settings.protected_targets.split(",")) if t]


def _mentions_protected_target(folded: str) -> bool:
    for target in _protected_targets():
        pattern = r"(?<![a-z0-9])" + re.escape(target) + r"(?![a-z0-9])"
        if re.search(pattern, folded):
            return True
    return False


def _has_finite_action_verb(text: str) -> bool:
    """True se `text` tem verbo/termo de acao em forma finita/imperativa."""
    for word in re.findall(r"[a-z0-9]+", text):
        if _ACTION_STEM_RE.match(word) and not _NON_FINITE_SUFFIX_RE.search(word):
            return True
    return False


def _qualified_by_post_negation(part: str, hit: "re.Match[str]") -> bool:
    """Negacao posposta ("... Contabo deve ser ignorado"): vale so se a
    keyword NAO for objeto de um verbo de acao finito antes dela nem entre ela
    e o participio."""
    cue = _POST_NEGATION_RE.search(part, hit.end())
    if cue is None:
        return False
    return not _has_finite_action_verb(part[: hit.start()]) and not _has_finite_action_verb(part[hit.end() : cue.start()])


def _is_governed_by_negation(between: str) -> bool:
    """`between` = trecho entre o fim do marcador de negacao e o inicio da
    keyword. True se a negacao realmente governa a keyword (ver docstring do
    modulo): nenhum verbo de acao em forma finita fora da posicao imediata."""
    for match in re.finditer(r"[a-z0-9]+", between):
        word = match.group(0)
        if not _ACTION_STEM_RE.match(word) or _NON_FINITE_SUFFIX_RE.search(word):
            continue
        # forma finita/imperativa/substantivo de acao: so vale se vier
        # imediatamente apos a negacao (so espacos entre os dois).
        if between[: match.start()].strip():
            return False
    return True


def _text_blocked(folded: str) -> bool:
    for sentence in _SENTENCE_SPLIT_RE.split(folded):
        for part in _CONTRAST_RE.split(sentence):
            cues = list(_NEGATION_RE.finditer(part))
            for hit in _KEYWORD_RE.finditer(part):
                preceding = [c for c in cues if c.end() <= hit.start()]
                if preceding and _is_governed_by_negation(part[preceding[-1].end() : hit.start()]):
                    continue
                if _qualified_by_post_negation(part, hit):
                    continue
                return True
    return False


def check_production_infra_block(instructions: str) -> str | None:
    """Retorna uma mensagem de recusa se a instrucao referenciar infra de
    producao propria conhecida como um pedido de acao real (nao como
    proibicao/exemplo, ver modulo); None se nao houver match (ou seja, ok
    para seguir para o especialista, que ainda aplica seu proprio
    julgamento de autorizacao via system prompt)."""
    folded = _fold(instructions)

    if _mentions_protected_target(folded):
        return _REFUSAL_MESSAGE

    # Qualquer variante bloqueando basta: as variantes (leetspeak, separadores
    # removidos) so podem ADICIONAR bloqueios, nunca liberar o que a forma
    # original bloquearia.
    if any(_text_blocked(variant) for variant in _variants(folded)):
        return _REFUSAL_MESSAGE
    return None
