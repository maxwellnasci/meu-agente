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
  // Declared-action wording with zero tool calls this turn — the exact shape
  // of a false_action claim. This is a PRIORITY signal for the LLM judge's
  // context, never a verdict on its own: DECLARED_ACTION_PATTERN is a plain
  // regex over completed-action verbs and cannot tell a genuine claim apart
  // from a negation ("não enviei"), a quotation, or a non-literal/idiomatic
  // use of the same verb. The LLM judge (audit-runner.ts) always makes the
  // final flagged/category call; this field only raises the turn's priority
  // and adds a hint to the audit prompt.
  highSuspicionFalseAction: boolean;
};

export function evaluateAuditHeuristic(
  turn: Pick<CapturedTurn, "finalText" | "toolsExecuted">,
): HeuristicDecision {
  const reasons: AuditTriggerReason[] = [];

  const declaredAction = DECLARED_ACTION_PATTERN.test(turn.finalText);
  if (declaredAction) {
    reasons.push("declared_action_text");
  }
  if (turn.toolsExecuted.length > 0) {
    reasons.push("tool_executed");
  }
  if (turn.finalText.length >= AUDIT_MIN_LENGTH) {
    reasons.push("long_response");
  }

  return {
    shouldAudit: reasons.length > 0,
    reasons,
    highSuspicionFalseAction: declaredAction && turn.toolsExecuted.length === 0,
  };
}
