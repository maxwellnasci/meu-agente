import { describe, expect, it } from "vitest";
import { AUDIT_MIN_LENGTH, evaluateAuditHeuristic } from "./heuristic-filter.js";

describe("evaluateAuditHeuristic", () => {
  it("skips a short, action-free reply with no tool calls", () => {
    const decision = evaluateAuditHeuristic({ finalText: "oi, tudo bem?", toolsExecuted: [] });
    expect(decision.shouldAudit).toBe(false);
    expect(decision.reasons).toEqual([]);
  });

  it("triggers on a declared-action verb (Problem 3 shape: 'Já alertei o Coach')", () => {
    const decision = evaluateAuditHeuristic({
      finalText: "Já alertei o Coach sobre o que você relatou.",
      toolsExecuted: [],
    });
    expect(decision.shouldAudit).toBe(true);
    expect(decision.reasons).toContain("declared_action_text");
  });

  it("triggers when a tool actually ran this turn, regardless of wording", () => {
    const decision = evaluateAuditHeuristic({
      finalText: "beleza, deixa comigo",
      toolsExecuted: ["send_alert"],
    });
    expect(decision.shouldAudit).toBe(true);
    expect(decision.reasons).toEqual(["tool_executed"]);
  });

  it("triggers on length alone once the reply reaches AUDIT_MIN_LENGTH", () => {
    const longNeutralText = "x".repeat(AUDIT_MIN_LENGTH);
    const decision = evaluateAuditHeuristic({ finalText: longNeutralText, toolsExecuted: [] });
    expect(decision.shouldAudit).toBe(true);
    expect(decision.reasons).toEqual(["long_response"]);
  });

  it("does not trigger on length one char below AUDIT_MIN_LENGTH", () => {
    const almostLongText = "x".repeat(AUDIT_MIN_LENGTH - 1);
    const decision = evaluateAuditHeuristic({ finalText: almostLongText, toolsExecuted: [] });
    expect(decision.shouldAudit).toBe(false);
  });

  it("reports every matching reason, not just the first", () => {
    const decision = evaluateAuditHeuristic({
      finalText: `Já marquei o horário pra você. ${"x".repeat(AUDIT_MIN_LENGTH)}`,
      toolsExecuted: ["schedule_appointment"],
    });
    expect(decision.shouldAudit).toBe(true);
    expect(decision.reasons).toEqual(
      expect.arrayContaining(["declared_action_text", "tool_executed", "long_response"]),
    );
    expect(decision.reasons).toHaveLength(3);
  });
});
