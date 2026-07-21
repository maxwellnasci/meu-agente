import { withTempWorkspace } from "openclaw/plugin-sdk/temp-path";
// The github_repo_report tool. Runs entirely in the gateway/host process —
// never enters the Docker sandbox, never has a free-text command field the
// model could escalate into arbitrary exec (see schema.ts).
import type { AnyAgentTool, PluginLogger } from "../api.js";
import { resolvePreferredOpenClawTmpDir, type TempWorkspace } from "../api.js";
import { createTimingMarker } from "./debug-timing.js";
import { fetchGithubRepoTarball } from "./github-fetch.js";
import { isGithubRepoEnabled, resolveGithubRepoEntry } from "./repo-registry.js";
import { buildRepoReport } from "./report-builder.js";
import { GithubRepoReportSchema } from "./schema.js";

export function createGithubRepoReportTool(logger?: PluginLogger): AnyAgentTool {
  return {
    label: "GitHub Repo Report",
    name: "github_repo_report",
    description:
      "Fetch one allow-listed GitHub repository and return a structured report (file tree, sizes, README, manifest). Read-only; runs outside the sandbox.",
    parameters: GithubRepoReportSchema,
    execute: async (_toolCallId, params) => {
      const args = params as { repo: string; ref?: string };
      const entry = resolveGithubRepoEntry(args.repo);
      if (!entry) {
        throw new Error(`Unknown repo: ${args.repo}`);
      }
      // Defense in depth: the trusted policy in policy.ts already gates
      // disabled repos before execute() ever runs, but this tool must not
      // trust that alone — fail closed here too.
      if (!isGithubRepoEnabled(args.repo)) {
        throw new Error(
          `Repo "${args.repo}" is not enabled yet. Edit src/repo-registry.ts to enable it.`,
        );
      }

      const mark = createTimingMarker(logger, "tool");
      mark("workspace:create:start");
      const report = await withTempWorkspace(
        { rootDir: resolvePreferredOpenClawTmpDir(), prefix: "github-repo-report-" },
        async (workspace: TempWorkspace) => {
          mark("workspace:create:done");
          const fetched = await fetchGithubRepoTarball(entry, args.ref, workspace, logger);
          // Bug 4 circuit-breaker isolation (docs/SESSAO_2026-07-15.md): when
          // set to "write" or "extract", returns right after the fetch stage,
          // before buildRepoReport ever runs. Debug-only, gated behind an env
          // var never set in production. Remove with debug-timing.ts.
          const stopAfter = process.env.GITHUB_REPORT_DEBUG_STOP_AFTER;
          if (stopAfter === "write" || stopAfter === "extract") {
            mark("run-callback:done");
            return `[debug] stopped after fetch stage "${stopAfter}" (rootDir=${fetched.rootDir})`;
          }
          const result = await buildRepoReport({
            rootDir: fetched.rootDir,
            repoLabel: entry.label,
            ref: fetched.ref,
            logger,
          });
          mark("run-callback:done");
          return result;
        },
      );
      mark("workspace:cleanup:done");

      return {
        content: [{ type: "text", text: report }],
        details: { repo: entry.slug, ref: args.ref ?? entry.defaultRef },
      };
    },
  };
}
