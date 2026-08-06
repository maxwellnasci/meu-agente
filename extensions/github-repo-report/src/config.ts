// Resolves the plugin's own config block (owner + repos) into a flat list of
// repo entries. Mirrors extensions/webhooks/src/config.ts: a stricter zod
// pass on top of the JSON Schema already validated by the plugin loader
// (openclaw.plugin.json's configSchema, which applies its own defaults).
import { z } from "zod";
import type { GithubRepoEntry } from "./repo-registry.js";

const repoEntryConfigSchema = z
  .object({
    slug: z.string().trim().min(1),
    owner: z.string().trim().min(1).optional(),
    label: z.string().trim().min(1).optional(),
    defaultRef: z.string().trim().min(1).optional().default("main"),
    enabled: z.boolean().optional().default(true),
  })
  .strict();

const githubRepoReportPluginConfigSchema = z
  .object({
    owner: z.string().trim().min(1).optional(),
    repos: z.array(repoEntryConfigSchema).optional().default([]),
  })
  .strict();

export function resolveGithubRepoReportPluginConfig(params: {
  pluginConfig: unknown;
}): GithubRepoEntry[] {
  const parsed = githubRepoReportPluginConfigSchema.parse(params.pluginConfig ?? {});
  const seenSlugs = new Set<string>();
  const resolved: GithubRepoEntry[] = [];

  for (const repo of parsed.repos) {
    if (seenSlugs.has(repo.slug)) {
      throw new Error(`github-repo-report.repos: duplicate slug "${repo.slug}".`);
    }
    seenSlugs.add(repo.slug);

    const owner = repo.owner ?? parsed.owner;
    if (!owner) {
      throw new Error(
        `github-repo-report.repos.${repo.slug}: missing owner (set repos[].owner or top-level owner).`,
      );
    }

    resolved.push({
      slug: repo.slug,
      owner,
      label: repo.label ?? repo.slug,
      defaultRef: repo.defaultRef,
      enabled: repo.enabled,
    });
  }

  return resolved;
}
