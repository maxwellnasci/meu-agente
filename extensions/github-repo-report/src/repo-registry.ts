// Repo Registry is the single source of truth for which GitHub repos this
// tool may fetch. Flip `enabled` here (and only here) to allow a new repo
// once its behavior has been validated with the first enabled repo.
export type GithubRepoSlug = "meu-agente" | "arbo" | "Mox---Sistemas";

export type GithubRepoEntry = {
  slug: GithubRepoSlug;
  owner: string;
  label: string;
  defaultRef: string;
  enabled: boolean;
};

export const GITHUB_REPO_OWNER = "maxwellnasci";

// Slugs verified live against the GitHub API on 2026-07-15 (see
// docs/SESSAO_2026-07-15.md). "Mox---Sistemas" is the real repo name — not
// "mox" or "Mox" — GitHub's API is case-insensitive for lookups but this is
// the canonical spelling.
export const GITHUB_REPO_REGISTRY: Readonly<Record<GithubRepoSlug, GithubRepoEntry>> = {
  "meu-agente": {
    slug: "meu-agente",
    owner: GITHUB_REPO_OWNER,
    label: "meu-agente",
    defaultRef: "master",
    enabled: false,
  },
  arbo: {
    slug: "arbo",
    owner: GITHUB_REPO_OWNER,
    label: "arbo",
    defaultRef: "master",
    enabled: false,
  },
  "Mox---Sistemas": {
    slug: "Mox---Sistemas",
    owner: GITHUB_REPO_OWNER,
    label: "mox",
    defaultRef: "main",
    enabled: true,
  },
};

export const GITHUB_REPO_SLUGS = Object.keys(GITHUB_REPO_REGISTRY) as GithubRepoSlug[];

export function resolveGithubRepoEntry(slug: string): GithubRepoEntry | undefined {
  return GITHUB_REPO_REGISTRY[slug as GithubRepoSlug];
}

export function isGithubRepoEnabled(slug: string): boolean {
  return resolveGithubRepoEntry(slug)?.enabled === true;
}
