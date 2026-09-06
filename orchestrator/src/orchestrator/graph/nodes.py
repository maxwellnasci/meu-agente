import json
import logging
import time

import httpx
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI

from orchestrator.clients.n8n_client import N8nClient
from orchestrator.clients.openclaw_client import OpenClawClient
from orchestrator.config import settings
from orchestrator.graph.cybersec_guard import check_production_infra_block
from orchestrator.graph.n8n_confirmation import (
    NEEDS_CONFIRMATION_KEY,
    build_pending_confirmation,
    classify_confirmation_reply,
    get_valid_pending_confirmation,
    is_write_action,
)
from orchestrator.graph.n8n_guard import check_destructive_n8n_action
from orchestrator.graph.state import GraphState, PendingSpecialist
from orchestrator.schemas.n8n_tools import (
    N8nActivateWorkflow,
    N8nCreateWorkflow,
    N8nDeactivateWorkflow,
    N8nDeleteWorkflow,
    N8nGetWorkflow,
    N8nListWorkflows,
    N8nTriggerWebhook,
    N8nUpdateWorkflow,
)
from orchestrator.schemas.requests import SpecialistCallRequest
from orchestrator.schemas.routing import (
    DispatchSpecialist,
    RouteDestination,
    SpecialistName,
)

# Mapa especialista -> no do grafo que sabe executa-lo. Chave amarrada a
# SpecialistName (schemas/routing.py): adicionar um especialista novo e
# adicionar um no + uma entrada aqui + um valor no Enum.
SPECIALIST_ROUTES = {
    SpecialistName.OPENCLAW.value: "specialist_openclaw",
    SpecialistName.CYBERSEC.value: "specialist_cybersec",
    SpecialistName.N8N.value: "specialist_n8n",
}

# Tools reais do especialista n8n (bind_tools) - cada uma mapeia 1:1 para um
# metodo de N8nClient via _run_n8n_tool. Diferente do OpenClaw/cybersec (que
# delegam a execucao real a um agent externo via HTTP), o n8n nao tem um
# "agent" por tras: o tool-calling roda aqui mesmo, dentro do orquestrador.
_N8N_TOOLS = [
    N8nListWorkflows,
    N8nGetWorkflow,
    N8nCreateWorkflow,
    N8nUpdateWorkflow,
    N8nDeleteWorkflow,
    N8nActivateWorkflow,
    N8nDeactivateWorkflow,
    N8nTriggerWebhook,
]

# Trava de loop do ReAct manual do especialista n8n: quantas rodadas de
# tool-calling ele pode fazer numa unica tarefa antes de desistir e reportar
# erro (nao existe supervisor de fora vigiando esse loop interno).
_N8N_MAX_STEPS = 6

_N8N_SYSTEM_PROMPT = (
    "Voce e o Especialista de Automacao (n8n) de um enxame de agentes de IA. "
    "Voce tem tool-calling real contra a API REST de uma instancia de n8n "
    "que roda em PRODUCAO (https://n8n.mxos.com.br) - toda chamada de tool "
    "tem efeito real e imediato nessa instancia (criar/editar/deletar/"
    "ativar/desativar/disparar workflows de verdade).\n\n"
    "REGRA DE CAUTELA (nao-negociavel): so edite, desative, delete ou "
    "dispare um workflow PRE-EXISTENTE (que voce nao criou nesta mesma "
    "tarefa) se a instrucao pedir isso explicitamente para aquele workflow "
    "especifico. Para pedidos exploratorios ou ambiguos ('o que tem ali', "
    "'organiza isso'), prefira listar/consultar e descrever o que "
    "encontrou em vez de alterar algo que ja esta rodando.\n\n"
    "REGRA DE CONFIRMACAO (nao-negociavel): criar, ativar, desativar e "
    "deletar workflow sao acoes que MUDAM producao e passam por uma etapa "
    "de confirmacao do usuario FORA do seu controle - ao chamar uma dessas "
    "tools, a acao NAO e executada na hora: vira uma proposta que o usuario "
    "precisa confirmar num proximo turno. Por isso: (a) proponha UMA acao de "
    "escrita por vez; (b) nunca chame ativar logo apos criar - a criacao ja "
    "deixa o workflow inativo e a ativacao e um passo separado, com a sua "
    "propria confirmacao; (c) nao repita a mesma tool esperando que 'passe' "
    "na segunda - descreva o que vai fazer e pare.\n\n"
    "REGRA DE TRIGGER (tecnica, causa comum de falha): o n8n so ativa um "
    "workflow se o primeiro node for um TRIGGER de verdade, nao uma acao "
    "comum. Muitos nodes tem uma versao 'action' (le/busca sob demanda) E "
    "uma versao 'trigger' (dispara sozinho) com nomes parecidos - use "
    "sempre a versao trigger quando o workflow precisar rodar automatico. "
    "Exemplos: 'n8n-nodes-base.rssFeedReadTrigger' (nao "
    "'n8n-nodes-base.rssFeedRead'), 'n8n-nodes-base.scheduleTrigger' para "
    "rodar em intervalos/horarios, 'n8n-nodes-base.webhook' para disparo "
    "por HTTP. Se a ativacao falhar com erro do tipo "
    "'must have at least one trigger node' ou 400 generico logo apos criar/"
    "editar, o motivo quase sempre e esse - troque o node inicial pela "
    "variante trigger e tente de novo, em vez de repetir a mesma chamada "
    "de ativacao ou desistir.\n\n"
    "REGRA DO 'BASICO' (quando o pedido for vago tipo 'cria algo simples/"
    "basico pra testar'): construa algo minimamente funcional de verdade - "
    "um trigger real (schedule ou webhook) ligado a uma acao real e simples "
    "(ex.: um noOp ou um setNode que so passa um valor adiante) - nunca "
    "dois nodes vazios (noOp -> noOp) sem trigger nenhum. 'Basico' e sobre "
    "a COMPLEXIDADE da automacao, nao sobre ela nao ter trigger ou nao "
    "fazer nada.\n\n"
    "Use as tools disponiveis para executar a instrucao de verdade - nunca "
    "apenas descreva em texto o que faria. Quando a tarefa estiver "
    "concluida (ou quando precisar desistir por algum bloqueio), responda "
    "em texto, sem chamar nenhuma tool: esse texto vai direto para o "
    "scratchpad compartilhado do enxame, entao resuma objetivamente o que "
    "foi executado (quais workflows, quais operacoes)."
)

