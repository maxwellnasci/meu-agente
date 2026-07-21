import { describe, expect, it } from "vitest";
import {
  GITHUB_REPO_REGISTRY,
  GITHUB_REPO_SLUGS,
  isGithubRepoEnabled,
  resolveGithubRepoEntry,
} from "./repo-registry.js";

describe("repo-registry", () => {
  it("only enables Mox---Sistemas in the first test round", () => {
    const enabled = GITHUB_REPO_SLUGS.filter((slug) => GITHUB_REPO_REGISTRY[slug].enabled);
    expect(enabled).toEqual(["Mox---Sistemas"]);
  });

  it("uses the exact GitHub slug, not a friendly nickname", () => {
    expect(resolveGithubRepoEntry("mox")).toBeUndefined();
    expect(resolveGithubRepoEntry("Mox")).toBeUndefined();
    expect(resolveGithubRepoEntry("Mox---Sistemas")?.label).toBe("mox");
  });

  it("resolveGithubRepoEntry / isGithubRepoEnabled agree with each other", () => {
    for (const slug of GITHUB_REPO_SLUGS) {
      expect(isGithubRepoEnabled(slug)).toBe(GITHUB_REPO_REGISTRY[slug].enabled);
    }
    expect(isGithubRepoEnabled("not-a-real-repo")).toBe(false);
  });

  it("returns undefined for unknown slugs instead of throwing", () => {
    expect(resolveGithubRepoEntry("does-not-exist")).toBeUndefined();
  });
});
