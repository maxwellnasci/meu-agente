import { describe, expect, it } from "vitest";
import {
  buildGithubRepoRegistry,
  isGithubRepoEnabled,
  listGithubRepoSlugs,
  resolveGithubRepoEntry,
} from "./repo-registry.js";

const FIXTURE_ENTRIES = [
  {
    slug: "meu-agente",
    owner: "maxwellnasci",
    label: "meu-agente",
    defaultRef: "master",
    enabled: false,
  },
  { slug: "arbo", owner: "maxwellnasci", label: "arbo", defaultRef: "master", enabled: false },
  {
    slug: "Mox---Sistemas",
    owner: "maxwellnasci",
    label: "mox",
    defaultRef: "main",
    enabled: true,
  },
];

describe("repo-registry", () => {
  it("only enables the entries marked enabled", () => {
    const registry = buildGithubRepoRegistry(FIXTURE_ENTRIES);
    const enabled = listGithubRepoSlugs(registry).filter((slug) => isGithubRepoEnabled(registry, slug));
    expect(enabled).toEqual(["Mox---Sistemas"]);
  });

  it("uses the exact GitHub slug, not a friendly nickname", () => {
    const registry = buildGithubRepoRegistry(FIXTURE_ENTRIES);
    expect(resolveGithubRepoEntry(registry, "mox")).toBeUndefined();
    expect(resolveGithubRepoEntry(registry, "Mox")).toBeUndefined();
    expect(resolveGithubRepoEntry(registry, "Mox---Sistemas")?.label).toBe("mox");
  });

  it("resolveGithubRepoEntry / isGithubRepoEnabled agree with each other", () => {
    const registry = buildGithubRepoRegistry(FIXTURE_ENTRIES);
    for (const slug of listGithubRepoSlugs(registry)) {
      const expected = FIXTURE_ENTRIES.find((entry) => entry.slug === slug)?.enabled;
      expect(isGithubRepoEnabled(registry, slug)).toBe(expected);
    }
    expect(isGithubRepoEnabled(registry, "not-a-real-repo")).toBe(false);
  });

  it("returns undefined for unknown slugs instead of throwing", () => {
    const registry = buildGithubRepoRegistry(FIXTURE_ENTRIES);
    expect(resolveGithubRepoEntry(registry, "does-not-exist")).toBeUndefined();
  });

  it("builds an empty registry from an empty entry list", () => {
    const registry = buildGithubRepoRegistry([]);
    expect(listGithubRepoSlugs(registry)).toEqual([]);
  });
});
