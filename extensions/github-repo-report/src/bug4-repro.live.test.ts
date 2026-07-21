// Bug 4 circuit-breaker isolation (docs/SESSAO_2026-07-15.md).
// Throwaway repro harness — NOT a regression test. Calls the real tool
// against the real Mox---Sistemas repo over the real network, stopping the
// pipeline early via GITHUB_REPORT_DEBUG_STOP_AFTER (see tool.ts,
// github-fetch.ts, report-builder.ts) to bisect which stage hangs.
// Delete this file, and the STOP_AFTER gates it drives, once Bug 4 is closed.
import { describe, expect, it } from "vitest";
import type { PluginLogger } from "../api.js";
import { createGithubRepoReportTool } from "./tool.js";

const liveEnabled = process.env.OPENCLAW_LIVE_TEST === "1";
const describeLive = liveEnabled ? describe : describe.skip;

function timestampedLogger(stage: string): PluginLogger {
  const startedAt = performance.now();
  const line = (level: string) => (message: string) => {
    // eslint-disable-next-line no-console
    console.log(`[+${Math.round(performance.now() - startedAt)}ms][${stage}][${level}] ${message}`);
  };
  return { debug: line("debug"), info: line("info"), warn: line("warn"), error: line("error") };
}

// Comfortably above the internal FETCH_TIMEOUT_MS + EXTRACT_TIMEOUT_MS (30s each
// = 60s worst case). If a stage is still running past this, it is not just slow
// network — it is the hang under investigation.
const STAGE_TIMEOUT_MS = 100_000;

describeLive("bug4 circuit-breaker isolation (real network, real Mox---Sistemas repo)", () => {
  it(
    "TESTE 1: fetch + write only (stop before extract)",
    async () => {
      process.env.GITHUB_REPORT_DEBUG_STOP_AFTER = "write";
      const tool = createGithubRepoReportTool(timestampedLogger("teste1-write"));
      const result = await tool.execute("bug4-teste1", { repo: "Mox---Sistemas" });
      const text = result.content[0]?.type === "text" ? result.content[0].text : "";
      expect(text).toMatch(/stopped after fetch stage "write"/);
    },
    STAGE_TIMEOUT_MS,
  );

  it(
    "TESTE 2: fetch + write + extract (stop before walk)",
    async () => {
      process.env.GITHUB_REPORT_DEBUG_STOP_AFTER = "extract";
      const tool = createGithubRepoReportTool(timestampedLogger("teste2-extract"));
      const result = await tool.execute("bug4-teste2", { repo: "Mox---Sistemas" });
      const text = result.content[0]?.type === "text" ? result.content[0].text : "";
      expect(text).toMatch(/stopped after fetch stage "extract"/);
    },
    STAGE_TIMEOUT_MS,
  );

  it(
    "TESTE 3: + walk file tree (stop before inline-file reads / final report)",
    async () => {
      process.env.GITHUB_REPORT_DEBUG_STOP_AFTER = "walk";
      const tool = createGithubRepoReportTool(timestampedLogger("teste3-walk"));
      const result = await tool.execute("bug4-teste3", { repo: "Mox---Sistemas" });
      const text = result.content[0]?.type === "text" ? result.content[0].text : "";
      expect(text).toMatch(/## File tree/);
    },
    STAGE_TIMEOUT_MS,
  );

  it(
    "TESTE 4: full pipeline, no circuit breaker",
    async () => {
      delete process.env.GITHUB_REPORT_DEBUG_STOP_AFTER;
      const tool = createGithubRepoReportTool(timestampedLogger("teste4-full"));
      const result = await tool.execute("bug4-teste4", { repo: "Mox---Sistemas" });
      const text = result.content[0]?.type === "text" ? result.content[0].text : "";
      expect(text).toMatch(/# Repo report: mox/);
    },
    STAGE_TIMEOUT_MS,
  );
});
