// WhatsApp Cloud plugin module implements channel behavior.
import {
  createHybridChannelConfigAdapter,
  createScopedDmSecurityResolver,
} from "openclaw/plugin-sdk/channel-config-helpers";
import { createChatChannelPlugin, type ChannelPlugin } from "openclaw/plugin-sdk/channel-core";
import {
  createMessageReceiptFromOutboundResults,
  defineChannelMessageAdapter,
} from "openclaw/plugin-sdk/channel-outbound";
import { createConditionalWarningCollector } from "openclaw/plugin-sdk/channel-policy";
import { createEmptyChannelDirectoryAdapter } from "openclaw/plugin-sdk/directory-runtime";
import {
  inspectWhatsAppCloudAccount,
  isWhatsAppCloudAccountConfigured,
  listWhatsAppCloudAccountIds,
  resolveDefaultWhatsAppCloudAccountId,
  resolveWhatsAppCloudAccessToken,
  resolveWhatsAppCloudAccount,
} from "./accounts.js";
import { WhatsAppCloudChannelConfigSchema } from "./config-schema.js";
import { collectWhatsAppCloudStartupWarnings, startWhatsAppCloudGatewayAccount } from "./gateway.js";
import type { WhatsAppCloudChannelRuntime } from "./inbound.js";
import {
  normalizeWhatsAppCloudAllowFrom,
  normalizeWhatsAppCloudPhoneNumber,
  toWhatsAppCloudSendableNumber,
} from "./phone.js";
import { sendWhatsAppCloudTextChunks, toWhatsAppCloudPlainText } from "./send.js";
import type { ResolvedWhatsAppCloudAccount } from "./types.js";

const CHANNEL_ID = "whatsapp-cloud";

const whatsAppCloudConfigAdapter = createHybridChannelConfigAdapter<ResolvedWhatsAppCloudAccount>({
  sectionKey: CHANNEL_ID,
  listAccountIds: listWhatsAppCloudAccountIds,
  resolveAccount: resolveWhatsAppCloudAccount,
  defaultAccountId: resolveDefaultWhatsAppCloudAccountId,
  clearBaseFields: [
    "phoneNumberId",
    "verifyToken",
    "appSecret",
    "accessToken",
    "dmPolicy",
    "allowFrom",
  ],
  resolveAllowFrom: (account) => account.allowFrom,
  formatAllowFrom: (allowFrom) => allowFrom.map((entry) => normalizeWhatsAppCloudAllowFrom(String(entry))),
});

const resolveWhatsAppCloudDmPolicy = createScopedDmSecurityResolver<ResolvedWhatsAppCloudAccount>({
  channelKey: CHANNEL_ID,
  resolvePolicy: (account) => account.dmPolicy,
  resolveAllowFrom: (account) => account.allowFrom,
  policyPathSuffix: "dmPolicy",
  defaultPolicy: "allowlist",
  approveHint: `Add the sender's phone number to channels.${CHANNEL_ID}.allowFrom`,
  normalizeEntry: normalizeWhatsAppCloudAllowFrom,
});

const collectWhatsAppCloudSecurityWarnings = createConditionalWarningCollector<ResolvedWhatsAppCloudAccount>(
  (account) =>
    account.dmPolicy === "open" &&
    account.allowFrom.includes("*") &&
    '- WhatsApp Cloud: dmPolicy="open" allows any phone number to message the bot.',
);

function createWhatsAppCloudReceipt(results: Array<{ messageId: string; to: string }>) {
  const first = results[0];
  if (!first) {
    throw new Error("WhatsApp Cloud send did not return a message id.");
  }
  return {
    channel: CHANNEL_ID,
    messageId: first.messageId,
    chatId: first.to,
    receipt: createMessageReceiptFromOutboundResults({
      results: results.map((result) => ({
        channel: CHANNEL_ID,
        messageId: result.messageId,
        chatId: result.to,
        toJid: result.to,
        conversationId: result.to,
      })),
      threadId: first.to,
      kind: "text" as const,
    }),
  };
}

async function sendWhatsAppCloudText(ctx: {
  cfg: import("openclaw/plugin-sdk/account-resolution").OpenClawConfig;
  accountId?: string | null;
  to: string;
  text: string;
}) {
  const account = resolveWhatsAppCloudAccount(ctx.cfg, ctx.accountId);
  const to = toWhatsAppCloudSendableNumber(ctx.to);
  if (!to) {
    throw new Error(`Invalid WhatsApp Cloud target: ${ctx.to}`);
  }
  const accessToken = await resolveWhatsAppCloudAccessToken(ctx.cfg, account);
  if (!accessToken) {
    throw new Error("WhatsApp Cloud accessToken is not configured or could not be resolved.");
  }
  const results = await sendWhatsAppCloudTextChunks({
    phoneNumberId: account.phoneNumberId,
    accessToken,
    to,
    text: ctx.text,
  });
  return createWhatsAppCloudReceipt(results);
}

