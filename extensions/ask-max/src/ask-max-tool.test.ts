import { beforeEach, describe, expect, it, vi } from "vitest";

const { sendAskMaxMessageMock } = vi.hoisted(() => ({ sendAskMaxMessageMock: vi.fn() }));

vi.mock("./proactive-send.js", () => ({
  sendAskMaxMessage: sendAskMaxMessageMock,
}));

import type { OpenClawPluginApi, OpenClawPluginToolContext } from "../api.js";
import { createAskMaxTool } from "./ask-max-tool.js";

function fakeApi(pluginConfig: Record<string, unknown>): { api: OpenClawPluginApi; map: Map<string, unknown> } {
  const map = new Map<string, unknown>();
  const api = {
    pluginConfig,
    logger: { warn: vi.fn(), info: vi.fn(), error: vi.fn(), debug: vi.fn() },
    runtime: {
      state: {
        openKeyedStore: () => ({
          register: async (key: string, value: unknown) => {
            map.set(key, value);
          },
          registerIfAbsent: async (key: string, value: unknown) => {
            if (map.has(key)) {
              return false;
            }
            map.set(key, value);
            return true;
          },
          lookup: async (key: string) => map.get(key),
          consume: async (key: string) => {
            const value = map.get(key);
            map.delete(key);
            return value;
          },
          delete: async (key: string) => map.delete(key),
          entries: async () => [...map.entries()].map(([key, value]) => ({ key, value })),
          clear: async () => map.clear(),
        }),
      },
    },
  } as unknown as OpenClawPluginApi;
  return { api, map };
}

const CTX_WITH_DELIVERY = {
  deliveryContext: { channel: "whatsapp-cloud", to: "554188887777" },
} as OpenClawPluginToolContext;

const CTX_WITHOUT_DELIVERY = {} as OpenClawPluginToolContext;

describe("createAskMaxTool", () => {
  beforeEach(() => {
    sendAskMaxMessageMock.mockReset();
  });

  it("throws when the run has no delivery context", async () => {
    const { api } = fakeApi({ channel: "whatsapp-cloud", to: "554199999999" });
    const tool = createAskMaxTool(api)(CTX_WITHOUT_DELIVERY);
    await expect(tool.execute("id1", { question: "q" })).rejects.toThrow(/unavailable/);
  });

  it("throws when the operator target is not configured", async () => {
    const { api } = fakeApi({});
    const tool = createAskMaxTool(api)(CTX_WITH_DELIVERY);
    await expect(tool.execute("id1", { question: "q" })).rejects.toThrow(/not configured/);
  });

  it("sends the question and records a pending escalation on success", async () => {
    sendAskMaxMessageMock.mockResolvedValue({ ok: true });
    const { api, map } = fakeApi({ channel: "whatsapp-cloud", to: "554199999999" });
    const tool = createAskMaxTool(api)(CTX_WITH_DELIVERY);
    const result = await tool.execute("id1", { question: "Posso remarcar?", context: "aluno João" });
    expect(result.details).toEqual({ sent: true });
    expect(map.get("pending")).toMatchObject({ question: "Posso remarcar?", context: "aluno João" });
    expect(sendAskMaxMessageMock).toHaveBeenCalledTimes(1);
  });

  it("refuses a second question while one is already pending", async () => {
    sendAskMaxMessageMock.mockResolvedValue({ ok: true });
    const { api } = fakeApi({ channel: "whatsapp-cloud", to: "554199999999" });
    const factory = createAskMaxTool(api);
    await factory(CTX_WITH_DELIVERY).execute("id1", { question: "primeira" });
    const result = await factory(CTX_WITH_DELIVERY).execute("id2", { question: "segunda" });
    expect(result.details).toEqual({ sent: false, reason: "already_pending" });
    expect(sendAskMaxMessageMock).toHaveBeenCalledTimes(1);
  });

  it("clears the pending record when the send fails, so a retry is possible", async () => {
    sendAskMaxMessageMock.mockResolvedValue({
      ok: false,
      reason: "send_failed",
      error: new Error("boom"),
    });
    const { api, map } = fakeApi({ channel: "whatsapp-cloud", to: "554199999999" });
    const tool = createAskMaxTool(api)(CTX_WITH_DELIVERY);
    const result = await tool.execute("id1", { question: "q" });
    expect(result.details).toEqual({ sent: false, reason: "send_failed" });
    expect(map.size).toBe(0);
  });

  it("reports the 24h-window failure distinctly and still clears the pending record", async () => {
    sendAskMaxMessageMock.mockResolvedValue({
      ok: false,
      reason: "outside_24h_window",
      error: new Error("x"),
    });
    const { api, map } = fakeApi({ channel: "whatsapp-cloud", to: "554199999999" });
    const tool = createAskMaxTool(api)(CTX_WITH_DELIVERY);
    const result = await tool.execute("id1", { question: "q" });
    expect(result.details).toEqual({ sent: false, reason: "outside_24h_window" });
    expect(map.size).toBe(0);
  });
});
