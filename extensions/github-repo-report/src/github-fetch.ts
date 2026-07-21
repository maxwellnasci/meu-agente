import fs from "node:fs/promises";
import path from "node:path";
// Downloads and extracts one GitHub repo tarball, entirely in the host
// (gateway) process — this never touches the Docker sandbox or its network
// namespace. See docs/SESSAO_2026-07-15.md, "Desenho mínimo pra clonar + ler
// 1 repositório", for why this pattern was chosen over a sandbox network
// exception.
import { extractArchive } from "@openclaw/fs-safe/archive";
import type { PluginLogger, TempWorkspace } from "../api.js";
import { createTimingMarker } from "./debug-timing.js";
import type { GithubRepoEntry } from "./repo-registry.js";

const MAX_ARCHIVE_BYTES = 50 * 1024 * 1024; // 50 MB compressed
const MAX_EXTRACTED_BYTES = 150 * 1024 * 1024; // 150 MB uncompressed
const MAX_ENTRIES = 20_000;
const MAX_ENTRY_BYTES = 20 * 1024 * 1024;
const FETCH_TIMEOUT_MS = 30_000;
const EXTRACT_TIMEOUT_MS = 30_000;

export type FetchedGithubRepo = {
  rootDir: string;
  ref: string;
};

export async function fetchGithubRepoTarball(
  entry: GithubRepoEntry,
  ref: string | undefined,
  workspace: TempWorkspace,
  logger?: PluginLogger,
): Promise<FetchedGithubRepo> {
  const mark = createTimingMarker(logger, "fetch");
  const resolvedRef = ref?.trim() || entry.defaultRef;
  const url = `https://api.github.com/repos/${entry.owner}/${entry.slug}/tarball/${encodeURIComponent(resolvedRef)}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  // clearTimeout stays in finally around the whole request lifecycle (fetch,
  // body read, write, extraction) so a stalled body stream after headers
  // arrive still gets aborted instead of hanging past FETCH_TIMEOUT_MS.
  try {
    mark("http:start");
    const response = await fetch(url, {
      headers: {
        "user-agent": "openclaw-github-repo-report",
        accept: "application/vnd.github+json",
      },
      signal: controller.signal,
    });
    mark("http:headers-received");
    if (!response.ok) {
      throw new Error(
        `GitHub tarball request failed for ${entry.owner}/${entry.slug}@${resolvedRef}: ${response.status} ${response.statusText}`,
      );
    }

    const contentLength = Number(response.headers.get("content-length") ?? "0");
    if (contentLength > MAX_ARCHIVE_BYTES) {
      throw new Error(
        `GitHub tarball for ${entry.slug} exceeds ${MAX_ARCHIVE_BYTES} bytes (reported ${contentLength})`,
      );
    }

    mark("body-read:start");
    const buffer = Buffer.from(await response.arrayBuffer());
    mark("body-read:done");
    if (buffer.byteLength > MAX_ARCHIVE_BYTES) {
      throw new Error(
        `GitHub tarball for ${entry.slug} exceeds ${MAX_ARCHIVE_BYTES} bytes (actual ${buffer.byteLength})`,
      );
    }

    mark("workspace-write:start");
    const archivePath = await workspace.write("repo.tar.gz", buffer);
    const destDir = path.join(workspace.dir, "extracted");
    await fs.mkdir(destDir, { recursive: true });
    mark("workspace-write:done");

    // Bug 4 circuit-breaker isolation (docs/SESSAO_2026-07-15.md): when set,
    // returns right after fetch+write, before extraction ever runs. Debug-only,
    // gated behind an env var never set in production. Remove with debug-timing.ts.
    if (process.env.GITHUB_REPORT_DEBUG_STOP_AFTER === "write") {
      return { rootDir: destDir, ref: resolvedRef };
    }

    mark("extract:start");
    await extractArchive({
      archivePath,
      destDir,
      kind: "tar",
      tarGzip: true,
      timeoutMs: EXTRACT_TIMEOUT_MS,
      // GitHub tarballs wrap everything in a single "<owner>-<repo>-<sha>/"
      // root directory; strip it so report-builder sees real repo-relative paths.
      stripComponents: 1,
      limits: {
        maxArchiveBytes: MAX_ARCHIVE_BYTES,
        maxEntries: MAX_ENTRIES,
        maxExtractedBytes: MAX_EXTRACTED_BYTES,
        maxEntryBytes: MAX_ENTRY_BYTES,
      },
    });
    mark("extract:done");

    return { rootDir: destDir, ref: resolvedRef };
  } finally {
    clearTimeout(timer);
  }
}