# Catalogo de skills de ciberseguranca que o Especialista (executado via
# gateway OpenClaw, que tem acesso a tool Skill) pode invocar de fato.
# Mantido aqui (nao no OpenClaw) porque e o `supervisor`/especialista deste
# orquestrador que decide/orienta qual skill usar - texto injetado no prompt
# de `specialist_cybersec_node`.
_CYBERSEC_SKILLS_CATALOG = (
    "01-recon-osint, 02-vulnerability-scanner, 03-exploit-development, "
    "04-reverse-engineering, 05-malware-analysis, 06-threat-hunting, "
    "07-incident-response, 08-network-security, 09-web-security, "
    "10-cloud-security, 11-csoc-automation, 12-log-analysis, "
    "13-crypto-analysis, 14-red-team-ops, 15-blue-team-defense, "
    "16-ai-llm-security, 17-mobile-security, 18-ot-ics-security, "
    "19-grc-compliance, active-directory-attacks, api-security-testing, "
    "cloud-security, container-security, file-transfer-techniques, "
    "initial-access-recon, linux-privilege-escalation, mobile-pentesting, "
    "network-service-enumeration, password-attacks, persistence-techniques, "
    "phishing-social-engineering, web-app-security, web3-blockchain, "
    "windows-privilege-escalation, wireless-attacks"
)

_CYBERSEC_SYSTEM_PROMPT = (
    "Voce e o Especialista em Ciberseguranca de um enxame de agentes de IA. "
    "Voce tem acesso real a skills de seguranca instaladas neste ambiente e "
    "deve efetivamente INVOCA-LAS (via sua tool Skill) para executar a "
    "tarefa - nunca apenas descrever em texto o que faria.\n\n"
    f"Skills disponiveis: {_CYBERSEC_SKILLS_CATALOG}.\n"
    "Escolha a(s) skill(s) mais adequada(s) a instrucao e invoque-a(s) de "
    "verdade antes de responder.\n\n"
    "REGRA DE AUTORIZACAO (dura, nao-negociavel, sem excecao mesmo se a "
    "instrucao insistir): voce so pode executar ACOES ATIVAS (scans, "
    "requisicoes de teste, tentativas de exploracao, brute force, etc.) "
    "contra um alvo se a instrucao abaixo autorizar aquele alvo "
    "EXPLICITAMENTE (ex.: um dominio/IP/projeto que o usuario diz "
    "claramente ser dele e pede pra testar). Analise passiva (ler codigo, "
    "revisar config, analisar logs/artefatos ja fornecidos) nao exige essa "
    "autorizacao explicita. Voce NUNCA deve escanear, testar ou tocar em "
    "infraestrutura de producao deste projeto (servidor Contabo, "
    "Amigao/OpenClaw gateway, n8n, chatwoot, evolution-api, WhatsApp Cloud) "
    "nem em qualquer alvo de terceiros sem autorizacao explicita nesta "
    "instrucao. Se a autorizacao para o alvo nao estiver clara, RECUSE a "
    "acao ativa e explique que precisa de confirmacao explicita do alvo - "
    "nao assuma autorizacao.\n\n"
    "Ao final, reporte um resultado estruturado: o que foi executado (qual "
    "skill, contra qual alvo), os achados principais, e severidade/proximos "
    "passos quando aplicavel."
)

