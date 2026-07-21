import { beforeEach, describe, expect, it } from "vitest";
import {
  clearCapturedTurnsForTest,
  peekCapturedTurnCountForTest,
  rememberTurnFinalText,
  rememberTurnPrompt,
  rememberTurnToolExecuted,
  takeCapturedTurn,
} from "./turn-capture.js";

describe("turn-capture", () => {
  beforeEach(() => {
    clearCapturedTurnsForTest();
  });

  it("assembles a full turn from prompt, tool, and reply captures keyed by runId", () => {
    rememberTurnPrompt({
      runId: "run-1",
      prompt: "fisguei o joelho, e agora?",
      sessionKey: "session-1",
      agentId: "main",
      channel: "whatsapp-cloud",
      chatId: "5541999999999",
      senderId: "5541999999999",
    });
    rememberTurnToolExecuted({ runId: "run-1", toolName: "send_alert" });
    rememberTurnFinalText({ runId: "run-1", text: "Quer que eu levante isso com o Coach?" });

    const turn = takeCapturedTurn("run-1");

    expect(turn).toMatchObject({
      runId: "run-1",
      prompt: "fisguei o joelho, e agora?",
      sessionKey: "session-1",
      agentId: "main",
      channel: "whatsapp-cloud",
      chatId: "5541999999999",
      senderId: "5541999999999",
      finalText: "Quer que eu levante isso com o Coach?",
      toolsExecuted: ["send_alert"],
    });
  });

  it("consumes the record: a second take for the same runId returns undefined", () => {
    rememberTurnPrompt({ runId: "run-2", prompt: "oi" });
    expect(takeCapturedTurn("run-2")).toBeDefined();
    expect(takeCapturedTurn("run-2")).toBeUndefined();
  });

  it("returns undefined for a runId that was never captured", () => {
    expect(takeCapturedTurn("never-seen")).toBeUndefined();
  });

  it("dedupes repeated tool names within the same run", () => {
    rememberTurnToolExecuted({ runId: "run-3", toolName: "send_alert" });
    rememberTurnToolExecuted({ runId: "run-3", toolName: "send_alert" });
    rememberTurnToolExecuted({ runId: "run-3", toolName: "schedule_appointment" });

    const turn = takeCapturedTurn("run-3");
    expect(turn?.toolsExecuted).toEqual(["send_alert", "schedule_appointment"]);
  });

  it("accumulates final text across multiple reply payloads for the same run", () => {
    rememberTurnFinalText({ runId: "run-4", text: "primeira parte" });
    rememberTurnFinalText({ runId: "run-4", text: "segunda parte" });

    const turn = takeCapturedTurn("run-4");
    expect(turn?.finalText).toBe("primeira parte\nsegunda parte");
  });

  it("ignores empty-string final text instead of creating a blank turn", () => {
    rememberTurnFinalText({ runId: "run-5", text: "" });
    expect(peekCapturedTurnCountForTest()).toBe(0);
  });

  it("keeps runs isolated from each other", () => {
    rememberTurnPrompt({ runId: "run-a", prompt: "pergunta A" });
    rememberTurnPrompt({ runId: "run-b", prompt: "pergunta B" });

    expect(peekCapturedTurnCountForTest()).toBe(2);
    expect(takeCapturedTurn("run-a")?.prompt).toBe("pergunta A");
    expect(takeCapturedTurn("run-b")?.prompt).toBe("pergunta B");
  });
});
