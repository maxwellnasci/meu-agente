// WhatsApp Cloud plugin module validates Meta's X-Hub-Signature-256 header.
import { createHmac, timingSafeEqual } from "node:crypto";

const SIGNATURE_PREFIX = "sha256=";

function safeEqual(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

export function verifyWhatsAppCloudSignature(params: {
  signatureHeader: string | undefined;
  rawBody: string;
  appSecret: string;
}): boolean {
  if (!params.signatureHeader || !params.appSecret) {
    return false;
  }
  if (!params.signatureHeader.startsWith(SIGNATURE_PREFIX)) {
    return false;
  }
  const presented = params.signatureHeader.slice(SIGNATURE_PREFIX.length).trim();
  const expected = createHmac("sha256", params.appSecret).update(params.rawBody).digest("hex");
  return safeEqual(presented, expected);
}