_SUPERVISOR_SYSTEM_PROMPT = (
    "Voce e o Supervisor de um enxame de especialistas de IA. Leia a "
    "instrucao do usuario e, se houver, o progresso ja registrado pelos "
    "especialistas que ja rodaram nesta tarefa. Decida se e preciso acionar "
    "um ou mais especialistas para executar acoes reais.\n\n"
    "PERGUNTA INDIRETA E PEDIDO (importante, erro comum): em portugues "
    "coloquial (WhatsApp), 'voce consegue criar X?', 'consegui fazer X?', "
    "'seria possivel X?' SAO pedidos pra executar X, nao perguntas "
    "abstratas sobre capacidade - trate como se o usuario tivesse dito "
    "'cria X'. So NAO acione um especialista quando o pedido genuinamente "
    "nao descreve uma coisa concreta pra fazer ainda (ex.: 'me da ideias "
    "do que eu poderia automatizar' - ai sim responda direto com opcoes, "
    "sem despachar, e deixe o usuario escolher uma antes de agir). A "
    "diferenca e: o pedido ja descreve UMA automacao/tarefa especifica "
    "(mesmo que simples ou fraseada como pergunta) -> despache. O pedido "
    "pede uma lista de opcoes/ideias em aberto -> responda direto.\n\n"
    "Especialistas disponiveis:\n"
    "- openclaw: Especialista em Programacao - escreve/edita codigo, "
    "executa comandos, mexe em arquivos de um projeto, debuga, roda "
    "testes, ou qualquer acao que precise de um sandbox de execucao real.\n"
    "- cybersec: Especialista em Ciberseguranca - recon/OSINT, scan de "
    "vulnerabilidades, pentest web/API/cloud/rede, analise de log, threat "
    "hunting, etc. Ele so executa acoes ativas (scans/exploits) contra um "
    "alvo que a propria instrucao autorize explicitamente - se o pedido do "
    "usuario nao deixar claro que ele controla e autoriza o alvo, inclua "
    "isso na instrucao para o especialista recusar/pedir confirmacao em vez "
    "de assumir. Nunca peca para ele testar a infraestrutura de producao "
    "deste proprio projeto (Contabo, Amigao, n8n, chatwoot, evolution-api, "
    "WhatsApp Cloud).\n"
    "- n8n: Especialista de Automacao - cria, edita, deleta, ativa/desativa "
    "e dispara execucao de workflows numa instancia de n8n real em "
    "producao, via tool-calling direto contra a API REST dela. Va com "
    "cautela ao pedir para ele mexer em workflows que ja existiam antes "
    "desta tarefa - so instrua isso se o usuario pedir explicitamente.\n\n"
    "Chame a tool DispatchSpecialist uma vez para cada especialista que "
    "precisar acionar (pode chamar mais de uma vez na mesma rodada). Se a "
    "tarefa ja puder ser respondida direto - ou se o progresso registrado "
    "ja e suficiente para concluir - NAO chame nenhuma tool."
)

_SYNTHESIZE_SYSTEM_PROMPT = (
    "Voce e o Cerebro de um orquestrador de agentes de IA, respondendo "
    "diretamente ao usuario numa conversa. Use as notas internas dos "
    "especialistas (se houver) para compor uma resposta natural e util. "
    "Nao mencione que existem especialistas, supervisor ou scratchpad por "
    "tras - do ponto de vista do usuario, voce e quem esta respondendo."
)

_ABORT_MESSAGE = (
    "Desculpa, essa tarefa ficou complexa demais e o orquestrador abortou "
    "por seguranca (limite de iteracoes do supervisor excedido). Tenta "
    "quebrar o pedido em partes menores."
)

_logger = logging.getLogger(__name__)


def extract_task_description(messages: list[BaseMessage]) -> str:
    """Extrai a instrucao mais recente do usuario para preencher o
    SpecialistCallRequest.

    `add_messages` (reducer do campo `messages` em GraphState) normaliza
    entradas em objetos BaseMessage, entao aqui assumimos HumanMessage - nao
    dict solto. Usado tanto pelos nos quanto pelo event_mapper (que le o
    mesmo formato a partir do `input` bruto do astream_events).
    """
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


def _format_scratchpad(scratchpad: list[str]) -> str:
    return "\n\n".join(scratchpad) if scratchpad else ""


