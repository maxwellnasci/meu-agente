// WhatsApp Cloud plugin module implements webhook behavior.
import type { IncomingMessage, ServerResponse } from "node:http";
import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import {
  createFixedWindowRateLimiter,
  readRequestBodyWithLimit,
} from "openclaw/plugin-sdk/webhook-ingress";
import { resolveWhatsAppCloudAppSecret, resolveWhatsAppCloudVerifyToken } from "./accounts.js";
import { parseWhatsAppCloudWebhookPayload } from "./inbound-parser.js";
import { dispatchWhatsAppCloudInboundEvent, type WhatsAppCloudChannelRuntime } from "./inbound.js";
import { normalizeWhatsAppCloudPhoneNumber } from "./phone.js";
import type { ResolvedWhatsAppCloudAccount } from "./types.js";
import { verifyWhatsAppCloudSignature } from "./webhook-signature.js";
import { handleWhatsAppCloudVerificationRequest } from "./webhook-verify.js";

const WEBHOOK_BODY_LIMIT_BYTES = 256 * 1024;
const WEBHOOK_BODY_TIMEOUT_MS = 10_000;

const rateLimiter = createFixedWindowRateLimiter({
  maxRequests: 30,
  windowMs: 60_000,
  maxTrackedKeys: 5_000,
});
const REPLAY_CACHE_TTL_MS = 10 * 60_000;
const REPLAY_CACHE_MAX_KEYS = 10_000;
const replayCache = new Map<string, number>();

type WhatsAppCloudWebhookLog = {
  info?: (message: string) => void;
  warn?: (message: string) => void;
  error?: (message: string) => void;
};

export type WhatsAppCloudWebhookHandlerParams = {
  cfg: OpenClawConfig;
  account: ResolvedWhatsAppCloudAccount;
  channelRuntime: WhatsAppCloudChannelRuntime;
  log?: WhatsAppCloudWebhookLog;
};

function headerValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function rateLimitKey(req: IncomingMessage): string {
  return req.socket?.remoteAddress ?? "unknown";
}

function rememberWebhookMessage(params: {
  accountId: string;
  messageId: string;
  now?: number;
}): boolean {
  const now = params.now ?? Date.now();
  for (const [key, expiresAt] of replayCache) {
    if (expiresAt > now && replayCache.size <= REPLAY_CACHE_MAX_KEYS) {
      break;
    }
    replayCache.delete(key);
  }
  const key = `${params.accountId}:${params.messageId}`;
  if ((replayCache.get(key) ?? 0) > now) {
    return false;
  }
  replayCache.set(key, now + REPLAY_CACHE_TTL_MS);
  return true;
}

export function resetWhatsAppCloudWebhookReplayCacheForTest(): void {
  replayCache.clear();
}

// Per-sender dispatch queue: serializes inbound dispatch calls for the same
// sender so a burst of quick follow-ups cannot make two dispatches for the
// same OpenClaw session run concurrently. Concurrent same-session dispatches
// each register their own `foregroundReplyFence` generation
// (`src/auto-reply/dispatch.ts` upstream), and the older one then waits in
// `shouldCancelForegroundReplyDelivery` for a newer generation that cannot
// itself start until the session's reply-run admission frees up — a
// deadlock, since only one turn runs per session at a time. See
// openclaw/openclaw#91914 (upstream, still open) and PROXIMOS_PASSOS.md.
// Different senders remain fully concurrent; only same-sender dispatches
// are chained.
const senderDispatchQueues = new Map<string, Promise<void>>();

/** Runs `task` after any prior queued task for the same `queueKey` settles. */
export function enqueueWhatsAppCloudSenderDispatch(
  queueKey: string,
  task: () => Promise<void>,
): void {
  const previous = senderDispatchQueues.get(queueKey) ?? Promise.resolve();
  const next = previous.catch(() => {}).then(task);
  senderDispatchQueues.set(queueKey, next);
  void next
    .catch(() => {})
    .finally(() => {
      if (senderDispatchQueues.get(queueKey) === next) {
        senderDispatchQueues.delete(queueKey);
      }
    });
}

