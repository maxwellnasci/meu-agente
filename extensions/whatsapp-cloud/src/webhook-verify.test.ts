import type { IncomingMessage, ServerResponse } from "node:http";
import { describe, expect, it } from "vitest";
import { handleWhatsAppCloudVerificationRequest } from "./webhook-verify.js";

const VERIFY_TOKEN = "correct-token";

function fakeReq(url: string): IncomingMessage {
  return { url } as IncomingMessage;
}

function fakeRes(): ServerResponse & { statusCode: number; body: string } {
  const res = {
    statusCode: 0,
    body: "",
    setHeader() {},
    end(chunk?: string) {
      res.body = chunk ?? "";
    },
  };
  return res as unknown as ServerResponse & { statusCode: number; body: string };
}

describe("handleWhatsAppCloudVerificationRequest", () => {
  it("echoes hub.challenge when mode and token match", () => {
    const res = fakeRes();
    handleWhatsAppCloudVerificationRequest({
      req: fakeReq("/webhook/whatsapp-cloud?hub.mode=subscribe&hub.verify_token=correct-token&hub.challenge=12345"),
      res,
      verifyToken: VERIFY_TOKEN,
    });
    expect(res.statusCode).toBe(200);
    expect(res.body).toBe("12345");
  });

  it("rejects when hub.verify_token does not match", () => {
    const res = fakeRes();
    handleWhatsAppCloudVerificationRequest({
      req: fakeReq("/webhook/whatsapp-cloud?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=12345"),
      res,
      verifyToken: VERIFY_TOKEN,
    });
    expect(res.statusCode).toBe(403);
  });

  it("rejects when hub.mode is not subscribe", () => {
    const res = fakeRes();
    handleWhatsAppCloudVerificationRequest({
      req: fakeReq("/webhook/whatsapp-cloud?hub.mode=unsubscribe&hub.verify_token=correct-token&hub.challenge=12345"),
      res,
      verifyToken: VERIFY_TOKEN,
    });
    expect(res.statusCode).toBe(403);
  });

  it("rejects when hub.challenge is missing", () => {
    const res = fakeRes();
    handleWhatsAppCloudVerificationRequest({
      req: fakeReq("/webhook/whatsapp-cloud?hub.mode=subscribe&hub.verify_token=correct-token"),
      res,
      verifyToken: VERIFY_TOKEN,
    });
    expect(res.statusCode).toBe(403);
  });
});
