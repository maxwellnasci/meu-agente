// Pure function: walks an already-extracted repo directory and builds a
// bounded text report. No network, no writes — read-only local filesystem
// access to a directory this plugin already downloaded and extracted itself.
import fs from "node:fs/promises";
import path from "node:path";
import type { PluginLogger } from "../api.js";
import { createTimingMarker } from "./debug-timing.js";

const MAX_TREE_ENTRIES = 500;
const MAX_INLINE_FILE_BYTES = 20_000;
const INLINE_FILENAMES = new Set([
  "README.md",
  "readme.md",
  "Readme.md",
  "package.json",
  "pyproject.toml",
  "Cargo.toml",
  "go.mod",
]);

type FileEntry = { relPath: string; size: number };

async function walk(rootDir: string, dir: string, out: FileEntry[]): Promise<void> {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (out.length >= MAX_TREE_ENTRIES) {
      return;
    }
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === ".git") {
        continue;
      }
      await walk(rootDir, fullPath, out);
      continue;
    }
    if (!entry.isFile()) {
      continue;
    }
    const stat = await fs.stat(fullPath);
    out.push({ relPath: path.relative(rootDir, fullPath), size: stat.size });
  }
}

export async function buildRepoReport(params: {
  rootDir: string;
  repoLabel: string;
  ref: string;
  logger?: PluginLogger;
}): Promise<string> {
  const mark = createTimingMarker(params.logger, "report");
  const files: FileEntry[] = [];
  mark("walk:start");
  await walk(params.rootDir, params.rootDir, files);
  mark("walk:done");
  files.sort((a, b) => a.relPath.localeCompare(b.relPath));

  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  const truncated = files.length >= MAX_TREE_ENTRIES;

  const lines: string[] = [];
  lines.push(`# Repo report: ${params.repoLabel} @ ${params.ref}`);
  lines.push(
    `Files: ${files.length}${truncated ? "+ (tree truncated)" : ""}, total size: ${totalBytes} bytes`,
  );
  lines.push("");
  lines.push("## File tree");
  for (const file of files) {
    lines.push(`- ${file.relPath} (${file.size} bytes)`);
  }

  // Bug 4 circuit-breaker isolation (docs/SESSAO_2026-07-15.md): when set,
  // returns right after the walk, before any inline file is read. Debug-only,
  // gated behind an env var never set in production. Remove with debug-timing.ts.
  if (process.env.GITHUB_REPORT_DEBUG_STOP_AFTER === "walk") {
    return lines.join("\n");
  }

  mark("inline-files:start");
  for (const file of files) {
    const baseName = path.basename(file.relPath);
    if (!INLINE_FILENAMES.has(baseName) || file.size > MAX_INLINE_FILE_BYTES) {
      continue;
    }
    const content = await fs.readFile(path.join(params.rootDir, file.relPath), "utf8");
    lines.push("");
    lines.push(`## ${file.relPath}`);
    lines.push("```");
    lines.push(content);
    lines.push("```");
  }
  mark("inline-files:done");

  return lines.join("\n");
}
