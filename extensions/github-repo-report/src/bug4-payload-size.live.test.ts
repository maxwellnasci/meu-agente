// Throwaway measurement harness for the Antigravity "93k token payload"
// hypothesis audit (2026-07-16). NOT a regression test. Calls the real tool
// against the real Mox---Sistemas repo over the real network and measures
// the actual report size, then simulates appending it to a large
// conversation history to check the claimed ~89k/~93k token figures.
// Delete after the audit concludes.
import { describe, expect, it } from "vitest";
import type { PluginLogger } from "../api.js";
import { createGithubRepoReportTool } from "./tool.js";

const liveEnabled = process.env.OPENCLAW_LIVE_TEST === "1";
const describeLive = liveEnabled ? describe : describe.skip;

function silentLogger(): PluginLogger {
  const noop = () => {};
  return { debug: noop, info: noop, warn: noop, error: noop };
}

// Rough approximation (~4 chars/token for English/code mixed text) since no
// tokenizer package is available in this repo. Reported alongside raw char
// counts so the reader can judge the estimate.
function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

describe("bug4 payload-size audit (real mox report + simulated WhatsApp history)", () => {
  describeLive("live", () => {
    it("measures real report size for Mox---Sistemas and a simulated large-history payload", async () => {
      const tool = createGithubRepoReportTool(silentLogger());
      const result = await tool.execute("bug4-payload-audit", { repo: "Mox---Sistemas" });
      const reportText = result.content[0]?.type === "text" ? result.content[0].text : "";

      const reportChars = reportText.length;
      const reportTokensEst = estimateTokens(reportText);

      // Simulate a "long WhatsApp conversation history" the way the
      // hypothesis describes: many prior turns of realistic-length
      // messages exchanged before the tool call.
      const simulatedTurn =
        "Usuário: pode ver esse repositório e me dizer o que mudou recentemente? " +
        "Assistente: claro, deixa eu verificar os arquivos principais e te retorno com um resumo detalhado.";
      const HISTORY_TURNS = 80; // generous stand-in for "várias trocas de mensagem antes"
      const historyText = new Array(HISTORY_TURNS).fill(simulatedTurn).join("\n");
      const historyChars = historyText.length;
      const historyTokensEst = estimateTokens(historyText);

      const totalChars = reportChars + historyChars;
      const totalTokensEst = reportTokensEst + historyTokensEst;

      // eslint-disable-next-line no-console
      console.log(
        JSON.stringify(
          {
            reportChars,
            reportTokensEst,
            historyChars,
            historyTokensEst,
            totalChars,
            totalTokensEst,
          },
          null,
          2,
        ),
      );

      expect(reportText).toMatch(/# Repo report: mox/);
    }, 100_000);
  });
});