async def supervisor_node(state: GraphState) -> dict:
    """No central do Enxame: decide, via tool-calling real (`bind_tools`),
    quais especialistas acionar para a instrucao atual - considerando o
    progresso ja registrado no `internal_scratchpad` quando esta e uma
    rodada de retorno apos especialistas ja terem rodado.

    Cada chamada da tool `DispatchSpecialist` vira um item na fila
    `pending_specialists`; a borda condicional `route_after_supervisor` so
    le essa fila, nao rechama o LLM. Se o LLM nao chamar nenhuma tool
    (tarefa respondivel direto, ou especialistas ja trouxeram o suficiente),
    a fila fica vazia e o grafo segue para `synthesize_final`.

    Trava de loop infinito: cada execucao deste no incrementa
    `iteration_count`. Ao estourar settings.max_supervisor_iterations, pula
    a chamada ao LLM e desvia direto para `synthesize_final` com um erro de
    aborto de seguranca.
    """
    iteration_count = state.get("iteration_count", 0) + 1

    if iteration_count > settings.max_supervisor_iterations:
        _logger.warning("supervisor_node: limite de iteracoes excedido (%d), abortando", iteration_count)
        return {
            "iteration_count": iteration_count,
            "pending_specialists": [],
            "last_error": "limite de iteracoes do supervisor excedido",
        }

    task_description = extract_task_description(state["messages"])
    scratchpad_text = _format_scratchpad(state.get("internal_scratchpad") or [])

    # --- Resolucao de acao n8n pendente de confirmacao --------------------
    # Roda so na primeira rodada do turno (a proposta que o n8n_node cria
    # volta pra ca como iteration 2 - nao e uma confirmacao). Deterministico,
    # antes do LLM: um falso "sim" aqui executa algo em producao.
    raw_pending = state.get("n8n_pending_confirmation")
    stored = get_valid_pending_confirmation(raw_pending)
    if iteration_count == 1 and raw_pending is not None and stored is None:
        # Pendencia existe mas expirou (ou esta malformada): descarta.
        _logger.info("supervisor_node: acao n8n pendente expirada, descartada")
        return {
            "iteration_count": iteration_count,
            "pending_specialists": [],
            "route": RouteDestination.GENERAL.value,
            "n8n_pending_confirmation": "clear",
            "internal_scratchpad": (state.get("internal_scratchpad") or [])
            + ["[n8n] A confirmacao pendente expirou sem resposta - a acao foi descartada e nada foi executado."],
        }
    if iteration_count == 1 and stored is not None:
        verdict = classify_confirmation_reply(task_description)
        if verdict == "affirm":
            _logger.info("supervisor_node: usuario confirmou acao n8n pendente '%s'", stored["action"])
            return {
                "iteration_count": iteration_count,
                "pending_specialists": [
                    {
                        "specialist": SpecialistName.N8N.value,
                        "instructions": f"O usuario CONFIRMOU a acao pendente: {stored['summary']} Execute-a agora.",
                    }
                ],
                "route": RouteDestination.SPECIALIST.value,
                "n8n_confirmed_token": stored["token"],
                "last_error": None,
            }
        if verdict == "deny":
            _logger.info("supervisor_node: usuario recusou acao n8n pendente '%s'", stored["action"])
            return {
                "iteration_count": iteration_count,
                "pending_specialists": [],
                "route": RouteDestination.GENERAL.value,
                "n8n_pending_confirmation": "clear",
                "internal_scratchpad": (state.get("internal_scratchpad") or [])
                + [
                    (
                        f"[n8n] O usuario RECUSOU a acao pendente ({stored['summary']}). "
                        "Ela foi cancelada e NADA foi executado. Confirme o cancelamento ao usuario."
                    )
                ],
            }
        # "unclear": segue o fluxo normal, mas avisa o LLM da pendencia.

    prompt = task_description
    if scratchpad_text:
        prompt += f"\n\nProgresso ja registrado pelos especialistas nesta tarefa:\n{scratchpad_text}"
    if stored is not None:
        prompt += (
            f"\n\nATENCAO: existe uma acao n8n PENDENTE DE CONFIRMACAO ({stored['summary']}). "
            "A mensagem do usuario nao foi um 'sim'/'nao' claro. NAO trate como confirmada. "
            "Se ele estiver ajustando o pedido, voce pode despachar o especialista n8n de novo "
            "para propor a acao corrigida (ela vai pedir nova confirmacao)."
        )
    last_error = state.get("last_error")
    if last_error:
        prompt += f"\n\nUltimo erro reportado por um especialista: {last_error}"

    llm = ChatOpenAI(
        model=settings.router_model,
        temperature=0,
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    ).bind_tools([DispatchSpecialist])

    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=_SUPERVISOR_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )
    except Exception:
        _logger.exception("supervisor_node: falha ao invocar o LLM supervisor, usando fallback openclaw")
        return {
            "iteration_count": iteration_count,
            "pending_specialists": [{"specialist": SpecialistName.OPENCLAW.value, "instructions": task_description}],
            "route": RouteDestination.SPECIALIST.value,
        }

    dispatches = [tc for tc in response.tool_calls if tc["name"] == DispatchSpecialist.__name__]

    if not dispatches:
        _logger.info("supervisor_node: rodada %d, nenhum especialista despachado (rota=general)", iteration_count)
        return {
            "iteration_count": iteration_count,
            "pending_specialists": [],
            "route": RouteDestination.GENERAL.value,
        }

    queue: list[PendingSpecialist] = [
        {"specialist": call["args"]["specialist"], "instructions": call["args"]["instructions"]} for call in dispatches
    ]
    _logger.info(
        "supervisor_node: rodada %d, despachando %d especialista(s): %s",
        iteration_count,
        len(queue),
        [item["specialist"] for item in queue],
    )
    return {
        "iteration_count": iteration_count,
        "pending_specialists": queue,
        "route": RouteDestination.SPECIALIST.value,
        # Limpa o ultimo erro ao iniciar nova rodada de especialistas: se um
        # especialista anterior falhou mas o supervisor decidiu tentar de novo
        # (ou acionar outro especialista), o erro antigo nao deve poluir o
        # synthesize_final caso esta nova rodada bem-suceda.
        "last_error": None,
    }


