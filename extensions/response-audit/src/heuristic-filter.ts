// Cheap pre-filter that decides whether a turn is worth spending a second
// LLM call on. No model call here — regex + plain data checks only.
//
// Any one of the three signals below is enough to trigger the audit:
//  1. The final reply text itself reads like a declared action (first-person
//     past-tense verbs such as "já", "fiz", "alertei") — this is the exact
//     shape of Problem 3 from docs/TREINAMENTO_AGENTS_MD.md ("Já alertei o
//     Coach sobre o que você relatou").
//  2. A tool genuinely ran this turn (ground truth from after_tool_call) —
//     lets the audit cross-check claimed vs. actual actions.
//  3. The reply is long enough (>= AUDIT_MIN_LENGTH chars) that invented
//     policy details or fabricated quotes (Problems 1 and 2) have room to
//     show up; short replies ("oi, tudo bem?") carry negligible risk.
import type { CapturedTurn } from "./turn-capture.js";

export const AUDIT_MIN_LENGTH = 300;

// First-person, past-tense/completed-action verbs in PT-BR that read as a
// claim of an action already taken. Word-boundary, accent-insensitive-ish,
// case-insensitive.
const DECLARED_ACTION_PATTERN =
  /\b(j[áa]\s+\w+|fiz|feito|alertei|avisei|marquei|cancelei|agendei|resolvi|enviei|confirmei|registrei|notifiquei|reportei|encaminhei|informei|atualizei|removi|adicionei)\b/iu;

export type AuditTriggerReason = "declared_action_text" | "tool_executed" | "long_response";

export type HeuristicDecision = {
  shouldAudit: boolean;
  reasons: AuditTriggerReason[];
};

export function evaluateAuditHeuristic(
  turn: Pick<CapturedTurn, "finalText" | "toolsExecuted">,
): HeuristicDecision {
  const reasons: AuditTriggerReason[] = [];

  if (DECLARED_ACTION_PATTERN.test(turn.finalText)) {
    reasons.push("declared_action_text");
  }
  if (turn.toolsExecuted.length > 0) {
    reasons.push("tool_executed");
  }
  if (turn.finalText.length >= AUDIT_MIN_LENGTH) {
    reasons.push("long_response");
  }

  return { shouldAudit: reasons.length > 0, reasons };
}
