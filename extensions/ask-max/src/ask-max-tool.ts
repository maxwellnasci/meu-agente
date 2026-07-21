// The ask_max tool: lets the model escalate a real doubt to the operator's
// WhatsApp instead of guessing or claiming it doesn't know. Fires the
// question proactively and never blocks — a separate inbound turn (see
// resolve-hook.ts) picks up the answer once the operator replies.
//
// Optional tool (see openclaw.plugin.json toolMetadata) — needs an explicit
// `tools.alsoAllow: ["ask_max"]` entry before the model can ever see it.
// Same lesson as github-repo-report's tool-exposure gap
// (docs/SESSAO_2026-07-17.md): "N plugins loaded" in the gateway log only
// means the plugin loaded, not that its tool reached the model.
import { Type } from "typebox";
import type { AnyAgentTool, OpenClawPluginApi, OpenClawPluginToolContext } from "../api.js";
import { resolveAskMaxTarget } from "./config.js";
import { sendAskMaxMessage } from "./proactive-send.js";
import { consumePendingAskMax, tryCreatePendingAskMax, type PendingAskMaxTarget } from "./store.js";

const AskMaxSchema = Type.Object(
  {
    question: Type.String({
      description:
        "The real, specific doubt you have right now — something you genuinely don't know and cannot find out any other way. Not a rhetorical or already-answered question.",
    }),
    context: Type.Optional(
      Type.String({
        description:
          "Short summary of who is asking and why, so the operator has enough context to answer without re-reading the whole conversation.",
      }),
    ),
  },
  { additionalProperties: false },
);

function buildEscalationText(params: { question: string; context?: string }): string {
  const lines = ["🙋 O Amigão tem uma dúvida:", "", params.question];
  if (params.context) {
    lines.push("", `Contexto: ${params.context}`);
  }
  lines.push("", "Responde aqui no WhatsApp — a próxima mensagem sua é tratada como a resposta.");
  return lines.join("\n");
}

function resolveOrigin(ctx: OpenClawPluginToolContext): PendingAskMaxTarget | undefined {
  const channel = ctx.deliveryContext?.channel;
  const to = ctx.deliveryContext?.to;
  if (!channel || !to) {
    return undefined;
  }
  const accountId = ctx.deliveryContext?.accountId;
  const threadId = ctx.deliveryContext?.threadId;
  return {
    channel,
    to,
    ...(accountId ? { accountId } : {}),
    ...(threadId !== undefined ? { threadId } : {}),
  };
}

export function createAskMaxTool(
  api: OpenClawPluginApi,
): (ctx: OpenClawPluginToolContext) => AnyAgentTool {
  return (ctx: OpenClawPluginToolContext) => {
    const origin = resolveOrigin(ctx);

    return {
      label: "Ask Max",
      name: "ask_max",
      description:
        "Call this tool DIRECTLY, right now, whenever you genuinely don't know something that only the human operator can confirm (e.g. a policy, a decision, data you have no way to look up). This is expected default behavior, not an action that needs the end user's permission first — do not ask the user 'do you want me to check?' or similar; just call the tool, then tell the user you're checking and will follow up. Only one question can be pending at a time — if one is already pending, this fails and you must tell the user you are still waiting on a previous check, not ask again. Never claim you already asked the operator before this tool actually succeeds.",
      parameters: AskMaxSchema,
      execute: async (_toolCallId, params) => {
        const args = params as { question: string; context?: string };

        if (!origin) {
          throw new Error("ask_max is unavailable outside a channel conversation.");
        }
        const target = resolveAskMaxTarget(api);
        if (!target) {
          throw new Error("ask_max is not configured yet (missing operator target).");
        }

        const created = await tryCreatePendingAskMax(api, {
          question: args.question,
          context: args.context,
          askedAt: Date.now(),
          origin,
        });
        if (!created) {
          return {
            content: [
              {
                type: "text" as const,
                text: "There is already a question pending with the operator. Wait for that one to be answered before asking another.",
              },
            ],
            details: { sent: false, reason: "already_pending" },
          };
        }

        const result = await sendAskMaxMessage({
          api,
          target,
          text: buildEscalationText(args),
        });
        if (!result.ok) {
          // The pending record must not survive a failed send — otherwise it
          // would permanently block every future ask_max call with no way
          // to clear it (the operator never received anything to reply to).
          await consumePendingAskMax(api);
          if (result.reason === "outside_24h_window") {
            api.logger.warn(
              "ask_max: proactive send blocked by WhatsApp's 24h messaging window; question not delivered",
            );
            return {
              content: [
                {
                  type: "text" as const,
                  text: "Could not reach the operator right now (outside the messaging window). Tell the user you'll check and follow up — do not claim you already asked.",
                },
              ],
              details: { sent: false, reason: "outside_24h_window" },
            };
          }
          api.logger.warn(`ask_max: proactive send failed: ${String(result.error)}`);
          return {
            content: [
              {
                type: "text" as const,
                text: "Could not reach the operator right now. Tell the user you'll check and follow up — do not claim you already asked.",
              },
            ],
            details: { sent: false, reason: "send_failed" },
          };
        }

        return {
          content: [
            {
              type: "text" as const,
              text: "Question sent to the operator. Tell the user you're checking and will follow up once you hear back — do not answer on the operator's behalf yet.",
            },
          ],
          details: { sent: true },
        };
      },
    };
  };
}