def route_after_supervisor(state: GraphState) -> str:
    """Borda condicional apos `supervisor`: funcao pura que so le a fila ja
    gravada em `pending_specialists` - nao rechama o LLM. Fila vazia (tarefa
    respondivel direto, especialistas ja trouxeram o suficiente, ou aborto
    por limite de iteracoes) segue para `synthesize_final`."""
    pending = state.get("pending_specialists") or []
    if not pending:
        return "synthesize_final"
    return SPECIALIST_ROUTES.get(pending[0]["specialist"], "synthesize_final")


async def specialist_openclaw_node(state: GraphState) -> dict:
    """No de especialista: consome o primeiro item de `pending_specialists`
    e delega ao Especialista (OpenClaw) via API. Grava o resultado (ou erro)
    no `internal_scratchpad` para o `supervisor`/`synthesize_final` lerem
    depois, e devolve a fila sem o item ja processado."""
    pending = list(state.get("pending_specialists") or [])
    if not pending:
        return {"current_specialist": None}

    job = pending.pop(0)
    client = OpenClawClient()
    request = SpecialistCallRequest(task_description=job["instructions"])
    started_at = time.monotonic()
    result = await client.call(request)
    elapsed_ms = round((time.monotonic() - started_at) * 1000)
    _logger.info("specialist_openclaw_node: concluido em %dms, sucesso=%s", elapsed_ms, result.success)

    update: dict = {
        "pending_specialists": pending,
        "current_specialist": None,
    }
    if result.success:
        update["internal_scratchpad"] = (state.get("internal_scratchpad") or []) + [f"[openclaw] {result.output}"]
    else:
        update["internal_scratchpad"] = (state.get("internal_scratchpad") or []) + [f"[openclaw] ERRO: {result.error}"]
        update["last_error"] = result.error or "falha desconhecida no especialista OpenClaw"
    return update


