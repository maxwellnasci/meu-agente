import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearPendingGithubRepoReportAuditForTest,
  peekPendingGithubRepoReportAuditCountForTest,
  registerGithubRepoReportAuditHook,
  rememberPendingGithubRepoReportAudit,
} from "./audit-log.js";

type AgentEndHandler = (
  event: { success: boolean; error?: string },
  ctx: { runId?: string },
) => Promise<void> | void;

function registerAndCaptureAgentEnd(registerStore: () => { register: (...args: unknown[]) => Promise<void> }) {
  let captured: AgentEndHandler | undefined;
  const api = {
    on: (hookName: string, handler: AgentEndHandler) => {
      if (hookName === "agent_end") {
        captured = handler;
      }
    },
    runtime: {
      state: {
        openKeyedStore: () => registerStore(),
      },
    },
  } as unknown as import("../api.js").OpenClawPluginApi;
  registerGithubRepoReportAuditHook(api);
  if (!captured) {
    throw new Error("agent_end handler was not captured");
  }
  return captured;
}

describe("github-repo-report audit log", () => {
  beforeEach(() => {
    clearPendingGithubRepoReportAuditForTest();
  });

  it("flushes pending records matching the run into the KV store on agent_end", async () => {
    rememberPendingGithubRepoReportAudit({
      runId: "run-42",
      toolCallId: "call-1",
      repo: "Mox---Sistemas",
      decision: "auto-allow",
      requestedAt: Date.now(),
    });
    expect(peekPendingGithubRepoReportAuditCountForTest()).toBe(1);

    const registerSpy = vi.fn(async () => {});
    const onAgentEnd = registerAndCaptureAgentEnd(() => ({ register: registerSpy }));

    await onAgentEnd({ success: true }, { runId: "run-42" });

    expect(registerSpy).toHaveBeenCalledTimes(1);
    const [, storedValue] = registerSpy.mock.calls[0] as [string, Record<string, unknown>];
    expect(storedValue.repo).toBe("Mox---Sistemas");
    expect(storedValue.runSuccess).toBe(true);
    expect(peekPendingGithubRepoReportAuditCountForTest()).toBe(0);
  });

  it("does not flush records from a different run", async () => {
    rememberPendingGithubRepoReportAudit({
      runId: "run-a",
      toolCallId: "call-a",
      repo: "arbo",
      decision: "require-approval",
      requestedAt: Date.now(),
    });

    const registerSpy = vi.fn(async () => {});
    const onAgentEnd = registerAndCaptureAgentEnd(() => ({ register: registerSpy }));

    await onAgentEnd({ success: false, error: "unrelated run" }, { runId: "run-b" });

    expect(registerSpy).not.toHaveBeenCalled();
    expect(peekPendingGithubRepoReportAuditCountForTest()).toBe(1);
  });

  it("is a no-op when there are no pending records", async () => {
    const registerSpy = vi.fn(async () => {});
    const onAgentEnd = registerAndCaptureAgentEnd(() => ({ register: registerSpy }));

    await onAgentEnd({ success: true }, { runId: "run-x" });

    expect(registerSpy).not.toHaveBeenCalled();
  });

  // Reproduces the real failure from the 2026-07-15 "analisa o mox" test:
  // policy.ts always sets `ref: <string> | undefined` (never omits the key),
  // which broke the KV store's JSON-serializability check with
  // "plugin state value at value.ref must be JSON-serializable" — confirmed
  // live, 0 rows in state/openclaw.sqlite. This test fails again if
  // stripUndefinedValues (or its call site) regresses.
  it("never passes an explicit undefined field to the KV store (the real ref-undefined bug)", async () => {
    rememberPendingGithubRepoReportAudit({
      runId: "run-99",
      toolCallId: "call-99",
      repo: "Mox---Sistemas",
      ref: undefined, // exactly what policy.ts sends when no ref param was given
      decision: "auto-allow",
      sessionKey: undefined,
      agentId: undefined,
      requestedAt: Date.now(),
    });

    const registerSpy = vi.fn(async () => {});
    const onAgentEnd = registerAndCaptureAgentEnd(() => ({ register: registerSpy }));

    // event.error is also undefined on a successful run — same class of bug.
    await onAgentEnd({ success: true, error: undefined }, { runId: "run-99" });

    expect(registerSpy).toHaveBeenCalledTimes(1);
    const [, storedValue] = registerSpy.mock.calls[0] as [string, Record<string, unknown>];

    for (const [key, value] of Object.entries(storedValue)) {
      expect(value, `key "${key}" must not be undefined`).not.toBeUndefined();
    }
    expect(Object.prototype.hasOwnProperty.call(storedValue, "ref")).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(storedValue, "sessionKey")).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(storedValue, "agentId")).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(storedValue, "runError")).toBe(false);
    expect(storedValue.repo).toBe("Mox---Sistemas");
    expect(storedValue.runSuccess).toBe(true);
  });
});
