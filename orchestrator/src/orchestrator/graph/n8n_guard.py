"""Gate de acao destrutiva do Especialista de Automacao (n8n).

Mesma filosofia do cybersec_guard.py: bloqueio em Python puro, incontornavel,
que roda ANTES de qualquer chamada de tool destrutiva contra a instancia real
de n8n em producao (https://n8n.mxos.com.br) - nao depende do LLM respeitar a
"REGRA DE CAUTELA" do system prompt (ver `_N8N_SYSTEM_PROMPT` em nodes.py).

Escopo deliberadamente minimo: so bloqueia as duas tools cujo efeito sobre um
workflow PRE-EXISTENTE e dificil ou impossivel de desfazer - deletar (perda
permanente) e desativar (interrompe producao). Create/update/activate ficam
de fora: sao reversiveis (dá pra editar de novo ou reativar) e o objetivo
aqui e so fechar a janela de "o LLM decide sozinho apagar/parar algo que
ninguem pediu", nao microgerenciar toda chamada de tool.
"""

# Radicais (nao palavras inteiras) para cobrir conjugacoes em portugues
# ("deleta", "deletar", "deletando", "delete" em ingles...) sem precisar
# enumerar cada forma verbal.
_DESTRUCTIVE_TOOL_CUES = {
    "N8nDeleteWorkflow": ("delet", "apag", "exclu", "remov"),
    "N8nDeactivateWorkflow": ("desativ", "pause", "pausa"),
}

_REFUSAL_TEMPLATE = (
    "RECUSADO: a tool {tool} e destrutiva/interrompe producao e a instrucao "
    "da tarefa nao pede isso explicitamente (nenhum destes verbos presente: "
    "{verbs}). Se a intencao era essa, reformule a instrucao com o verbo "
    "explicito e o workflow alvo."
)


def check_destructive_n8n_action(tool_name: str, instructions: str) -> str | None:
    """Retorna uma mensagem de recusa se `tool_name` for uma tool destrutiva
    e a instrucao original da tarefa nao contiver nenhum verbo que autorize
    aquela acao explicitamente; None libera a chamada (tool nao-destrutiva,
    ou instrucao ja contem o verbo esperado)."""
    cues = _DESTRUCTIVE_TOOL_CUES.get(tool_name)
    if cues is None:
        return None
    lowered = instructions.lower()
    if any(cue in lowered for cue in cues):
        return None
    return _REFUSAL_TEMPLATE.format(tool=tool_name, verbs="/".join(cues))
