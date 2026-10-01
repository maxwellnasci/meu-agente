// The ask_orchestrator tool: delegates a task to the project's LangGraph
// orchestrator (n8n automation specialist, Python/code automation
// specialist) via its synchronous /v1/turn API. The orchestrator's own
// contract (orchestrator/src/orchestrator/schemas/requests.py) always
// returns HTTP 200 with a fallback reply_text on internal failure/timeout -
// this tool still guards its own request with a timeout and handles a
// non-200/network failure explicitly, since the orchestrator being
// unreachable (container down, network issue) is a real failure mode its
// own contract cannot cover.
import { Type } from "typebox";
import type { AnyAgentTool, OpenClawPluginApi, OpenClawPluginToolContext } from "../api.js";
import { resolveOrchestratorTarget } from "./config.js";

const OrchestratorSchema = Type.Object(
  {
    task: Type.String({
      description:
        'The task to delegate, in natural language and with enough context to act on (e.g. "crie um workflow no n8n que...", "escreva um script Python que..."). The orchestrator decides which specialist handles it.',
    }),
  },
  { additionalProperties: false },
);

interface OrchestratorTurnResponse {
  reply_text?: unknown;
}

function resolveSenderId(ctx: OpenClawPluginToolContext): string {
  const to = ctx.deliveryContext?.to;
  return typeof to === "string" && to.trim().length > 0 ? to.trim() : "unknown-sender";
}

export function createAskOrchestratorTool(
  api: OpenClawPluginApi,
): (ctx: OpenClawPluginToolContext) => AnyAgentTool {
  return (ctx: OpenClawPluginToolContext) => {
    const senderId = resolveSenderId(ctx);

    return {
      label: "Ask Orchestrator",
      name: "ask_orchestrator",
      description:
        "Call this when the task needs the n8n automation specialist or the Python/code automation specialist - things outside your own sandbox's reach. Tell the user you're delegating before calling this (it can take up to ~2 minutes). Returns the specialist's final answer as plain text.",
      parameters: OrchestratorSchema,
      execute: async (_toolCallId, params) => {
        const args = params as { task: string };
        const target = resolveOrchestratorTarget(api);
        if (!target) {
          return {
            content: [
              {
                type: "text" as const,
                text: "ask_orchestrator is not configured yet (missing orchestrator URL). Tell the user this needs to be set up first.",
              },
            ],
            details: { ok: false, reason: "not_configured" },
          };
        }

        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), target.timeoutSeconds * 1000);
        try {
          const headers: Record<string, string> = { "Content-Type": "application/json" };
          // So manda o header quando ha token configurado (ORCHESTRATOR_API_TOKEN
          // no ambiente do gateway) - sem token, o orquestrador decide o que
          // fazer (fail-closed por padrao, 401; so libera com opt-in explicito
          // ORCHESTRATOR_ALLOW_INSECURE_DEV_AUTH=true do lado dele).
          if (target.token) {
            headers.Authorization = `Bearer ${target.token}`;
          }
          const res = await fetch(target.url, {
            method: "POST",
            headers,
            body: JSON.stringify({
              session_key: `orchestrator-bridge:${senderId}`,
              text: args.task,
              from: senderId,
            }),
            signal: controller.signal,
          });

          if (!res.ok) {
            const bodyText = await res.text().catch(() => "");
            api.logger.warn(`ask_orchestrator: HTTP ${res.status}: ${bodyText.slice(0, 500)}`);
            return {
              content: [
                {
                  type: "text" as const,
                  text: `O orquestrador respondeu com erro (HTTP ${res.status}). Não consegui completar a tarefa por ele agora.`,
                },
              ],
              details: { ok: false, status: res.status },
            };
          }

          const data = (await res.json()) as OrchestratorTurnResponse;
          const replyText = typeof data.reply_text === "string" ? data.reply_text : undefined;
          if (!replyText) {
            api.logger.warn(
              `ask_orchestrator: unexpected response shape: ${JSON.stringify(data).slice(0, 500)}`,
            );
            return {
              content: [
                {
                  type: "text" as const,
                  text: "O orquestrador respondeu num formato inesperado. Não consegui interpretar o resultado.",
                },
              ],
              details: { ok: false, reason: "unexpected_response" },
            };
          }

          return {
            content: [{ type: "text" as const, text: replyText }],
            details: { ok: true },
          };
        } catch (err) {
          const reason = controller.signal.aborted ? "timeout" : "unreachable";
          api.logger.warn(`ask_orchestrator: request failed (${reason}): ${String(err)}`);
          return {
            content: [
              {
                type: "text" as const,
                text:
                  reason === "timeout"
                    ? "O orquestrador demorou demais pra responder. Avise o usuário que vai tentar de outro jeito ou de novo depois."
                    : "Não consegui alcançar o orquestrador agora. Avise o usuário que vai tentar de outro jeito ou de novo depois.",
              },
            ],
            details: { ok: false, reason },
          };
        } finally {
          clearTimeout(timeout);
        }
      },
    };
  };
}
