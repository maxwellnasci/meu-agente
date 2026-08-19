// WhatsApp Cloud plugin module implements inbound behavior.
import { resolveStableChannelMessageIngress } from "openclaw/plugin-sdk/channel-ingress-runtime";
import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import type { PluginRuntime } from "openclaw/plugin-sdk/plugin-runtime";
import { resolveWhatsAppCloudAccessToken } from "./accounts.js";
import { callOrchestratorTurn, OrchestratorClientError } from "./orchestrator-client.js";
import { normalizeWhatsAppCloudPhoneNumber, toWhatsAppCloudSendableNumber } from "./phone.js";
import { sendWhatsAppCloudTextChunks } from "./send.js";
import type { ResolvedWhatsAppCloudAccount, WhatsAppCloudInboundMessage } from "./types.js";

const CHANNEL_ID = "whatsapp-cloud";

// Shown to the user only when the Orchestrator itself is unreachable (down,
// network error, timeout) - the Orchestrator's own internal failures already
// come back as a reply_text, so this string never overlaps with that path.
const ORCHESTRATOR_UNREACHABLE_FALLBACK_TEXT =
  "Desculpa, tive um problema para processar sua mensagem agora. Tenta de novo em instantes.";

type WhatsAppCloudLog = {
  info?: (message: string) => void;
  warn?: (message: string) => void;
};

export type WhatsAppCloudChannelRuntime = Pick<PluginRuntime["channel"], "pairing" | "routing">;

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

  // Handoff to the Python Orchestrator (the "Cerebro"): it owns the agent
  // turn end-to-end and always resolves with reply text, so this call
  // replaces the internal OpenClaw agent pipeline for this channel.
  let replyText: string;
  try {
    const turn = await callOrchestratorTurn({
      sessionKey: route.sessionKey,
      text: params.msg.body,
      from,
    });
    replyText = turn.replyText;
  } catch (err) {
    const message = err instanceof OrchestratorClientError ? err.message : String(err);
    params.log?.warn?.(`Orchestrator turn failed for ${from}: ${message}`);
    replyText = ORCHESTRATOR_UNREACHABLE_FALLBACK_TEXT;
  }

  await sendWhatsAppCloudReply({
    cfg: params.cfg,
    account: params.account,
    to: toWhatsAppCloudSendableNumber(from),
    text: replyText,
  });
}
