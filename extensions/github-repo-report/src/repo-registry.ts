// Generic repo-registry builders. All repo data comes from plugin config
// (see src/config.ts) — this module owns only lookup behavior, no hardcoded
// client data. See docs/PROXIMOS_PASSOS.md, "Roteiro: extrair template
// genérico do Amigão", item 3, for why this moved out of source.
export type GithubRepoEntry = {
  slug: string;
  owner: string;
  label: string;
  defaultRef: string;
  enabled: boolean;
};

export type GithubRepoRegistry = ReadonlyMap<string, GithubRepoEntry>;

export function buildGithubRepoRegistry(entries: readonly GithubRepoEntry[]): GithubRepoRegistry {
  return new Map(entries.map((entry) => [entry.slug, entry]));
}

export function listGithubRepoSlugs(registry: GithubRepoRegistry): string[] {
  return [...registry.keys()];
}

export function resolveGithubRepoEntry(
  registry: GithubRepoRegistry,
  slug: string,
): GithubRepoEntry | undefined {
  return registry.get(slug);
}

export function isGithubRepoEnabled(registry: GithubRepoRegistry, slug: string): boolean {
  return resolveGithubRepoEntry(registry, slug)?.enabled === true;
}