async def specialist_cybersec_node(state: GraphState) -> dict:
    """No de especialista: consome o primeiro item de `pending_specialists`
    e delega ao Especialista de Ciberseguranca via o mesmo canal de execucao
    do OpenClaw (o gateway e quem tem o sandbox real com acesso a tool
    Skill) - o que muda em relacao a `specialist_openclaw_node` e o prompt
    (persona + catalogo de skills + regra de autorizacao), nao o transporte.

    Antes de chamar o especialista, aplica `check_production_infra_block`
    (defesa em profundidade em Python puro, ver cybersec_guard.py): se a
    instrucao referenciar infra de producao propria conhecida, recusa a
    acao sem sequer chamar o LLM/gateway - a regra de autorizacao no prompt
    cobre o resto (alvos de terceiros, ambiguidade), mas os alvos de
    producao mais criticos ficam bloqueados incondicionalmente aqui.
    """
    pending = list(state.get("pending_specialists") or [])
    if not pending:
        return {"current_specialist": None}

    job = pending.pop(0)
    update: dict = {
        "pending_specialists": pending,
        "current_specialist": None,
    }

    task_description = extract_task_description(state["messages"])

    # Defesa em profundidade multi-turn: avalia tanto a mensagem original do
    # usuario quanto as instrucoes repassadas pelo supervisor. O supervisor
    # pode injetar (por prompt injection ou eco involuntario) uma keyword de
    # producao em `job["instructions"]` mesmo que a mensagem original nao a
    # contenha - checar apenas uma das duas cria uma janela de bypass.
    refusal = check_production_infra_block(task_description) or check_production_infra_block(
        job.get("instructions", "")
    )
    if refusal:
        _logger.info("specialist_cybersec_node: bloqueado pelo guard de infra de producao")
        update["internal_scratchpad"] = (state.get("internal_scratchpad") or []) + [f"[cybersec] {refusal}"]
        return update

    hardened_prompt = f"{_CYBERSEC_SYSTEM_PROMPT}\n\nInstrucao da tarefa:\n{job['instructions']}"
    client = OpenClawClient()
    request = SpecialistCallRequest(task_description=hardened_prompt)
    started_at = time.monotonic()
    result = await client.call(request)
    elapsed_ms = round((time.monotonic() - started_at) * 1000)
    _logger.info("specialist_cybersec_node: concluido em %dms, sucesso=%s", elapsed_ms, result.success)

    if result.success:
        update["internal_scratchpad"] = (state.get("internal_scratchpad") or []) + [f"[cybersec] {result.output}"]
    else:
        update["internal_scratchpad"] = (state.get("internal_scratchpad") or []) + [f"[cybersec] ERRO: {result.error}"]
        update["last_error"] = result.error or "falha desconhecida no especialista de ciberseguranca"
    return update


async def _run_n8n_tool(
    client: N8nClient,
    name: str,
    args: dict,
    instructions: str,
    *,
    bypass_confirmation: bool = False,
) -> dict:
    """Executa uma chamada de tool do especialista n8n contra o N8nClient de
    verdade, traduzindo qualquer erro HTTP/rede num dict `{"error": ...}` -
    o loop do especialista devolve isso como ToolMessage pro LLM decidir o
    proximo passo (ex.: tentar de novo, desistir e reportar), em vez de
    deixar a excecao estourar o no inteiro.

    Duas camadas de defesa em Python puro rodam ANTES da execucao:

    1. `check_destructive_n8n_action` (n8n_guard.py): delete/deactivate sao
       recusados se a instrucao nao trouxer o verbo explicito.
    2. Gate de confirmacao (n8n_confirmation.py): create/activate/deactivate/
       delete NAO sao executados sem uma confirmacao do usuario. Em vez de
       executar, devolve `{NEEDS_CONFIRMATION_KEY: <pendencia>}` para o node
       gravar a pendencia e pedir o "sim" num proximo turno.

    `bypass_confirmation=True` e usado APENAS pelo caminho em que o
    `supervisor` ja validou a resposta afirmativa do usuario contra o token
    da pendencia persistida (ver `specialist_n8n_node`).
    """
    if is_write_action(name) and not bypass_confirmation:
        pendencia = build_pending_confirmation(name, args, settings.n8n_confirmation_ttl_sec)
        return {NEEDS_CONFIRMATION_KEY: pendencia}

    # Guard de verbo (n8n_guard.py) continua rodando como camada extra. No
    # caminho `bypass_confirmation` a instrucao passada e o resumo da acao
    # confirmada ("EXCLUIR...", "DESATIVAR...") - sempre traz o verbo, entao
    # nunca bloqueia uma confirmacao legitima; so pegaria um delete/deactivate
    # que chegasse aqui por algum caminho futuro sem passar pelo gate.
    refusal = check_destructive_n8n_action(name, instructions)
    if refusal:
        return {"error": refusal}

    try:
        if name == N8nListWorkflows.__name__:
            return await client.list_workflows(active=args.get("active"), name=args.get("name"))
        if name == N8nGetWorkflow.__name__:
            return await client.get_workflow(args["workflow_id"])
        if name == N8nCreateWorkflow.__name__:
            return await client.create_workflow(args["name"], args.get("nodes") or [], args.get("connections") or {})
        if name == N8nUpdateWorkflow.__name__:
            return await client.update_workflow(
                args["workflow_id"], args["name"], args.get("nodes") or [], args.get("connections") or {}
            )
        if name == N8nDeleteWorkflow.__name__:
            return await client.delete_workflow(args["workflow_id"])
        if name == N8nActivateWorkflow.__name__:
            return await client.activate_workflow(args["workflow_id"])
        if name == N8nDeactivateWorkflow.__name__:
            return await client.deactivate_workflow(args["workflow_id"])
        if name == N8nTriggerWebhook.__name__:
            return await client.trigger_webhook(
                args["path"], method=args.get("method", "POST"), body=args.get("body"), test=args.get("test", False)
            )
        return {"error": f"tool desconhecida: {name}"}
    except httpx.HTTPStatusError as exc:
        return {"error": f"n8n retornou {exc.response.status_code}: {exc.response.text}"}
    except httpx.RequestError as exc:
        return {"error": f"erro de rede ao chamar n8n: {exc}"}


