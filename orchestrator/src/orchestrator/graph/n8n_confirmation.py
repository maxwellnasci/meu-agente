"""Gate de confirmacao explicita para acoes n8n que MUDAM producao.

Contexto (incidente 2026-09-05, ver ANALISE_CEREBRO_AGENTE_CONTABO_2026-09-06.md):
o especialista n8n criou E ativou um workflow em producao a partir de uma
mensagem de 4 palavras ("Me avisa quando apagar"), sem ninguem aprovar. O
`n8n_guard.py` so cobre delete/deactivate por heuristica de verbo; create e
activate passavam direto.

Este modulo adiciona uma etapa dura, em Python puro (nao depende do LLM), que
exige uma confirmacao do usuario ANTES de executar qualquer uma destas quatro
acoes:

    N8nCreateWorkflow   -> "create"
    N8nActivateWorkflow -> "activate"
    N8nDeactivateWorkflow -> "deactivate"
    N8nDeleteWorkflow   -> "delete"

Leitura/listagem (`N8nListWorkflows`, `N8nGetWorkflow`) e `N8nTriggerWebhook`
NAO passam por aqui - so as quatro que mudam o cadastro de workflows.

Propriedades da confirmacao:
  - explicita: o usuario precisa responder afirmativamente ("sim", "pode",
    "confirmo"...) num turno POSTERIOR ao da proposta;
  - persistente: a pendencia vive em `GraphState.n8n_pending_confirmation`,
    que sobrevive ao `fresh_turn_input` e e gravada pelo checkpointer;
  - vinculada a acao e ao workflow: a pendencia guarda a tool, os args e o
    `workflow_id` exatos; a execucao usa exatamente esses valores;
  - com expiracao: `expires_at` (config `n8n_confirmation_ttl_sec`);
  - uso unico: um `token` aleatorio; ao executar (ou recusar, ou expirar) a
    pendencia e apagada. Repetir o "sim" nao re-executa nada.

Regra derivada (requisito do incidente): "criar" nunca ativa no mesmo turno -
`N8nCreateWorkflow` cria o workflow INATIVO e `N8nActivateWorkflow` exige a
sua propria confirmacao, num turno a parte.
"""

import time
import unicodedata
import uuid

# tool (schemas/n8n_tools.py) -> verbo curto da acao. A presenca nesta tabela
# e o que define "acao que muda producao e precisa de confirmacao".
WRITE_ACTIONS: dict[str, str] = {
    "N8nCreateWorkflow": "create",
    "N8nActivateWorkflow": "activate",
    "N8nDeactivateWorkflow": "deactivate",
    "N8nDeleteWorkflow": "delete",
}

# Marcador que `_run_n8n_tool` devolve (em vez de executar) quando uma acao de
# escrita ainda nao tem confirmacao valida. O `specialist_n8n_node` detecta
# esta chave, grava a pendencia no estado e encerra o turno pedindo o "sim".
NEEDS_CONFIRMATION_KEY = "__n8n_needs_confirmation__"

_AFFIRMATIVE = {
    "sim", "s", "isso", "isso mesmo", "exato", "exatamente", "confirmo",
    "confirmado", "confirma", "confirmar", "pode", "pode sim", "pode ser",
    "pode fazer", "podes", "manda", "manda ver", "manda bala", "vai",
    "vai la", "faz", "faca", "faze", "bora", "ok", "okay", "okk", "beleza",
    "blz", "aprovo", "aprovado", "autorizo", "autorizado", "certo",
    "positivo", "claro", "com certeza", "sigo", "segue", "prossiga",
    "prossegue", "yes", "y", "👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿",
}

_NEGATIVE = {
    "nao", "n", "nao pode", "nao quero", "nega", "negativo", "cancela",
    "cancelar", "cancelado", "deixa", "deixa pra la", "esquece", "para",
    "parar", "melhor nao", "nem", "nunca", "no", "abortar", "aborta",
    "nao faz", "nao faca", "nao precisa", "para tudo",
}


