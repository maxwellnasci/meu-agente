"""Gate de autorizacao do Especialista de Ciberseguranca.

Camada de defesa em profundidade, em Python puro, que roda ANTES de
qualquer chamada ao Especialista (LLM/agente) - nao depende do LLM
respeitar a instrucao do system prompt. Isto NAO substitui o prompt de
autorizacao enviado ao especialista (ver `nodes.py`); e um bloqueio
adicional, incontornavel, para os alvos mais criticos conhecidos
(infra de producao propria), que nunca devem ser tocados por este
especialista independentemente do que a instrucao diga.

Deliberadamente simples (checagem de substring por sentenca,
case-insensitive): o objetivo nao e classificar toda instrucao ambigua
(isso fica a cargo do julgamento do proprio especialista, orientado
pelo system prompt), so impedir com certeza os alvos de producao
conhecidos listados abaixo.

A checagem e por sentenca (nao pelo texto inteiro) porque o
`_SUPERVISOR_SYSTEM_PROMPT` (ver `nodes.py`) instrui o proprio
supervisor a lembrar o especialista, na instrucao que ele gera, de
"nunca testar Contabo/Amigao/n8n/...". Se o LLM do supervisor ecoa essa
advertencia (comportamento comum de LLM: reforcar a regra na instrucao
delegada), um match ingenuo de substring bloqueia uma instrucao que na
verdade PROIBE o alvo de producao, nao que o solicita - e a propria
mensagem de recusa repete as keywords, alimentando a proxima rodada do
supervisor e causando loop ate o limite de iteracoes (bug real
observado em producao). Por isso, uma sentenca so conta como pedido de
acao se a keyword aparecer nela SEM um marcador de negacao (ver
`_NEGATION_CUES`) na mesma sentenca - "escaneia o Contabo" bloqueia,
"nunca testar o Contabo" nao.
"""

import re

_SENTENCE_SPLIT_RE = re.compile(r"[.!?\n]+")

# Marcadores de negacao/proibicao em portugues: quando aparecem na MESMA
# sentenca que a keyword de infra, a mencao e tratada como advertencia/
# exemplo proibido (ex.: eco do system prompt do supervisor), nao como
# pedido de acao contra o alvo.
_NEGATION_CUES = (
    "nunca",
    "jamais",
    "nao ",
    "nao-",
    "não ",
    "não-",
    "evite",
    "evitar",
    "proibido",
    "proibida",
    "sem autorizacao",
    "sem autorização",
)

# Palavras-chave da infraestrutura de producao propria (servidor Contabo:
# Amigao/OpenClaw gateway, n8n, chatwoot, evolution-api, WhatsApp Cloud).
# Atualizar esta lista sempre que um novo servico de producao entrar no ar.
_PRODUCTION_INFRA_KEYWORDS = (
    "contabo",
    "amigao",
    "amigão",
    "evolution-api",
    "evolution api",
    "whatsapp cloud",
    "whatsapp-cloud",
    "chatwoot",
    # "n8n" sozinho e comum demais (nome de ferramenta generica) - so bloqueia
    # quando aparece junto de um termo que amarra a producao propria.
)

_REFUSAL_MESSAGE = (
    "RECUSADO: a instrucao menciona infraestrutura de producao propria "
    "(Contabo/Amigao/n8n/chatwoot/evolution-api/WhatsApp Cloud), que este "
    "especialista nunca pode escanear, testar ou explorar - regra dura, "
    "sem excecao. Se a intencao era outra, reformule a instrucao apontando "
    "claramente para um alvo de teste que voce controla e autoriza."
)


def check_production_infra_block(instructions: str) -> str | None:
    """Retorna uma mensagem de recusa se a instrucao referenciar infra de
    producao propria conhecida como um pedido de acao real (nao como
    proibicao/exemplo, ver modulo); None se nao houver match (ou seja, ok
    para seguir para o especialista, que ainda aplica seu proprio
    julgamento de autorizacao via system prompt)."""
    lowered = instructions.lower()
    for sentence in _SENTENCE_SPLIT_RE.split(lowered):
        has_keyword = any(keyword in sentence for keyword in _PRODUCTION_INFRA_KEYWORDS)
        if not has_keyword:
            continue
        has_negation = any(cue in sentence for cue in _NEGATION_CUES)
        if not has_negation:
            return _REFUSAL_MESSAGE
    return None