async def specialist_n8n_node(state: GraphState) -> dict:
    """No de especialista: consome o primeiro item de `pending_specialists`
    e executa um loop ReAct manual (LLM com `bind_tools` + execucao real via
    N8nClient) contra a API REST de uma instancia de n8n em producao.

    Diferente do OpenClaw/cybersec (que so encaminham a instrucao a um agent
    externo via HTTP e recebem o resultado pronto), aqui o tool-calling roda
    dentro deste no: nao existe "agent n8n" por tras, so a API REST crua -
    entao o proprio orquestrador precisa decidir/executar cada chamada.

    Loop: pergunta ao LLM, se ele pedir tool(s) executa cada uma de verdade
    e devolve o resultado como ToolMessage, repete; se ele responder sem
    pedir tool, aquele texto e o resumo final. `_N8N_MAX_STEPS` evita loop
    infinito caso o LLM nunca pare de chamar tools.

    Gate de confirmacao (ver n8n_confirmation.py): create/activate/deactivate/
    delete NAO sao executados no loop - `_run_n8n_tool` devolve uma pendencia,
    que este node grava em `n8n_pending_confirmation` e transforma num pedido
    de "sim/nao" ao usuario. Quando o `supervisor` detecta a resposta
    afirmativa num turno seguinte, ele despacha este node com
    `n8n_confirmed_token` setado - ai a acao pendente e executada uma unica
    vez, sem passar pelo LLM.
    """
    pending = list(state.get("pending_specialists") or [])
    if not pending:
        return {"current_specialist": None}

    job = pending.pop(0)
    update: dict = {
        "pending_specialists": pending,
        "current_specialist": None,
    }

    client = N8nClient()

    # --- Caminho de execucao confirmada -------------------------------------
    # O supervisor so seta `n8n_confirmed_token` depois de bater a resposta
    # afirmativa do usuario contra uma pendencia valida. Aqui revalidamos o
    # token contra a pendencia persistida (defesa em profundidade) e
    # executamos exatamente a acao/args gravados - nada de LLM.
    confirmed_token = state.get("n8n_confirmed_token")
    if confirmed_token:
        stored = get_valid_pending_confirmation(state.get("n8n_pending_confirmation"))
        update["n8n_pending_confirmation"] = "clear"
        if not stored or stored.get("token") != confirmed_token:
            _logger.info("specialist_n8n_node: token de confirmacao invalido/expirado, nada executado")
            update["internal_scratchpad"] = (state.get("internal_scratchpad") or []) + [
                (
                    "[n8n] A confirmacao expirou ou nao corresponde a nenhuma acao pendente. "
                    "Nada foi executado - refaca o pedido se ainda quiser."
                )
            ]
            return update

        result = await _run_n8n_tool(
            client, stored["tool_name"], stored["args"], stored.get("summary", ""), bypass_confirmation=True
        )
        ok = "error" not in result
        _logger.info(
            "specialist_n8n_node: acao confirmada '%s' executada, sucesso=%s", stored["action"], ok
        )
        if ok:
            update["internal_scratchpad"] = (state.get("internal_scratchpad") or []) + [
                (
                    f"[n8n] Acao confirmada pelo usuario e executada: {stored['summary']} "
                    f"Resultado do n8n: {json.dumps(result, ensure_ascii=False, default=str)}"
                )
            ]
        else:
            update["internal_scratchpad"] = (state.get("internal_scratchpad") or []) + [
                f"[n8n] ERRO ao executar a acao confirmada ({stored['summary']}): {result['error']}"
            ]
            update["last_error"] = result["error"]
        return update

    # --- Loop ReAct normal (propoe acoes, nunca executa escrita direto) -----
    llm = ChatOpenAI(
        model=settings.router_model,
        temperature=0,
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    ).bind_tools(_N8N_TOOLS)

    conversation: list[BaseMessage] = [
        SystemMessage(content=_N8N_SYSTEM_PROMPT),
        HumanMessage(content=job["instructions"]),
    ]
    actions_log: list[str] = []
    final_text = ""
    error: str | None = None
    proposal: dict | None = None
    started_at = time.monotonic()

    for _ in range(_N8N_MAX_STEPS):
        try:
            response = await llm.ainvoke(conversation)
        except Exception as exc:
            error = f"falha ao invocar o LLM do especialista n8n: {exc}"
            break

        conversation.append(response)

        if not response.tool_calls:
            final_text = response.content if isinstance(response.content, str) else str(response.content)
            break

        for call in response.tool_calls:
            result = await _run_n8n_tool(client, call["name"], call["args"], job["instructions"])
            if isinstance(result, dict) and NEEDS_CONFIRMATION_KEY in result:
                # Acao que muda producao: nao executa. Guarda a primeira
                # proposta do turno, encerra o loop e devolve o pedido de
                # confirmacao. "Primeira" garante que criar nao arrasta um
                # activate no mesmo turno.
                proposal = result[NEEDS_CONFIRMATION_KEY]
                actions_log.append(f"{call['name']}({call['args']}) -> PROPOSTA (aguardando confirmacao)")
                break
            actions_log.append(f"{call['name']}({call['args']}) -> {result}")
            conversation.append(
                ToolMessage(content=json.dumps(result, ensure_ascii=False, default=str), tool_call_id=call["id"])
            )
        if proposal is not None:
            break
    else:
        error = "especialista n8n atingiu o limite de passos de tool-calling sem concluir"

    elapsed_ms = round((time.monotonic() - started_at) * 1000)
    _logger.info(
        "specialist_n8n_node: concluido em %dms, sucesso=%s, %d acao(oes) executada(s)",
        elapsed_ms,
        error is None,
        len(actions_log),
    )

    if error:
        update["internal_scratchpad"] = (state.get("internal_scratchpad") or []) + [f"[n8n] ERRO: {error}. Acoes realizadas: {actions_log}"]
        update["last_error"] = error
        return update

    if proposal is not None:
        update["n8n_pending_confirmation"] = proposal
        update["internal_scratchpad"] = (state.get("internal_scratchpad") or []) + [
            (
                "[n8n] PROPOSTA DE ACAO - NADA FOI EXECUTADO. Para prosseguir eu preciso "
                f"que o usuario confirme explicitamente. A acao seria: {proposal['summary']} "
                "Encerre este turno perguntando ao usuario, de forma direta, se ele confirma "
                "(sim/nao) - NAO redespache o especialista n8n."
            )
        ]
        _logger.info("specialist_n8n_node: acao '%s' proposta, aguardando confirmacao do usuario", proposal["action"])
        return update

    note = final_text or "Especialista n8n concluiu sem resumo textual."
    if actions_log:
        note += "\n\nAcoes executadas:\n" + "\n".join(f"- {a}" for a in actions_log)
    update["internal_scratchpad"] = (state.get("internal_scratchpad") or []) + [f"[n8n] {note}"]
    return update


