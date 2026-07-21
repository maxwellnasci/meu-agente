// WhatsApp Cloud plugin module implements gateway behavior.
import { waitUntilAbort } from "openclaw/plugin-sdk/channel-outbound";
import { registerPluginHttpRoute } from "openclaw/plugin-sdk/webhook-ingress";
import { isWhatsAppCloudAccountConfigured } from "./accounts.js";
import type { ResolvedWhatsAppCloudAccount } from "./types.js";
import { createWhatsAppCloudWebhookHandler, type WhatsAppCloudWebhookHandlerParams } from "./webhook.js";

const CHANNEL_ID = "whatsapp-cloud";
const WEBHOOK_PATH = "/webhook/whatsapp-cloud";

const activeRoutes = new Map<string, () => void>();

type WhatsAppCloudGatewayLog = {
  info?: (message: string) => void;
  warn?: (message: string) => void;
  error?: (message: string) => void;
};

export function collectWhatsAppCloudStartupWarnings(account: ResolvedWhatsAppCloudAccount): string[] {
  const warnings: string[] = [];
  if (!isWhatsAppCloudAccountConfigured(account)) {
    warnings.push(
      "- WhatsApp Cloud: phoneNumberId, appSecret, and accessToken are required.",
    );
  }
  if (!account.verifyToken) {
    warnings.push("- WhatsApp Cloud: verifyToken is required for the Meta webhook handshake.");
  }
  if (account.dmPolicy === "allowlist" && account.allowFrom.length === 0) {
    warnings.push("- WhatsApp Cloud: dmPolicy=allowlist with empty allowFrom rejects every sender.");
  }
  if (account.dmPolicy === "open" && !account.allowFrom.includes("*")) {
    warnings.push(
      '- WhatsApp Cloud: dmPolicy=open should set allowFrom=["*"] or explicit sender numbers.',
    );
  }
  return warnings;
}

export function registerWhatsAppCloudWebhookRoute(params: {
  cfg: WhatsAppCloudWebhookHandlerParams["cfg"];
  account: ResolvedWhatsAppCloudAccount;
  channelRuntime: WhatsAppCloudWebhookHandlerParams["channelRuntime"];
  log?: WhatsAppCloudGatewayLog;
}): () => void {
  activeRoutes.get(params.account.accountId)?.();
  const unregister = registerPluginHttpRoute({
    path: WEBHOOK_PATH,
    auth: "plugin",
    pluginId: CHANNEL_ID,
    accountId: params.account.accountId,
    log: (msg) => params.log?.info?.(msg),
    handler: createWhatsAppCloudWebhookHandler(params),
  });
  activeRoutes.set(params.account.accountId, unregister);
  return () => {
    unregister();
    activeRoutes.delete(params.account.accountId);
  };
}

export async function startWhatsAppCloudGatewayAccount(params: {
  cfg: WhatsAppCloudWebhookHandlerParams["cfg"];
  account: ResolvedWhatsAppCloudAccount;
  channelRuntime: WhatsAppCloudWebhookHandlerParams["channelRuntime"];
  abortSignal: AbortSignal;
  log?: WhatsAppCloudGatewayLog;
}) {
  if (!params.account.enabled) {
    params.log?.info?.(`WhatsApp Cloud account ${params.account.accountId} is disabled`);
    return waitUntilAbort(params.abortSignal);
  }
  const warnings = collectWhatsAppCloudStartupWarnings(params.account);
  if (warnings.some((warning) => warning.includes("required"))) {
    for (const warning of warnings) {
      params.log?.warn?.(warning);
    }
    return waitUntilAbort(params.abortSignal);
  }
  for (const warning of warnings) {
    params.log?.warn?.(warning);
  }
  const unregister = registerWhatsAppCloudWebhookRoute(params);
  params.log?.info?.(`Registered WhatsApp Cloud webhook route ${WEBHOOK_PATH} for account ${params.account.accountId}`);
  return waitUntilAbort(params.abortSignal, unregister);
}
