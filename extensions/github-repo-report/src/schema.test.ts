import { describe, expect, it } from "vitest";
import { GITHUB_REPO_SLUGS } from "./repo-registry.js";
import { GithubRepoReportSchema } from "./schema.js";

describe("GithubRepoReportSchema", () => {
  it("has no free-text/command field — only repo and ref", () => {
    expect(Object.keys(GithubRepoReportSchema.properties)).toEqual(["repo", "ref"]);
  });

  it("rejects unknown properties", () => {
    expect(GithubRepoReportSchema.additionalProperties).toBe(false);
  });

  it("repo enum matches the repo registry exactly (no drift)", () => {
    expect(GithubRepoReportSchema.properties.repo.enum).toEqual(GITHUB_REPO_SLUGS);
  });

  it("ref is optional", () => {
    expect(GithubRepoReportSchema.required ?? []).not.toContain("ref");
  });
});
