import { describe, expect, it, vi } from "vitest";
import type { OpenClawPluginApi } from "../api.js";
import { consumePendingAskMax, tryCreatePendingAskMax, type PendingAskMaxRecord } from "./store.js";

function fakeApi(): { api: OpenClawPluginApi; map: Map<string, unknown> } {
  const map = new Map<string, unknown>();
  const api = {
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

const RECORD: PendingAskMaxRecord = {
  question: "Posso remarcar o treino de amanhã?",
  askedAt: 1_700_000_000_000,
  origin: { channel: "whatsapp-cloud", to: "554199999999" },
};

describe("tryCreatePendingAskMax / consumePendingAskMax", () => {
  it("creates a pending record when none exists", async () => {
    const { api } = fakeApi();
    await expect(tryCreatePendingAskMax(api, RECORD)).resolves.toBe(true);
  });

  it("refuses to create a second pending record while one is open", async () => {
    const { api } = fakeApi();
    await tryCreatePendingAskMax(api, RECORD);
    await expect(
      tryCreatePendingAskMax(api, { ...RECORD, question: "outra pergunta" }),
    ).resolves.toBe(false);
  });

  it("consume returns undefined when nothing is pending", async () => {
    const { api } = fakeApi();
    await expect(consumePendingAskMax(api)).resolves.toBeUndefined();
  });

  it("consume returns and clears the pending record", async () => {
    const { api, map } = fakeApi();
    await tryCreatePendingAskMax(api, RECORD);
    await expect(consumePendingAskMax(api)).resolves.toEqual(RECORD);
    expect(map.size).toBe(0);
  });

  it("allows a new pending record after the previous one is consumed", async () => {
    const { api } = fakeApi();
    await tryCreatePendingAskMax(api, RECORD);
    await consumePendingAskMax(api);
    await expect(tryCreatePendingAskMax(api, RECORD)).resolves.toBe(true);
  });

  it("strips undefined fields before persisting, including nested origin", async () => {
    const { api, map } = fakeApi();
    await tryCreatePendingAskMax(api, {
      question: "q",
      context: undefined,
      askedAt: 1,
      origin: { channel: "whatsapp-cloud", to: "1", accountId: undefined, threadId: undefined },
    });
    const stored = map.get("pending") as Record<string, unknown>;
    expect(Object.keys(stored)).not.toContain("context");
    expect(Object.keys(stored.origin as Record<string, unknown>)).toEqual(["channel", "to"]);
  });

  it("uses a fresh store call per operation (no stale handle reused)", async () => {
    const { api } = fakeApi();
    const openKeyedStoreSpy = vi.spyOn(api.runtime.state, "openKeyedStore");
    await tryCreatePendingAskMax(api, RECORD);
    await consumePendingAskMax(api);
    expect(openKeyedStoreSpy).toHaveBeenCalledTimes(2);
  });
});
