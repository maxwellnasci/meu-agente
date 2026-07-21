import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import { verifyWhatsAppCloudSignature } from "./webhook-signature.js";

const APP_SECRET = "test-app-secret";
const BODY = JSON.stringify({ hello: "world" });

function sign(body: string, secret: string): string {
  return `sha256=${createHmac("sha256", secret).update(body).digest("hex")}`;
}

describe("verifyWhatsAppCloudSignature", () => {
  it("accepts a correctly signed body", () => {
    expect(
      verifyWhatsAppCloudSignature({
        signatureHeader: sign(BODY, APP_SECRET),
        rawBody: BODY,
        appSecret: APP_SECRET,
      }),
    ).toBe(true);
  });

  it("rejects a signature computed with the wrong secret", () => {
    expect(
      verifyWhatsAppCloudSignature({
        signatureHeader: sign(BODY, "wrong-secret"),
        rawBody: BODY,
        appSecret: APP_SECRET,
      }),
    ).toBe(false);
  });

  it("rejects a signature for a tampered body", () => {
    expect(
      verifyWhatsAppCloudSignature({
        signatureHeader: sign(BODY, APP_SECRET),
        rawBody: JSON.stringify({ hello: "tampered" }),
        appSecret: APP_SECRET,
      }),
    ).toBe(false);
  });

  it("rejects a missing signature header", () => {
    expect(
      verifyWhatsAppCloudSignature({
        signatureHeader: undefined,
        rawBody: BODY,
        appSecret: APP_SECRET,
      }),
    ).toBe(false);
  });

  it("rejects a header without the sha256= prefix", () => {
    expect(
      verifyWhatsAppCloudSignature({
        signatureHeader: createHmac("sha256", APP_SECRET).update(BODY).digest("hex"),
        rawBody: BODY,
        appSecret: APP_SECRET,
      }),
    ).toBe(false);
  });

  it("rejects when appSecret is empty", () => {
    expect(
      verifyWhatsAppCloudSignature({
        signatureHeader: sign(BODY, APP_SECRET),
        rawBody: BODY,
        appSecret: "",
      }),
    ).toBe(false);
  });
});
