// WhatsApp Cloud plugin module implements the Meta webhook verification handshake.
import type { IncomingMessage, ServerResponse } from "node:http";
import { safeEqualSecret } from "openclaw/plugin-sdk/security-runtime";

export function handleWhatsAppCloudVerificationRequest(params: {
  req: IncomingMessage;
  res: ServerResponse;
  verifyToken: string;
}): void {
  const url = new URL(params.req.url ?? "/", "http://localhost");
  const mode = url.searchParams.get("hub.mode");
  const token = url.searchParams.get("hub.verify_token") ?? "";
  const challenge = url.searchParams.get("hub.challenge") ?? "";

  if (mode !== "subscribe" || !challenge || !safeEqualSecret(token, params.verifyToken)) {
    params.res.statusCode = 403;
    params.res.setHeader("content-type", "text/plain; charset=utf-8");
    params.res.end("Verification failed");
    return;
  }

  params.res.statusCode = 200;
  params.res.setHeader("content-type", "text/plain; charset=utf-8");
  params.res.end(challenge);
}