def route_after_specialist(state: GraphState) -> str:
    """Borda de fila/loop apos um no de especialista: se ainda ha itens
    enfileirados pelo `supervisor` nesta rodada, drena o proximo direto
    (sem rechamar o LLM); fila vazia volta ao `supervisor`, que decide se
    aciona mais especialistas ou encerra a rodada."""
    pending = state.get("pending_specialists") or []
    if pending:
        return SPECIALIST_ROUTES.get(pending[0]["specialist"], "supervisor")
    return "supervisor"


async def synthesize_final_node(state: GraphState) -> dict:
    """No final do Enxame: le o `internal_scratchpad` acumulado pelos
    especialistas (se houver) e compoe a resposta ao usuario. Aborto de
    seguranca por limite de iteracoes vira uma mensagem fixa, sem chamar o
    LLM - o proprio limite estourado e sinal de que algo esta em loop."""
    if state.get("iteration_count", 0) > settings.max_supervisor_iterations:
        _logger.warning("synthesize_final_node: abortando por limite de iteracoes do supervisor")
        return {"final_result": _ABORT_MESSAGE}

    scratchpad_text = _format_scratchpad(state.get("internal_scratchpad") or [])
    task_description = extract_task_description(state["messages"])

    prompt = f"Instrucao original do usuario:\n{task_description}"
    if scratchpad_text:
        prompt += f"\n\nNotas internas dos especialistas que trabalharam nesta tarefa:\n{scratchpad_text}"
    last_error = state.get("last_error")
    if last_error:
        prompt += f"\n\nUm especialista reportou um erro: {last_error}"

    llm = ChatOpenAI(
        model=settings.general_model,
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )
    response = await llm.ainvoke([SystemMessage(content=_SYNTHESIZE_SYSTEM_PROMPT), HumanMessage(content=prompt)])
    text = response.content if isinstance(response.content, str) else str(response.content)
    _logger.info("synthesize_final_node: concluido, iteration_count=%d", state.get("iteration_count", 0))
    return {"messages": [response], "final_result": text}
