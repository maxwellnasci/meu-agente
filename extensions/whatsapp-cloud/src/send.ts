// WhatsApp Cloud plugin module implements outbound send behavior via the Graph API.
import { chunkTextForOutbound, stripMarkdown } from "openclaw/plugin-sdk/text-chunking";
import { fetchWithSsrFGuard } from "openclaw/plugin-sdk/ssrf-runtime";
import type { WhatsAppCloudSendResult } from "./types.js";

const GRAPH_API_HOSTNAME = "graph.facebook.com";
const GRAPH_API_VERSION = "v21.0";
const GRAPH_API_TIMEOUT_MS = 30_000;
const TEXT_CHUNK_LIMIT = 4096;

export class WhatsAppCloudApiError extends Error {
  readonly httpStatus: number;
  readonly responseText: string;

  constructor(httpStatus: number, responseText: string) {
    super(`WhatsApp Cloud API send failed (${httpStatus}): ${responseText || "unknown"}`);
    this.name = "WhatsAppCloudApiError";
    this.httpStatus = httpStatus;
    this.responseText = responseText;
  }
}

export function toWhatsAppCloudPlainText(text: string): string {
  return stripMarkdown(text).replace(/\r\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}

async function sendOneWhatsAppCloudMessage(params: {
  phoneNumberId: string;
  accessToken: string;
  to: string;
  text: string;
  fetchImpl?: typeof fetch;
}): Promise<WhatsAppCloudSendResult> {
  const url = `https://${GRAPH_API_HOSTNAME}/${GRAPH_API_VERSION}/${encodeURIComponent(params.phoneNumberId)}/messages`;
  const init = {
    method: "POST",
    headers: {
      authorization: `Bearer ${params.accessToken}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      messaging_product: "whatsapp",
      to: params.to,
      text: { body: params.text },
    }),
  } satisfies RequestInit;

  let response: { ok: boolean; status: number; text: string };
  if (params.fetchImpl) {
    const raw = await params.fetchImpl(url, init);
    response = { ok: raw.ok, status: raw.status, text: await raw.text() };
  } else {
    const guarded = await fetchWithSsrFGuard({
      url,
      init,
      auditContext: "whatsapp-cloud-graph-api",
      policy: { allowedHostnames: [GRAPH_API_HOSTNAME] },
      requireHttps: true,
      timeoutMs: GRAPH_API_TIMEOUT_MS,
    });
    try {
      response = {
        ok: guarded.response.ok,
        status: guarded.response.status,
        text: await guarded.response.text(),
      };
    } finally {
      await guarded.release();
    }
  }

  if (!response.ok) {
    throw new WhatsAppCloudApiError(response.status, response.text);
  }

  const parsed = JSON.parse(response.text) as {
    messages?: Array<{ id?: string }>;
  };
  const messageId = parsed.messages?.[0]?.id;
  if (!messageId) {
    throw new WhatsAppCloudApiError(response.status, "Response did not include a message id.");
  }
  return { messageId, to: params.to };
}

export async function sendWhatsAppCloudTextChunks(params: {
  phoneNumberId: string;
  accessToken: string;
  to: string;
  text: string;
  fetchImpl?: typeof fetch;
}): Promise<WhatsAppCloudSendResult[]> {
  const text = toWhatsAppCloudPlainText(params.text);
  if (!text) {
    throw new Error("WhatsApp Cloud send requires non-empty text.");
  }
  const chunks = chunkTextForOutbound(text, TEXT_CHUNK_LIMIT).filter(Boolean);
  const sendChunks = chunks.length ? chunks : [text];
  const results: WhatsAppCloudSendResult[] = [];
  for (const chunk of sendChunks) {
    results.push(
      await sendOneWhatsAppCloudMessage({
        phoneNumberId: params.phoneNumberId,
        accessToken: params.accessToken,
        to: params.to,
        text: chunk,
        fetchImpl: params.fetchImpl,
      }),
    );
  }
  return results;
}
