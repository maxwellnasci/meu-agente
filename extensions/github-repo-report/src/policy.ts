// Trusted tool policy for github_repo_report — modeled on
// src/skills/workshop/policy.ts:47-70 in core (resolveSkillWorkshopToolApproval):
// match the tool name, inspect the specific argument, auto-allow the
// expected/enabled case silently, and only pause for approval otherwise.
// Registered as `registerTrustedToolPolicy`, following the real example at
// src/plugins/contracts/host-hook-fixture.ts:63-73.
import type { OpenClawPluginApi } from "../api.js";
import { rememberPendingGithubRepoReportAudit } from "./audit-log.js";
import { isGithubRepoEnabled, resolveGithubRepoEntry } from "./repo-registry.js";

const TOOL_NAME = "github_repo_report";

export function registerGithubRepoReportPolicy(api: OpenClawPluginApi): void {
  api.registerTrustedToolPolicy({
    id: "github-repo-report-policy",
    description:
      "Auto-allows github_repo_report for repos enabled in repo-registry.ts; requires manual approval for the rest.",
    evaluate(event, ctx) {
      if (event.toolName !== TOOL_NAME) {
        return undefined;
      }
      const repo = typeof event.params.repo === "string" ? event.params.repo : undefined;
      const entry = repo ? resolveGithubRepoEntry(repo) : undefined;
      // A repo outside the registry enum can never be approved into anything
      // sensible (there's no owner/ref to fetch), so it is rejected outright
      // instead of entering the same require-approval flow as a recognized
      // but disabled repo. Channels without interactive approval delivery
      // (e.g. WhatsApp Cloud has no button/quick-reply mapped to a decision)
      // would otherwise leave the turn silently blocked for the full
      // approval timeout with no way for the user to act on it.
      const decision = entry
        ? isGithubRepoEnabled(entry.slug)
          ? "auto-allow"
          : "require-approval"
        : "block";

      rememberPendingGithubRepoReportAudit({
        runId: ctx.runId,
        toolCallId: event.toolCallId,
        repo: repo ?? "(unknown)",
        ref: typeof event.params.ref === "string" ? event.params.ref : undefined,
        decision,
        sessionKey: ctx.sessionKey,
        agentId: ctx.agentId,
        requestedAt: Date.now(),
      });

      if (decision === "auto-allow") {
        return undefined;
      }

      if (decision === "block") {
        return {
          block: true,
          blockReason: repo
            ? `Unknown repo "${repo}" — not present in repo-registry.ts.`
            : "Missing or invalid repo parameter for github_repo_report.",
        };
      }

      return {
        requireApproval: {
          title: "Fetch non-enabled GitHub repo",
          description: `Repo "${repo}" is not enabled in repo-registry.ts yet. Approve once, or edit the registry to enable it permanently.`,
          severity: "warning",
          allowedDecisions: ["allow-once", "deny"],
        },
      };
    },
  });
}
