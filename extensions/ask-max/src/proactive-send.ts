// Shared proactive-send helper: used to deliver the escalation question, the
// operator's short ack, and the routed answer back to the original asker.
// Wraps deliverOutboundPayloads (openclaw/plugin-sdk/outbound-runtime) — the
// only plugin-sdk-exposed seam found for sending a message that is not a
// reply to the turn currently being processed. No bundled extension used
// this path before ask-max; this is the first thing to validate live before
// trusting it in production (see docs/SESSAO_2026-07-18.md).
import { deliverOutboundPayloads, type OpenClawPluginApi, type ReplyPayload } from "../api.js";
import type { PendingAskMaxTarget } from "./store.js";

export type ProactiveSendResult =
  | { ok: true }
  | { ok: false; reason: "outside_24h_window"; error: unknown }
  | { ok: false; reason: "send_failed"; error: unknown };

type DeliverOutboundPayloadsParams = Parameters<typeof deliverOutboundPayloads>[0];

// WhatsApp Cloud (Meta Graph API) only accepts free-form text within 24h of
// the recipient's last message; outside that window it requires a
// pre-approved message template and rejects the send. Matched by known Graph
// API error codes/wording — NOT yet confirmed against a real rejection (no
// bundled plugin has hit this path before ask-max). Adjust this pattern
// after the first live 24h-window failure if the actual wording differs.
const WINDOW_ERROR_PATTERN = /131047|131026|24\s*hour|outside.*(window|session)|re-?engagement/i;

export function isOutside24hWindowError(error: unknown): boolean {
  const text = error instanceof Error ? `${error.message} ${String(error.cause ?? "")}` : String(error);
  return WINDOW_ERROR_PATTERN.test(text);
}

export async function sendAskMaxMessage(params: {
  api: OpenClawPluginApi;
  target: PendingAskMaxTarget;
  text: string;
}): Promise<ProactiveSendResult> {
  const payload: ReplyPayload = { text: params.text };
  try {
    await deliverOutboundPayloads({
      cfg: params.api.config,
      channel: params.target.channel as DeliverOutboundPayloadsParams["channel"],
      to: params.target.to,
      accountId: params.target.accountId,
      threadId: params.target.threadId,
      payloads: [payload],
    });
    return { ok: true };
  } catch (error) {
    if (isOutside24hWindowError(error)) {
      return { ok: false, reason: "outside_24h_window", error };
    }
    return { ok: false, reason: "send_failed", error };
  }
}