export function resetWhatsAppCloudWebhookSenderQueueForTest(): void {
  senderDispatchQueues.clear();
}

function respondPlain(res: ServerResponse, statusCode: number, body = ""): void {
  res.statusCode = statusCode;
  res.setHeader("content-type", "text/plain; charset=utf-8");
  res.end(body);
}

export function createWhatsAppCloudWebhookHandler(params: WhatsAppCloudWebhookHandlerParams) {
  return async (req: IncomingMessage, res: ServerResponse) => {
    if (req.method === "GET") {
      const verifyToken = await resolveWhatsAppCloudVerifyToken(params.cfg, params.account);
      if (!verifyToken) {
        params.log?.warn?.("WhatsApp Cloud verifyToken is not configured or could not be resolved");
        respondPlain(res, 500, "Verify token not configured");
        return true;
      }
      handleWhatsAppCloudVerificationRequest({ req, res, verifyToken });
      return true;
    }

    if (req.method !== "POST") {
      respondPlain(res, 405, "Method not allowed");
      return true;
    }

    const key = rateLimitKey(req);
    if (rateLimiter.isRateLimited(key)) {
      params.log?.warn?.(`WhatsApp Cloud webhook rate limit exceeded for ${key}`);
      respondPlain(res, 429, "Rate limit exceeded");
      return true;
    }

    let rawBody: string;
    try {
      rawBody = await readRequestBodyWithLimit(req, {
        maxBytes: WEBHOOK_BODY_LIMIT_BYTES,
        timeoutMs: WEBHOOK_BODY_TIMEOUT_MS,
      });
    } catch {
      respondPlain(res, 400, "Invalid request body");
      return true;
    }

    const appSecret = await resolveWhatsAppCloudAppSecret(params.cfg, params.account);
    if (!appSecret) {
      params.log?.warn?.("WhatsApp Cloud appSecret is not configured or could not be resolved");
      respondPlain(res, 500, "App secret not configured");
      return true;
    }

    const signatureOk = verifyWhatsAppCloudSignature({
      signatureHeader: headerValue(req.headers["x-hub-signature-256"]),
      rawBody,
      appSecret,
    });
    if (!signatureOk) {
      params.log?.warn?.("WhatsApp Cloud webhook rejected invalid X-Hub-Signature-256");
      respondPlain(res, 403, "Invalid signature");
      return true;
    }

    let payload: unknown;
    try {
      payload = JSON.parse(rawBody);
    } catch {
      respondPlain(res, 400, "Invalid JSON body");
      return true;
    }

    const parsed = parseWhatsAppCloudWebhookPayload(payload);
    if (parsed.phoneNumberId && parsed.phoneNumberId !== params.account.phoneNumberId) {
      params.log?.warn?.("WhatsApp Cloud webhook rejected mismatched phone_number_id");
      respondPlain(res, 200);
      return true;
    }

    // Ack Meta immediately; process messages after responding so retries
    // caused by a slow agent turn cannot duplicate delivery.
    respondPlain(res, 200);

    for (const msg of parsed.messages) {
      if (
        !rememberWebhookMessage({
          accountId: params.account.accountId,
          messageId: msg.messageId,
        })
      ) {
        params.log?.warn?.(`WhatsApp Cloud webhook ignored replayed message ${msg.messageId}`);
        continue;
      }
      const queueKey = `${params.account.accountId}:${normalizeWhatsAppCloudPhoneNumber(msg.from)}`;
      enqueueWhatsAppCloudSenderDispatch(queueKey, () =>
        dispatchWhatsAppCloudInboundEvent({
          cfg: params.cfg,
          account: params.account,
          msg,
          channelRuntime: params.channelRuntime,
          log: params.log,
        }).catch((err: unknown) => {
          params.log?.error?.(
            `WhatsApp Cloud webhook dispatch failed: ${err instanceof Error ? err.message : String(err)}`,
          );
        }),
      );
    }

    return true;
  };
}
