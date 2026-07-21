import { describe, expect, it, vi } from "vitest";
import { createGithubRepoReportTool } from "./tool.js";

describe("github_repo_report tool", () => {
  it("has the expected fixed shape (name, no free-text params)", () => {
    const tool = createGithubRepoReportTool();
    expect(tool.name).toBe("github_repo_report");
    expect(Object.keys(tool.parameters.properties)).toEqual(["repo", "ref"]);
  });

  it("fails closed for a repo that is in the enum but not enabled", async () => {
    const tool = createGithubRepoReportTool();
    await expect(tool.execute("call-1", { repo: "arbo" })).rejects.toThrow(/not enabled yet/);
  });

  it("fails closed for a repo not in the registry at all", async () => {
    const tool = createGithubRepoReportTool();
    await expect(tool.execute("call-2", { repo: "totally-unknown" })).rejects.toThrow(
      /Unknown repo/,
    );
  });
});
