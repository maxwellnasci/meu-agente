import { describe, expect, it } from "vitest";
import { resolveGithubRepoReportPluginConfig } from "./config.js";

describe("resolveGithubRepoReportPluginConfig", () => {
  it("returns an empty list when no repos are configured", () => {
    expect(resolveGithubRepoReportPluginConfig({ pluginConfig: undefined })).toEqual([]);
    expect(resolveGithubRepoReportPluginConfig({ pluginConfig: {} })).toEqual([]);
  });

  it("applies the top-level owner and the enabled/defaultRef defaults", () => {
    const entries = resolveGithubRepoReportPluginConfig({
      pluginConfig: {
        owner: "maxwellnasci",
        repos: [{ slug: "Mox---Sistemas", label: "mox" }],
      },
    });

    expect(entries).toEqual([
      {
        slug: "Mox---Sistemas",
        owner: "maxwellnasci",
        label: "mox",
        defaultRef: "main",
        enabled: true,
      },
    ]);
  });

  it("lets a repo entry override the top-level owner", () => {
    const entries = resolveGithubRepoReportPluginConfig({
      pluginConfig: {
        owner: "maxwellnasci",
        repos: [{ slug: "some-repo", owner: "other-org" }],
      },
    });

    expect(entries[0]?.owner).toBe("other-org");
  });

  it("defaults label to slug when not given", () => {
    const entries = resolveGithubRepoReportPluginConfig({
      pluginConfig: { owner: "maxwellnasci", repos: [{ slug: "some-repo" }] },
    });

    expect(entries[0]?.label).toBe("some-repo");
  });

  it("rejects duplicate slugs", () => {
    expect(() =>
      resolveGithubRepoReportPluginConfig({
        pluginConfig: {
          owner: "maxwellnasci",
          repos: [{ slug: "dup" }, { slug: "dup" }],
        },
      }),
    ).toThrow(/duplicate slug "dup"/);
  });

  it("rejects a repo entry with no resolvable owner", () => {
    expect(() =>
      resolveGithubRepoReportPluginConfig({
        pluginConfig: { repos: [{ slug: "no-owner" }] },
      }),
    ).toThrow(/missing owner/);
  });

  it("rejects unknown top-level properties (additionalProperties: false)", () => {
    expect(() =>
      resolveGithubRepoReportPluginConfig({
        pluginConfig: { ownerTypo: "maxwellnasci" },
      }),
    ).toThrow();
  });
});
