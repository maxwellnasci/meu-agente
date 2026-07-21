import { describe, expect, it } from "vitest";
import type { PluginLogger } from "../api.js";
import { createGithubRepoReportTool } from "./tool.js";

const STAGE_TIMEOUT_MS = 100_000;

function timestampedLogger(stage: string): PluginLogger {
  const startedAt = performance.now();
  const line = (level: string) => (message: string) => {
    console.log(`[+${Math.round(performance.now() - startedAt)}ms][${stage}][${level}] ${message}`);
  };
  return { debug: line("debug"), info: line("info"), warn: line("warn"), error: line("error") };
}

describe("bug4 concurrency reproduction", () => {
  it("runs 5 concurrent executions", async () => {
    const concurrency = 5;
    console.log(`Starting ${concurrency} concurrent executions...`);
    
    // We are simulating the full pipeline to see if they contend
    delete process.env.GITHUB_REPORT_DEBUG_STOP_AFTER;
    
    const promises = Array.from({ length: concurrency }).map(async (_, i) => {
      const id = `req-${i}`;
      console.log(`[${id}] Started`);
      const tool = createGithubRepoReportTool(timestampedLogger(`concurrent-${i}`));
      const result = await tool.execute(`run-${i}`, { repo: "Mox---Sistemas" });
      console.log(`[${id}] Finished`);
      return result;
    });

    const results = await Promise.all(promises);
    expect(results.length).toBe(concurrency);
    console.log("All concurrent executions finished successfully.");
  }, STAGE_TIMEOUT_MS);
});
