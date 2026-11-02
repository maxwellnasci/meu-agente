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
   - o trecho entre a negacao e a keyword so pode conter vocabulario
     OFENSIVO (scan, teste, ataque, explorar...), verbos LEVES (faca,
     realize, execute...) e palavras FUNCIONAIS ou do dominio de
     infraestrutura (o, contra, servidor, producao...). Isso cobre os ecos
     reais ("nunca testar, escanear ou tocar em infraestrutura de
     producao (Contabo, ...)", "nao faca scan no Contabo", "nao teste,
     escaneie ou explore o Contabo"). Qualquer outra palavra ("precisa",
     "relatorio", "site", "pare"...) encerra o escopo: "nao precisa de
     relatorio, faca um scan no Contabo" bloqueia;
   - termo ofensivo DEPOIS de outra keyword tambem encerra o escopo
     ("nunca testar o Amigao e escaneie o Contabo" bloqueia), a menos que
     um novo marcador ("nem") reabra a negacao;
   - virgula/parentese colado logo apos a negacao ("..., nao, escaneie o
     Contabo") e verbo copulativo ("nao e um teste, escaneie...") nao
     abrem escopo.

   Trade-off assumido: uma palavra fora do vocabulario conhecido num eco
   ("nao faca scan AGRESSIVO no Contabo") bloqueia, e o supervisor pode
   repetir ate o limite de iteracoes; o oposto (liberar por engano) seria
   pior. Casos como "nao e um teste, escaneie..." sao tratados, mas nenhuma
   heuristica de texto fecha todas as formas - ver o aviso no topo.

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
    r"\b(?:nunca|jamais|nao|nem|evite|evitar|proibid[oa]s?|ignorad[oa]s?|ignorar|"
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

# Vocabulario OFENSIVO (radicais; qualquer flexao): verbos e substantivos de
# acao contra um alvo. Dentro do escopo de uma negacao eles sao esperados
# ("nao faca SCAN", "nunca realize TESTES"); depois de outra keyword, nao.
_OFFENSIVE_STEMS = (
    "escan", "scan", "nmap", "pentest", "test", "explor", "exploit", "ataq", "atac",
    "varr", "vasculh", "fuzz", "hack", "invad", "invas", "intrus", "brut", "sond",
    "enumer", "ping", "sniff", "injet", "inject", "derrub", "toc", "toq", "mex", "acess",
    "rod", "execut", "tent", "avali", "analis", "verific", "audit", "investig",
    "mape", "util", "usar", "use", "usando",
)  # fmt: skip
# Verbos LEVES que carregam o substantivo de acao ("faca um scan", "realize testes").
_LIGHT_VERB_STEMS = ("fac", "faz", "realiz", "efetu", "inici", "lanc", "aplic", "conduz", "peca", "pedi", "solicit", "mand", "instru", "autoriz", "permit", "deix", "inclu")  # fmt: skip
# Substantivos de infraestrutura: sao OBJETO. Depois de um deles, um termo
# ofensivo finito abre uma nova oracao ("nao teste o servidor, escaneie o
# Contabo") e encerra o escopo da negacao.
_DOMAIN_NOUNS = frozenset(
    ["projeto", "projetos", "servidor", "servidores", "infraestrutura", "infraestruturas", "producao", "rede", "redes", "sistema", "sistemas", "host", "hosts", "alvo", "alvos", "dominio", "dominios", "ip", "ips", "servico", "servicos", "gateway", "openclaw", "n8n"]
)  # fmt: skip
# Palavras FUNCIONAIS e do dominio de infraestrutura que podem aparecer no meio
# de um eco legitimo. Qualquer palavra fora de OFENSIVO/LEVE/FUNCIONAL encerra o escopo.
_FUNCTION_WORDS = frozenset(
    ["o", "a", "os", "as", "um", "uma", "uns", "umas", "no", "na", "nos", "nas", "ao", "aos", "do", "da", "dos", "das", "de", "em", "contra", "sobre", "para", "por", "com", "pelo", "pela", "pelos", "pelas", "que", "se", "qualquer", "nenhum", "nenhuma", "algum", "alguma", "todo", "toda", "todos", "todas", "ativo", "ativos", "ativa", "ativas", "passivo", "remoto", "real", "reais", "direto", "neste", "nesta", "deste", "desta", "desse", "dessa", "esse", "essa", "este", "esta", "isso", "isto", "proprio", "propria", "proprios", "proprias", "nosso", "nossa", "nossos", "nossas", "ele", "ela", "eles", "elas", "lhe", "voce", "voces", "tambem", "mais", "menos", "deve", "devem", "pode", "podem", "poderia", "deveria", "ser", "estar", "sao", "sera", "fica", "ficam", "ficar", "tipo", "tipos", "forma", "formas", "como", "nessa", "nesse", "nessas", "nesses", "dessas", "desses", "seja", "sejam", "ou", "e"]
) | _DOMAIN_NOUNS  # fmt: skip
_NON_FINITE_SUFFIX_RE = re.compile(r"(?:ar|er|ir|or|ando|endo|indo|ado|ados|ada|adas|ido|idos)$")
# Primeira palavra apos a negacao que NAO abre escopo ofensivo (copula: "nao e um teste, ...").
_COPULAS = frozenset({"e", "eh", "sao", "foi", "era", "sera", "ha"})

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


def _is_offensive(word: str) -> bool:
    return word.startswith(_OFFENSIVE_STEMS)


def _is_light_verb(word: str) -> bool:
    return word.startswith(_LIGHT_VERB_STEMS)


def _has_finite_action_verb(text: str) -> bool:
    """True se `text` tem termo ofensivo em forma finita/imperativa (nao
    infinitivo/participio)."""
    for word in re.findall(r"[a-z0-9]+", text):
        if _is_offensive(word) and not _NON_FINITE_SUFFIX_RE.search(word):
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
    modulo): so vocabulario ofensivo/leve/funcional no meio, nada ofensivo
    depois de outra keyword, e a negacao nao termina em virgula/copula."""
    if re.match(r"\s*[,;:()]", between):
        return False  # "nao, escaneie o Contabo": a negacao nao governa nada
    first = re.match(r"\s*([a-z0-9]+)", between)
    if first and first.group(1) in _COPULAS:
        return False  # "nao e um teste, escaneie o Contabo"

    keyword_hits = list(_KEYWORD_RE.finditer(between))
    if keyword_hits:
        tail = between[keyword_hits[-1].end() :]
        if any(_is_offensive(w) for w in re.findall(r"[a-z0-9]+", tail)):
            return False  # "nunca testar o Amigao e escaneie o Contabo"

    vocabulary_only = _KEYWORD_RE.sub(" ", between)
    object_seen = False
    for word in re.findall(r"[a-z0-9]+", vocabulary_only):
        if object_seen and _is_offensive(word) and not _NON_FINITE_SUFFIX_RE.search(word):
            return False  # "nao teste o servidor, escaneie o Contabo": nova oracao
        if word in _DOMAIN_NOUNS:
            object_seen = True
        if _is_offensive(word) or _is_light_verb(word) or word in _FUNCTION_WORDS:
            continue
        return False  # palavra fora do vocabulario: encerra o escopo
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
