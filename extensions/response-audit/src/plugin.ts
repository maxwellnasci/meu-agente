// Composes the response-audit capture hooks and the audit trigger.
// Mirrors extensions/github-repo-report/src/plugin.ts's manual
// register(api) pattern for a plugin that only wires hooks (no tool).
//
// The trigger lives in reply_payload_sending (kind: "final"), not agent_end.
// Confirmed live on 2026-07-18 that agent_end fires BEFORE the final reply's
// reply_payload_sending — agent_end observes the model turn finishing, not
// the reply actually being handed to the channel, which is a separate
// downstream step. Consuming the captured turn in agent_end always found an
// empty finalText. reply_payload_sending fires synchronously in the delivery
// path (it's a decision hook, unlike agent_end's fire-and-forget), so the
// audit call is kicked off detached (not awaited, not returned) so it never
// delays the WhatsApp send — same fire-and-forget idiom the host itself uses
// in agent-end-side-effects.ts (`void runCoreAgentEndSideEffects(...)`).
import type { OpenClawPluginApi } from "../api.js";
import { runResponseAudit } from "./audit-runner.js";
import { persistAuditResult } from "./audit-store.js";
import { evaluateAuditHeuristic } from "./heuristic-filter.js";
import {
  rememberTurnFinalText,
  rememberTurnPrompt,
  rememberTurnToolExecuted,
  takeCapturedTurn,
} from "./turn-capture.js";

async function auditFinalReply(api: OpenClawPluginApi, runId: string): Promise<void> {
  const turn = takeCapturedTurn(runId);
  if (!turn || !turn.finalText) {
    return;
  }

  const decision = evaluateAuditHeuristic(turn);
  if (!decision.shouldAudit) {
    return;
  }

  try {
    const verdict = await runResponseAudit(api, turn);
    await persistAuditResult(api, {
      runId: turn.runId,
      sessionKey: turn.sessionKey,
      agentId: turn.agentId,
      channel: turn.channel,
      chatId: turn.chatId,
      prompt: turn.prompt,
      finalText: turn.finalText,
      toolsExecuted: turn.toolsExecuted,
      triggerReasons: decision.reasons,
      flagged: verdict.flagged,
      category: verdict.category,
      reason: verdict.reason,
      auditedAt: Date.now(),
    });
  } catch (error) {
    // Audit is observational; failures must not affect the completed run.
    api.logger.warn(`response-audit failed for run ${runId}: ${String(error)}`);
  }
}

export function registerResponseAuditPlugin(api: OpenClawPluginApi): void {
  api.on("before_agent_run", (event, ctx) => {
    if (!ctx.runId) {
      return;
    }
    rememberTurnPrompt({
      runId: ctx.runId,
      prompt: event.prompt,
      sessionKey: ctx.sessionKey,
      agentId: ctx.agentId,
      channel: ctx.channel,
      chatId: ctx.chatId,
      senderId: ctx.senderId,
    });
  });

  api.on("after_tool_call", (event, ctx) => {
    if (!ctx.runId || event.error) {
      return;
    }
    rememberTurnToolExecuted({ runId: ctx.runId, toolName: event.toolName });
  });

  api.on("reply_payload_sending", (event) => {
    if (!event.runId || event.kind !== "final") {
      return;
    }
    const text = event.payload.text;
    if (
      !text ||
      event.payload.isStatusNotice ||
      event.payload.isCompactionNotice ||
      event.payload.isFallbackNotice ||
      event.payload.isReasoning
    ) {
      return;
    }
    rememberTurnFinalText({ runId: event.runId, text });
    // Fire-and-forget: do not await/return this from the hook handler, or the
    // host will wait for it before delivering the WhatsApp message.
    void auditFinalReply(api, event.runId);
  });
}