def _now() -> float:
    return time.time()


def _normalize(text: str) -> str:
    """Minusculas, sem acento, sem pontuacao das pontas, espacos colapsados."""
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    cleaned = "".join(c if (c.isalnum() or c.isspace()) else " " for c in stripped)
    return " ".join(cleaned.lower().split())


def is_write_action(tool_name: str) -> bool:
    return tool_name in WRITE_ACTIONS


def describe_action(action: str, workflow_id: str | None, workflow_name: str | None) -> str:
    """Frase curta, para o usuario, do que a acao vai fazer em producao."""
    label = workflow_name and f"'{workflow_name}'" or (workflow_id and f"id {workflow_id}") or "o workflow"
    if action == "create":
        return (
            f"criar um novo workflow {label} na instancia de n8n de producao. "
            "Ele nasce INATIVO (ativar depois exige uma confirmacao a parte)."
        )
    if action == "activate":
        return (
            f"ATIVAR o workflow {label} em producao - os triggers automaticos "
            "(webhook, agendamento) passam a valer de verdade."
        )
    if action == "deactivate":
        return f"DESATIVAR o workflow {label} em producao - os triggers automaticos deixam de disparar."
    if action == "delete":
        return f"EXCLUIR PERMANENTEMENTE o workflow {label} da instancia de n8n de producao."
    return f"executar a acao '{action}' sobre {label}."


def build_pending_confirmation(tool_name: str, args: dict, ttl_sec: int) -> dict:
    """Monta o registro de pendencia gravado em `n8n_pending_confirmation`."""
    action = WRITE_ACTIONS[tool_name]
    workflow_id = args.get("workflow_id")
    workflow_name = args.get("name")
    now = _now()
    return {
        "token": uuid.uuid4().hex,
        "tool_name": tool_name,
        "action": action,
        "workflow_id": workflow_id,
        "workflow_name": workflow_name,
        "args": args,
        "created_at": now,
        "expires_at": now + max(1, int(ttl_sec)),
        "summary": describe_action(action, workflow_id, workflow_name),
    }


def get_valid_pending_confirmation(pending: object, now: float | None = None) -> dict | None:
    """Retorna a pendencia se ela e um registro bem-formado e ainda nao
    expirou; None caso contrario (inclui expirada - que deve ser limpa pelo
    chamador)."""
    now = _now() if now is None else now
    if not isinstance(pending, dict):
        return None
    if not pending.get("token") or not pending.get("tool_name"):
        return None
    if now >= pending.get("expires_at", 0):
        return None
    return pending


def classify_confirmation_reply(text: str) -> str:
    """Classifica a mensagem do usuario como resposta a uma pendencia:
    "affirm", "deny" ou "unclear".

    Deliberadamente ESTRITO: so devolve "affirm"/"deny" para mensagens
    curtas e inequivocas. Qualquer coisa com conteudo extra ("sim, mas muda
    o nome", "pode apagar o outro") vira "unclear" - o lado seguro, ja que
    um falso "affirm" executa uma acao em producao. Negacao e checada antes
    da afirmacao ("nao pode" nao pode virar "pode").
    """
    norm = _normalize(text)
    if not norm:
        return "unclear"
    if norm in _NEGATIVE:
        return "deny"
    if norm in _AFFIRMATIVE:
        return "affirm"
    # tolera pontuacao/educacao minima: ate 3 tokens, ex. "sim por favor",
    # "pode sim", "nao obrigado".
    tokens = norm.split()
    if len(tokens) <= 3:
        joined = " ".join(tokens)
        if joined in _NEGATIVE or any(t in _NEGATIVE for t in tokens):
            return "deny"
        if joined in _AFFIRMATIVE or (
            any(t in _AFFIRMATIVE for t in tokens) and not any(t in _NEGATIVE for t in tokens)
        ):
            return "affirm"
    return "unclear"
