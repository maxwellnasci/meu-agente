import { beforeEach, describe, expect, it, vi } from "vitest";

const { sendAskMaxMessageMock } = vi.hoisted(() => ({ sendAskMaxMessageMock: vi.fn() }));

vi.mock("./proactive-send.js", () => ({
  sendAskMaxMessage: sendAskMaxMessageMock,
}));

import type { OpenClawPluginApi } from "../api.js";
import { phoneLikelyMatches, registerAskMaxResolveHook } from "./resolve-hook.js";
import { tryCreatePendingAskMax } from "./store.js";

type Handler = (event: unknown, ctx: unknown) => unknown;

function fakeApi(
  pluginConfig: Record<string, unknown>,
): { api: OpenClawPluginApi; handlers: Map<string, Handler>; map: Map<string, unknown> } {
  const map = new Map<string, unknown>();
  const handlers = new Map<string, Handler>();
  const api = {
    pluginConfig,
    logger: { warn: vi.fn(), info: vi.fn(), error: vi.fn(), debug: vi.fn() },
    on: (event: string, handler: Handler) => {
      handlers.set(event, handler);
    },
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
  return { api, handlers, map };
}

const TARGET_CONFIG = { channel: "whatsapp-cloud", to: "5541984445755" };

describe("phoneLikelyMatches", () => {
  it("matches identical numbers", () => {
    expect(phoneLikelyMatches("5541984445755", "5541984445755")).toBe(true);
  });

  it("matches numbers differing only by a leading mobile 9 digit", () => {
    expect(phoneLikelyMatches("5541984445755", "554184445755")).toBe(true);
    expect(phoneLikelyMatches("554184445755", "5541984445755")).toBe(true);
  });

  it("does not match unrelated numbers", () => {
    expect(phoneLikelyMatches("5541984445755", "5511999998888")).toBe(false);
  });

  it("does not match numbers differing by more than one digit of slack", () => {
    expect(phoneLikelyMatches("5541984445755", "41984445755")).toBe(false);
  });

  it("ignores formatting characters", () => {
    expect(phoneLikelyMatches("+55 (41) 98444-5755", "5541984445755")).toBe(true);
  });
});

describe("registerAskMaxResolveHook", () => {
  beforeEach(() => {
    sendAskMaxMessageMock.mockReset();
    sendAskMaxMessageMock.mockResolvedValue({ ok: true });
  });

  it("passes through when the operator target is not configured", async () => {
    const { api, handlers } = fakeApi({});
    registerAskMaxResolveHook(api);
    const result = await handlers.get("before_agent_run")!(
      { prompt: "oi" },
      { channel: "whatsapp-cloud", chatId: "5541984445755" },
    );
    expect(result).toBeUndefined();
    expect(sendAskMaxMessageMock).not.toHaveBeenCalled();
  });

  it("passes through when the sender does not match the configured operator", async () => {
    const { api, handlers } = fakeApi(TARGET_CONFIG);
    registerAskMaxResolveHook(api);
    const result = await handlers.get("before_agent_run")!(
      { prompt: "oi" },
      { channel: "whatsapp-cloud", chatId: "5511999998888" },
    );
    expect(result).toBeUndefined();
    expect(sendAskMaxMessageMock).not.toHaveBeenCalled();
  });

  it("passes through when the channel does not match, even if the number does", async () => {
    const { api, handlers } = fakeApi(TARGET_CONFIG);
    registerAskMaxResolveHook(api);
    const result = await handlers.get("before_agent_run")!(
      { prompt: "oi" },
      { channel: "telegram", chatId: "5541984445755" },
    );
    expect(result).toBeUndefined();
    expect(sendAskMaxMessageMock).not.toHaveBeenCalled();
  });

  it("passes through when the operator writes but nothing is pending", async () => {
    const { api, handlers } = fakeApi(TARGET_CONFIG);
    registerAskMaxResolveHook(api);
    const result = await handlers.get("before_agent_run")!(
      { prompt: "oi" },
      { channel: "whatsapp-cloud", chatId: "5541984445755" },
    );
    expect(result).toBeUndefined();
    expect(sendAskMaxMessageMock).not.toHaveBeenCalled();
  });

  it("consumes the pending question, blocks the turn, and routes the answer plus ack — matching even with the leading-9 variant", async () => {
    const { api, handlers, map } = fakeApi(TARGET_CONFIG);
    await tryCreatePendingAskMax(api, {
      question: "Posso remarcar amanhã?",
      askedAt: 1,
      origin: { channel: "whatsapp-cloud", to: "554177776666" },
    });
    registerAskMaxResolveHook(api);

    // Inbound chatId omits the leading 9 that the configured target has —
    // this is the exact real-world mismatch found live on 2026-07-18.
    const result = await handlers.get("before_agent_run")!(
      { prompt: "Pode sim, sem problema" },
      { channel: "whatsapp-cloud", chatId: "554184445755" },
    );

    expect(result).toEqual({
      outcome: "block",
      reason: "ask-max: message consumed as the pending escalation answer",
    });
    expect(map.size).toBe(0);

    await vi.waitFor(() => expect(sendAskMaxMessageMock).toHaveBeenCalledTimes(2));
    expect(sendAskMaxMessageMock).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        target: { channel: "whatsapp-cloud", to: "554177776666" },
        text: expect.stringContaining("Pode sim, sem problema"),
      }),
    );
    expect(sendAskMaxMessageMock).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        target: TARGET_CONFIG,
      }),
    );
  });

  it("does not block a message once the pending record is gone", async () => {
    const { api, handlers } = fakeApi(TARGET_CONFIG);
    registerAskMaxResolveHook(api);
    const result = await handlers.get("before_agent_run")!(
      { prompt: "e aí, tudo certo?" },
      { channel: "whatsapp-cloud", chatId: "5541984445755" },
    );
    expect(result).toBeUndefined();
  });
});
