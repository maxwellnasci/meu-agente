import { afterEach, describe, expect, it, vi } from "vitest";
import type { GithubRepoEntry } from "./repo-registry.js";

const entry: GithubRepoEntry = {
  slug: "Mox---Sistemas",
  owner: "maxwellnasci",
  label: "mox",
  defaultRef: "main",
  enabled: true,
};

function fakeWorkspace(overrides: Partial<{ write: (...args: unknown[]) => Promise<string> }> = {}) {
  return {
    dir: "/tmp/fake-workspace",
    write: overrides.write ?? vi.fn(async () => "/tmp/fake-workspace/repo.tar.gz"),
  } as unknown as import("../api.js").TempWorkspace;
}

describe("fetchGithubRepoTarball", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("builds the tarball URL from owner/slug/ref and defaults ref to defaultRef", async () => {
    const fetchMock = vi.fn(async () => new Response("nope", { status: 404, statusText: "Not Found" }));
    vi.stubGlobal("fetch", fetchMock);
    const { fetchGithubRepoTarball } = await import("./github-fetch.js");

    await expect(fetchGithubRepoTarball(entry, undefined, fakeWorkspace())).rejects.toThrow(
      /404/,
    );
    const [calledUrl] = fetchMock.mock.calls[0] as [string];
    expect(calledUrl).toBe(
      "https://api.github.com/repos/maxwellnasci/Mox---Sistemas/tarball/main",
    );
  });

  it("uses the explicit ref when provided", async () => {
    const fetchMock = vi.fn(async () => new Response("nope", { status: 404, statusText: "Not Found" }));
    vi.stubGlobal("fetch", fetchMock);
    const { fetchGithubRepoTarball } = await import("./github-fetch.js");

    await expect(
      fetchGithubRepoTarball(entry, "feature/x", fakeWorkspace()),
    ).rejects.toThrow(/404/);
    const [calledUrl] = fetchMock.mock.calls[0] as [string];
    expect(calledUrl).toBe(
      "https://api.github.com/repos/maxwellnasci/Mox---Sistemas/tarball/feature%2Fx",
    );
  });

  it("rejects when GitHub reports a content-length above the size cap", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("body", {
            status: 200,
            headers: { "content-length": String(200 * 1024 * 1024) },
          }),
      ),
    );
    const { fetchGithubRepoTarball } = await import("./github-fetch.js");

    await expect(fetchGithubRepoTarball(entry, undefined, fakeWorkspace())).rejects.toThrow(
      /exceeds/,
    );
  });
});
