// Bug 4 instrumentation: a hung github_repo_report turn showed zero CPU and
// zero network for 3+ minutes with no recovery short of a container restart.
// These marks exist to pin down, on the next local reproduction, exactly
// which await never returns. Remove once Bug 4's root cause is found and fixed.
import type { PluginLogger } from "../api.js";

export function createTimingMarker(logger: PluginLogger | undefined, scope: string) {
  const startedAt = performance.now();
  return (label: string) => {
    logger?.debug?.(
      `[github-repo-report] ${scope} ${label} +${Math.round(performance.now() - startedAt)}ms`,
    );
  };
}
