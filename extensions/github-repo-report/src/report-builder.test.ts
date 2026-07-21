import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { buildRepoReport } from "./report-builder.js";

describe("buildRepoReport", () => {
  let dir: string;

  beforeEach(async () => {
    dir = await fs.mkdtemp(path.join(os.tmpdir(), "report-builder-test-"));
  });

  afterEach(async () => {
    await fs.rm(dir, { recursive: true, force: true });
  });

  it("lists files in the tree and inlines README/package.json content", async () => {
    await fs.writeFile(path.join(dir, "README.md"), "# Hello\nWorld");
    await fs.writeFile(path.join(dir, "package.json"), '{"name":"x"}');
    await fs.mkdir(path.join(dir, "src"));
    await fs.writeFile(path.join(dir, "src", "index.ts"), "export const x = 1;");

    const report = await buildRepoReport({ rootDir: dir, repoLabel: "mox", ref: "main" });

    expect(report).toContain("Repo report: mox @ main");
    expect(report).toContain("README.md");
    expect(report).toContain("package.json");
    expect(report).toContain("src/index.ts");
    expect(report).toContain("# Hello\nWorld");
    expect(report).toContain('{"name":"x"}');
  });

  it("skips .git directories", async () => {
    await fs.mkdir(path.join(dir, ".git"));
    await fs.writeFile(path.join(dir, ".git", "HEAD"), "ref: refs/heads/main");
    await fs.writeFile(path.join(dir, "a.txt"), "hi");

    const report = await buildRepoReport({ rootDir: dir, repoLabel: "mox", ref: "main" });

    expect(report).not.toContain(".git");
    expect(report).toContain("a.txt");
  });

  it("does not inline files larger than the cap or files not on the allowlist", async () => {
    await fs.writeFile(path.join(dir, "notes.txt"), "should not be inlined");

    const report = await buildRepoReport({ rootDir: dir, repoLabel: "mox", ref: "main" });

    expect(report).toContain("notes.txt");
    expect(report).not.toContain("should not be inlined");
  });
});
