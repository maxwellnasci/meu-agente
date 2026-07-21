// WhatsApp Cloud plugin module parses Meta's inbound webhook payload.
import type { WhatsAppCloudInboundMessage } from "./types.js";

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function firstString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export type ParsedWhatsAppCloudWebhookPayload = {
  phoneNumberId: string | undefined;
  messages: WhatsAppCloudInboundMessage[];
};

/**
 * Meta batches text messages, delivery-status callbacks, and other change
 * types in the same payload shape. Non-text entries (statuses, reactions,
 * media without a text body) are silently skipped rather than treated as a
 * parse error, since Meta expects a 200 regardless.
 */
export function parseWhatsAppCloudWebhookPayload(body: unknown): ParsedWhatsAppCloudWebhookPayload {
  const messages: WhatsAppCloudInboundMessage[] = [];
  let phoneNumberId: string | undefined;

  if (!isRecord(body)) {
    return { phoneNumberId, messages };
  }

  for (const entry of asArray(body.entry)) {
    if (!isRecord(entry)) {
      continue;
    }
    for (const change of asArray(entry.changes)) {
      if (!isRecord(change) || change.field !== "messages") {
        continue;
      }
      const value = change.value;
      if (!isRecord(value)) {
        continue;
      }
      const metadata = value.metadata;
      if (isRecord(metadata)) {
        const id = firstString(metadata.phone_number_id);
        if (id) {
          phoneNumberId = id;
        }
      }
      for (const rawMessage of asArray(value.messages)) {
        if (!isRecord(rawMessage)) {
          continue;
        }
        if (rawMessage.type !== "text") {
          continue;
        }
        const text = rawMessage.text;
        const body = isRecord(text) ? firstString(text.body) : "";
        const from = firstString(rawMessage.from);
        const messageId = firstString(rawMessage.id);
        const timestampRaw = firstString(rawMessage.timestamp);
        if (!from || !messageId || !body) {
          continue;
        }
        messages.push({
          messageId,
          from,
          to: phoneNumberId ?? "",
          body,
          timestamp: timestampRaw ? Number(timestampRaw) * 1000 : Date.now(),
        });
      }
    }
  }

  return { phoneNumberId, messages };
}
