import { beforeEach, describe, expect, it, vi } from "vitest";

const { deliverOutboundPayloadsMock } = vi.hoisted(() => ({
  deliverOutboundPayloadsMock: vi.fn(),
}));

vi.mock("../api.js", () => ({
  deliverOutboundPayloads: deliverOutboundPayloadsMock,
}));

import type { OpenClawPluginApi } from "../api.js";
import { isOutside24hWindowError, sendAskMaxMessage } from "./proactive-send.js";

function fakeApi(): OpenClawPluginApi {
  return {
    config: {},
    logger: { warn: vi.fn(), info: vi.fn(), error: vi.fn(), debug: vi.fn() },
  } as unknown as OpenClawPluginApi;
}

describe("isOutside24hWindowError", () => {
  it("matches the known Graph API re-engagement error code", () => {
    expect(
      isOutside24hWindowError(
        new Error("WhatsApp Cloud API send failed (470): (#131047) Re-engagement message"),
      ),
    ).toBe(true);
  });

  it("matches generic 24-hour wording", () => {
    expect(
      isOutside24hWindowError(new Error("message outside the 24 hour customer service window")),
    ).toBe(true);
  });

  it("does not match unrelated errors", () => {
    expect(isOutside24hWindowError(new Error("network timeout"))).toBe(false);
  });

  it("handles non-Error values without throwing", () => {
    expect(isOutside24hWindowError("random string")).toBe(false);
    expect(isOutside24hWindowError(undefined)).toBe(false);
  });
});

describe("sendAskMaxMessage", () => {
  beforeEach(() => {
    deliverOutboundPayloadsMock.mockReset();
  });

  it("returns ok when delivery succeeds", async () => {
    deliverOutboundPayloadsMock.mockResolvedValue([{ channel: "whatsapp-cloud", messageId: "1" }]);
    const result = await sendAskMaxMessage({
      api: fakeApi(),
      target: { channel: "whatsapp-cloud", to: "1" },
      text: "oi",
    });
    expect(result).toEqual({ ok: true });
  });

  it("passes the target and text through to the delivery call", async () => {
    deliverOutboundPayloadsMock.mockResolvedValue([]);
    await sendAskMaxMessage({
      api: fakeApi(),
      target: { channel: "whatsapp-cloud", to: "554199999999", accountId: "default" },
      text: "pergunta",
    });
    expect(deliverOutboundPayloadsMock).toHaveBeenCalledWith(
      expect.objectContaining({
        channel: "whatsapp-cloud",
        to: "554199999999",
        accountId: "default",
        payloads: [{ text: "pergunta" }],
      }),
    );
  });

  it("classifies a 24h-window failure distinctly", async () => {
    deliverOutboundPayloadsMock.mockRejectedValue(new Error("(#131047) Re-engagement message"));
    const result = await sendAskMaxMessage({
      api: fakeApi(),
      target: { channel: "whatsapp-cloud", to: "1" },
      text: "oi",
    });
    expect(result.ok).toBe(false);
    expect(result.ok === false && result.reason).toBe("outside_24h_window");
  });

  it("classifies any other failure as send_failed", async () => {
    deliverOutboundPayloadsMock.mockRejectedValue(new Error("network timeout"));
    const result = await sendAskMaxMessage({
      api: fakeApi(),
      target: { channel: "whatsapp-cloud", to: "1" },
      text: "oi",
    });
    expect(result.ok).toBe(false);
    expect(result.ok === false && result.reason).toBe("send_failed");
  });
});
