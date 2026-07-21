// WhatsApp Cloud plugin module implements inbound behavior.
import { resolveStableChannelMessageIngress } from "openclaw/plugin-sdk/channel-ingress-runtime";
import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import type { PluginRuntime } from "openclaw/plugin-sdk/plugin-runtime";
import { resolveWhatsAppCloudAccessToken } from "./accounts.js";
import { normalizeWhatsAppCloudPhoneNumber, toWhatsAppCloudSendableNumber } from "./phone.js";
import { sendWhatsAppCloudTextChunks } from "./send.js";
import type { ResolvedWhatsAppCloudAccount, WhatsAppCloudInboundMessage } from "./types.js";

const CHANNEL_ID = "whatsapp-cloud";

type WhatsAppCloudLog = {
  info?: (message: string) => void;
  warn?: (message: string) => void;
};

export type WhatsAppCloudChannelRuntime = Pick<
  PluginRuntime["channel"],
  "inbound" | "pairing" | "reply" | "routing" | "session"
>;

async function authorizeWhatsAppCloudSender(params: {
  cfg: OpenClawConfig;
  account: ResolvedWhatsAppCloudAccount;
  channelRuntime: WhatsAppCloudChannelRuntime;
  from: string;
}) {
  return await resolveStableChannelMessageIngress({
    channelId: CHANNEL_ID,
    accountId: params.account.accountId,
    cfg: params.cfg,
    identity: {
      key: "phone",
      entryIdPrefix: "whatsapp-cloud-entry",
    },
    readStoreAllowFrom: async () =>
      await params.channelRuntime.pairing.readAllowFromStore({
        channel: CHANNEL_ID,
        accountId: params.account.accountId,
      }),
    subject: { stableId: params.from },
    conversation: {
      kind: "direct",
      id: "direct",
    },
    event: { mayPair: false },
    dmPolicy: params.account.dmPolicy,
    allowFrom: params.account.allowFrom,
  });
}

async function sendWhatsAppCloudReply(params: {
  cfg: OpenClawConfig;
  account: ResolvedWhatsAppCloudAccount;
  to: string;
  text: string;
}): Promise<void> {
  const accessToken = await resolveWhatsAppCloudAccessToken(params.cfg, params.account);
  if (!accessToken) {
    throw new Error("WhatsApp Cloud accessToken is not configured or could not be resolved.");
  }
  await sendWhatsAppCloudTextChunks({
    phoneNumberId: params.account.phoneNumberId,
    accessToken,
    to: params.to,
    text: params.text,
  });
}

export async function dispatchWhatsAppCloudInboundEvent(params: {
  cfg: OpenClawConfig;
  account: ResolvedWhatsAppCloudAccount;
  msg: WhatsAppCloudInboundMessage;
  channelRuntime: WhatsAppCloudChannelRuntime;
  log?: WhatsAppCloudLog;
}): Promise<void> {
  const from = normalizeWhatsAppCloudPhoneNumber(params.msg.from);
  const auth = await authorizeWhatsAppCloudSender({
    cfg: params.cfg,
    account: params.account,
    channelRuntime: params.channelRuntime,
    from,
  });
  if (!auth.senderAccess.allowed) {
    params.log?.warn?.(`WhatsApp Cloud sender ${from} is not authorized`);
    return;
  }

  const route = params.channelRuntime.routing.resolveAgentRoute({
    cfg: params.cfg,
    channel: CHANNEL_ID,
    accountId: params.account.accountId,
    peer: {
      kind: "direct",
      id: from,
    },
  });
  const sessionKey = route.sessionKey;

  await params.channelRuntime.inbound.run({
    channel: CHANNEL_ID,
    accountId: params.account.accountId,
    raw: params.msg,
    adapter: {
      ingest: (msg) => ({
        id: msg.messageId,
        timestamp: msg.timestamp,
        rawText: msg.body,
        textForAgent: msg.body,
        textForCommands: msg.body,
        raw: msg,
      }),
      resolveTurn: async (input) => {
        const ctxPayload = params.channelRuntime.inbound.buildContext({
          channel: CHANNEL_ID,
          accountId: params.account.accountId,
          timestamp: input.timestamp,
          from: `whatsapp-cloud:${from}`,
          sender: {
            id: from,
            name: from,
          },
          conversation: {
            kind: "direct",
            id: from,
            label: from,
          },
          route: {
            agentId: route.agentId,
            accountId: params.account.accountId,
            routeSessionKey: sessionKey,
            dispatchSessionKey: sessionKey,
          },
          reply: {
            to: `whatsapp-cloud:${from}`,
          },
          message: {
            rawBody: input.rawText,
            commandBody: input.textForCommands,
            bodyForAgent: input.textForAgent,
          },
          extra: {
            MessageId: params.msg.messageId,
            To: params.msg.to,
          },
        });
        const storePath = params.channelRuntime.session.resolveStorePath(
          params.cfg.session?.store,
          {
            agentId: route.agentId,
          },
        );
        return {
          cfg: params.cfg,
          channel: CHANNEL_ID,
          accountId: params.account.accountId,
          agentId: route.agentId,
          routeSessionKey: sessionKey,
          storePath,
          ctxPayload,
          recordInboundSession: params.channelRuntime.session.recordInboundSession,
          dispatchReplyWithBufferedBlockDispatcher:
            params.channelRuntime.reply.dispatchReplyWithBufferedBlockDispatcher,
          delivery: {
            deliver: async (payload) => {
              const text = payload.text;
              if (!text) {
                return { visibleReplySent: false };
              }
              await sendWhatsAppCloudReply({
                cfg: params.cfg,
                account: params.account,
                to: toWhatsAppCloudSendableNumber(from),
                text,
              });
              return { visibleReplySent: true };
            },
          },
          dispatcherOptions: {
            onReplyStart: () => {
              params.log?.info?.(`WhatsApp Cloud reply started for ${from}`);
            },
          },
        };
      },
    },
  });
}