const whatsAppCloudMessageAdapter = defineChannelMessageAdapter({
  id: CHANNEL_ID,
  durableFinal: {
    capabilities: {
      text: true,
      media: false,
      messageSendingHooks: true,
    },
  },
  send: {
    text: async (ctx) => await sendWhatsAppCloudText(ctx),
  },
});

export const whatsAppCloudPlugin: ChannelPlugin<ResolvedWhatsAppCloudAccount> =
  createChatChannelPlugin({
    base: {
      id: CHANNEL_ID,
      meta: {
        id: CHANNEL_ID,
        label: "WhatsApp Cloud API",
        selectionLabel: "WhatsApp (Cloud API)",
        detailLabel: "WhatsApp Cloud API (Meta Graph API)",
        docsPath: "/channels/whatsapp-cloud",
        docsLabel: "whatsapp-cloud",
        blurb: "Meta's official WhatsApp Business Cloud API, receiving inbound webhooks and replying via the Graph API.",
        order: 89,
      },
      capabilities: {
        chatTypes: ["direct"],
        media: false,
        threads: false,
        reactions: false,
        edit: false,
        unsend: false,
        reply: false,
        effects: false,
        blockStreaming: false,
      },
      reload: { configPrefixes: [`channels.${CHANNEL_ID}`] },
      configSchema: WhatsAppCloudChannelConfigSchema,
      config: {
        ...whatsAppCloudConfigAdapter,
        inspectAccount: inspectWhatsAppCloudAccount,
        isConfigured: isWhatsAppCloudAccountConfigured,
        unconfiguredReason: () =>
          "WhatsApp Cloud requires phoneNumberId, verifyToken, appSecret, and accessToken.",
        describeAccount: (account) => ({
          accountId: account.accountId,
          name: account.phoneNumberId || "WhatsApp Cloud",
          configured: isWhatsAppCloudAccountConfigured(account),
          enabled: account.enabled,
        }),
      },
      directory: createEmptyChannelDirectoryAdapter(),
      gateway: {
        startAccount: async (ctx) => {
          if (!ctx.channelRuntime) {
            ctx.log?.warn?.("WhatsApp Cloud channel runtime is not available; webhook route not started");
            return;
          }
          return await startWhatsAppCloudGatewayAccount({
            cfg: ctx.cfg,
            account: ctx.account,
            channelRuntime: ctx.channelRuntime as unknown as WhatsAppCloudChannelRuntime,
            abortSignal: ctx.abortSignal,
            log: ctx.log,
          });
        },
      },
      status: {
        buildAccountSnapshot: ({ account }) => {
          const configured = isWhatsAppCloudAccountConfigured(account);
          return {
            accountId: account.accountId,
            name: account.phoneNumberId || "WhatsApp Cloud",
            enabled: account.enabled,
            configured,
            statusState: !account.enabled ? "disabled" : configured ? "configured" : "unconfigured",
          };
        },
        buildCapabilitiesDiagnostics: async ({ account }) => ({
          lines: collectWhatsAppCloudStartupWarnings(account).map((text) => ({ text, tone: "warn" })),
        }),
      },
      agentPrompt: {
        messageToolHints: () => [
          "",
          "### WhatsApp Formatting",
          "WhatsApp supports limited formatting (*bold*, _italic_). Avoid markdown tables and keep replies concise.",
        ],
      },
      message: whatsAppCloudMessageAdapter,
    },
    security: {
      resolveDmPolicy: resolveWhatsAppCloudDmPolicy,
      collectWarnings: ({ account }) => collectWhatsAppCloudSecurityWarnings(account),
    },
    outbound: {
      deliveryMode: "gateway",
      chunkerMode: "text",
      textChunkLimit: 4096,
      resolveTarget: ({ cfg: _cfg, to }) => {
        const explicit = normalizeWhatsAppCloudPhoneNumber(to ?? "");
        if (explicit) {
          return { ok: true, to: explicit };
        }
        return { ok: false, error: new Error("WhatsApp Cloud target must be a phone number.") };
      },
      sanitizeText: ({ text }) => toWhatsAppCloudPlainText(text),
      sendText: sendWhatsAppCloudText,
    },
  });
