// Detects the operator's reply to a pending ask_max escalation and routes it
// back to the original conversation. Runs in before_agent_run (same hook
// extensions/response-audit uses for capture) so it can suppress the normal
// LLM turn for the operator's answer — confirmed live-capable via
// src/agents/embedded-agent-runner/run/attempt.ts (a before_agent_run
// "block" decision sets skipPromptSubmission=true, so no LLM call happens).
//
// Identifies the operator by comparing the inbound channel/chat directly
// against this plugin's own configured target (config.ts), NOT via core's
// event.senderIsOwner. Confirmed live on 2026-07-18 that senderIsOwner does
// not reliably resolve true for the configured operator on a plain
// conversational WhatsApp Cloud reply, even with commands.ownerAllowFrom set
// (see docs/SESSAO_2026-07-18.md) — root cause not fully isolated (likely a
// phone-number normalization mismatch between the generic owner-matching
// path and the channel's own allowFrom normalization), and not worth
// depending on: this plugin already has an unambiguous, self-contained
// source of truth for "who is the operator" (the same target it sends the
// question to), so it uses that instead of a second, less predictable
// core mechanism.
//
// What was NOT verified during design: the exact rendering of core's
// built-in block message. It always wraps the decision's text in
// "Your message could not be sent: ..." (src/plugins/hook-decision-types.ts,
// resolveBlockMessage) — wrong tone for a confirmation, and it was unclear
// whether that text is even delivered as a live outbound message or just
// recorded in the session transcript. So this hook does not depend on it:
// it sends its own ack independently, and the block decision exists only to
// stop the LLM from trying to process the operator's answer as a fresh
// request.
import type { OpenClawPluginApi } from "../api.js";
import { resolveAskMaxTarget } from "./config.js";
import { sendAskMaxMessage } from "./proactive-send.js";
import { consumePendingAskMax, type PendingAskMaxTarget } from "./store.js";

function normalizeDigits(value: string): string {
  return value.replace(/\D/g, "");
}

// WhatsApp numbers for the same physical line can arrive formatted with or
// without an extra mobile digit (e.g. Brazil's "9", inserted after the area
// code — not at the start, so a prefix/suffix check alone misses it).
// Comparing on digits with a 1-digit insertion allowed anywhere handles it
// without hardcoding any country's numbering rules.
export function phoneLikelyMatches(a: string, b: string): boolean {
  const da = normalizeDigits(a);
  const db = normalizeDigits(b);
  if (!da || !db) {
    return false;
  }
  if (da === db) {
    return true;
  }
  const shorter = da.length <= db.length ? da : db;
  const longer = da.length <= db.length ? db : da;
  if (longer.length - shorter.length !== 1) {
    return false;
  }
  for (let i = 0; i < longer.length; i++) {
    if (longer.slice(0, i) + longer.slice(i + 1) === shorter) {
      return true;
    }
  }
  return false;
}

function isFromOperator(params: { ctx: { channel?: string; chatId?: string }; target: PendingAskMaxTarget }): boolean {
  const { ctx, target } = params;
  if (!ctx.channel || !ctx.chatId) {
    return false;
  }
  return ctx.channel === target.channel && phoneLikelyMatches(ctx.chatId, target.to);
}

async function deliverAnswerAndAck(params: {
  api: OpenClawPluginApi;
  question: string;
  answerText: string;
  origin: PendingAskMaxTarget;
  operatorTarget: PendingAskMaxTarget;
}): Promise<void> {
  const { api, question, answerText, origin, operatorTarget } = params;

  const answerResult = await sendAskMaxMessage({
    api,
    target: origin,
    text: `O Max respondeu sua dúvida:\n\n"${question}"\n\nResposta: ${answerText}`,
  });
  if (!answerResult.ok) {
    api.logger.warn(
      `ask_max: failed to deliver operator answer to the original chat: ${String(answerResult.error)}`,
    );
  }

  const ackText = answerResult.ok
    ? "✅ Encaminhei sua resposta pro usuário."
    : "⚠️ Recebi sua resposta, mas não consegui encaminhar pro usuário original agora. Confere os logs.";
  const ackResult = await sendAskMaxMessage({ api, target: operatorTarget, text: ackText });
  if (!ackResult.ok) {
    api.logger.warn(`ask_max: failed to send operator ack: ${String(ackResult.error)}`);
  }
}

export function registerAskMaxResolveHook(api: OpenClawPluginApi): void {
  api.on("before_agent_run", async (event, ctx) => {
    const target = resolveAskMaxTarget(api);
    if (!target || !isFromOperator({ ctx, target })) {
      return;
    }
    const pending = await consumePendingAskMax(api);
    if (!pending) {
      return;
    }

    // Fire-and-forget: these are network sends. Do not make the operator's
    // own turn wait on them — same fire-and-forget idiom
    // extensions/response-audit/src/plugin.ts uses for reply_payload_sending.
    void deliverAnswerAndAck({
      api,
      question: pending.question,
      answerText: event.prompt,
      origin: pending.origin,
      operatorTarget: target,
    });

    return {
      outcome: "block" as const,
      reason: "ask-max: message consumed as the pending escalation answer",
    };
  });
}
