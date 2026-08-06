import { describe, expect, it } from "vitest";
import { createGithubRepoReportSchema } from "./schema.js";

describe("createGithubRepoReportSchema", () => {
  it("has no free-text/command field — only repo and ref", () => {
    const schema = createGithubRepoReportSchema(["Mox---Sistemas"]);
    expect(Object.keys(schema.properties)).toEqual(["repo", "ref"]);
  });

  it("rejects unknown properties", () => {
    const schema = createGithubRepoReportSchema(["Mox---Sistemas"]);
    expect(schema.additionalProperties).toBe(false);
  });

  it("repo enum matches the given slugs exactly (no drift)", () => {
    const slugs = ["meu-agente", "arbo", "Mox---Sistemas"];
    const schema = createGithubRepoReportSchema(slugs);
    expect(schema.properties.repo.enum).toEqual(slugs);
  });

  it("ref is optional", () => {
    const schema = createGithubRepoReportSchema(["Mox---Sistemas"]);
    expect(schema.required ?? []).not.toContain("ref");
  });

  it("documents that an empty slug list drops the enum constraint entirely (must never be called with [])", () => {
    const schema = createGithubRepoReportSchema([]);
    expect(schema.properties.repo.enum).toBeUndefined();
  });
});
