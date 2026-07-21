// Composes the github_repo_report tool, its trusted approval policy, and its
// async audit hook. Mirrors extensions/diffs/src/plugin.ts's manual
// register(api) pattern — needed here because the defineToolPlugin sugar
// only covers tool registration, not trusted policies or lifecycle hooks.
import type { OpenClawPluginApi } from "../api.js";
import { registerGithubRepoReportAuditHook } from "./audit-log.js";
import { registerGithubRepoReportPolicy } from "./policy.js";
import { createGithubRepoReportTool } from "./tool.js";

export function registerGithubRepoReportPlugin(api: OpenClawPluginApi): void {
  api.registerTool(createGithubRepoReportTool(api.logger));
  registerGithubRepoReportPolicy(api);
  registerGithubRepoReportAuditHook(api);
}
