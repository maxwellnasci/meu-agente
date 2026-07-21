import { beforeEach, describe, expect, it } from "vitest";
import { clearPendingGithubRepoReportAuditForTest } from "./audit-log.js";
import { registerGithubRepoReportPolicy } from "./policy.js";

type CapturedEvaluate = (
  event: { toolName: string; params: Record<string, unknown>; toolCallId?: string },
  ctx: { runId?: string; sessionKey?: string; agentId?: string },
) => unknown;

function registerAndCapture(): CapturedEvaluate {
  let captured: CapturedEvaluate | undefined;
  const api = {
    registerTrustedToolPolicy: (policy: { evaluate: CapturedEvaluate }) => {
      captured = policy.evaluate;
    },
  } as unknown as import("../api.js").OpenClawPluginApi;
  registerGithubRepoReportPolicy(api);
  if (!captured) {
    throw new Error("policy.evaluate was not captured");
  }
  return captured;
}

describe("github-repo-report policy", () => {
  beforeEach(() => {
    clearPendingGithubRepoReportAuditForTest();
  });

  it("ignores calls to other tools", () => {
    const evaluate = registerAndCapture();
    const result = evaluate({ toolName: "exec", params: {} }, {});
    expect(result).toBeUndefined();
  });

  it("auto-allows the enabled repo (Mox---Sistemas) silently", () => {
    const evaluate = registerAndCapture();
    const result = evaluate(
      { toolName: "github_repo_report", params: { repo: "Mox---Sistemas" } },
      { runId: "run-1" },
    );
    expect(result).toBeUndefined();
  });

  it("requires approval for repos present in the enum but not yet enabled", () => {
    const evaluate = registerAndCapture();
    const result = evaluate(
      { toolName: "github_repo_report", params: { repo: "arbo" } },
      { runId: "run-2" },
    ) as { requireApproval?: { allowedDecisions?: string[] } };
    expect(result?.requireApproval).toBeDefined();
    expect(result?.requireApproval?.allowedDecisions).toEqual(["allow-once", "deny"]);
  });

  it("blocks an unrecognized repo immediately instead of requiring approval", () => {
    const evaluate = registerAndCapture();
    const result = evaluate(
      { toolName: "github_repo_report", params: { repo: "not-a-real-repo" } },
      {},
    ) as { block?: boolean; blockReason?: string; requireApproval?: unknown };
    expect(result?.block).toBe(true);
    expect(result?.blockReason).toContain("not-a-real-repo");
    expect(result?.requireApproval).toBeUndefined();
  });

  it("blocks a missing repo parameter immediately", () => {
    const evaluate = registerAndCapture();
    const result = evaluate({ toolName: "github_repo_report", params: {} }, {}) as {
      block?: boolean;
      blockReason?: string;
    };
    expect(result?.block).toBe(true);
    expect(result?.blockReason).toBeDefined();
  });
});
