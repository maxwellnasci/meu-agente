// Composes the github_repo_report tool, its trusted approval policy, and its
// async audit hook. Mirrors extensions/diffs/src/plugin.ts's manual
// register(api) pattern — needed here because the defineToolPlugin sugar
// only covers tool registration, not trusted policies or lifecycle hooks.
// Config resolution follows extensions/webhooks/index.ts: parse
// api.pluginConfig once here, and skip registration entirely when no repos
// are configured. That is deliberate, not just a null-op guard: an empty
// slug list would make createGithubRepoReportSchema()'s stringEnum([])
// degrade to an unconstrained string field (see schema.ts), which is the
// opposite of "safe by default" for this repo allowlist.
import type { OpenClawPluginApi } from "../api.js";
import { registerGithubRepoReportAuditHook } from "./audit-log.js";
import { resolveGithubRepoReportPluginConfig } from "./config.js";
import { registerGithubRepoReportPolicy } from "./policy.js";
import { buildGithubRepoRegistry } from "./repo-registry.js";
import { createGithubRepoReportTool } from "./tool.js";

export function registerGithubRepoReportPlugin(api: OpenClawPluginApi): void {
  const entries = resolveGithubRepoReportPluginConfig({ pluginConfig: api.pluginConfig });
  if (entries.length === 0) {
    api.logger.info?.("[github-repo-report] no repos configured; tool not registered");
    return;
  }

  const registry = buildGithubRepoRegistry(entries);
  api.registerTool(createGithubRepoReportTool(registry, api.logger));
  registerGithubRepoReportPolicy(api, registry);
  registerGithubRepoReportAuditHook(api);
}
