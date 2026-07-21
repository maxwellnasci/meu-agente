// WhatsApp Cloud helper module supports config schema behavior.
import {
  AllowFromListSchema,
  buildChannelConfigSchema,
  DmPolicySchema,
  requireOpenAllowFrom,
} from "openclaw/plugin-sdk/channel-config-primitives";
import { requireChannelOpenAllowFrom } from "openclaw/plugin-sdk/extension-shared";
import { buildSecretInputSchema } from "openclaw/plugin-sdk/secret-input";
import { z } from "zod";

const SecretInputSchema = buildSecretInputSchema();

const WhatsAppCloudAccountConfigSchema = z
  .object({
    name: z.string().optional(),
    enabled: z.boolean().optional(),
    phoneNumberId: z.string().optional(),
    verifyToken: SecretInputSchema.optional(),
    appSecret: SecretInputSchema.optional(),
    accessToken: SecretInputSchema.optional(),
    dmPolicy: DmPolicySchema.optional().default("allowlist"),
    allowFrom: AllowFromListSchema,
  })
  .strict()
  .superRefine((value, ctx) => {
    requireChannelOpenAllowFrom({
      channel: "whatsapp-cloud",
      policy: value.dmPolicy,
      allowFrom: value.allowFrom,
      ctx,
      requireOpenAllowFrom,
    });
  });

export const WhatsAppCloudConfigSchema = WhatsAppCloudAccountConfigSchema.extend({
  accounts: z.record(z.string(), WhatsAppCloudAccountConfigSchema.optional()).optional(),
  defaultAccount: z.string().optional(),
});

export const WhatsAppCloudChannelConfigSchema = buildChannelConfigSchema(
  WhatsAppCloudConfigSchema,
  {
    uiHints: {
      "": {
        label: "WhatsApp Cloud API",
        help: "Meta WhatsApp Cloud API (Graph API) channel configuration for inbound webhooks and outbound replies.",
      },
      phoneNumberId: {
        label: "Phone Number ID",
        help: "Meta Graph API phone_number_id for the WhatsApp Business number.",
      },
      verifyToken: {
        label: "Webhook Verify Token",
        help: "Shared secret used to validate Meta's webhook verification handshake (hub.verify_token).",
      },
      appSecret: {
        label: "App Secret",
        help: "Meta app secret used to validate the X-Hub-Signature-256 HMAC on inbound webhooks.",
      },
      accessToken: {
        label: "Access Token",
        help: "Meta Graph API access token used to send outbound WhatsApp messages.",
      },
      dmPolicy: {
        label: "WhatsApp DM Policy",
        help: 'Direct message access control ("allowlist" recommended). "open" requires channels["whatsapp-cloud"].allowFrom=["*"].',
      },
      allowFrom: {
        label: "WhatsApp Allow From",
        help: "Allowed sender phone numbers (digits only, no leading +), or * when dmPolicy is open.",
      },
    },
  },
);
