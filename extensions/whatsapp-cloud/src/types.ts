// WhatsApp Cloud type declarations define plugin contracts.
import type { SecretInput } from "openclaw/plugin-sdk/secret-input";

export type WhatsAppCloudConfigFields = {
  enabled?: boolean;
  phoneNumberId?: string;
  verifyToken?: SecretInput;
  appSecret?: SecretInput;
  accessToken?: SecretInput;
  dmPolicy?: "pairing" | "open" | "allowlist" | "disabled";
  allowFrom?: string | Array<string | number>;
};

export interface WhatsAppCloudChannelConfig extends WhatsAppCloudConfigFields {
  accounts?: Record<string, WhatsAppCloudAccountRaw>;
  defaultAccount?: string;
}

export interface WhatsAppCloudAccountRaw extends WhatsAppCloudConfigFields {}

export interface ResolvedWhatsAppCloudAccount {
  accountId: string;
  enabled: boolean;
  phoneNumberId: string;
  /** Unresolved: may be a plain string or a SecretRef. Resolve with resolveWhatsAppCloudSecret(). */
  verifyToken: SecretInput | undefined;
  appSecret: SecretInput | undefined;
  accessToken: SecretInput | undefined;
  dmPolicy: "pairing" | "open" | "allowlist" | "disabled";
  allowFrom: string[];
}

export interface WhatsAppCloudInboundMessage {
  messageId: string;
  from: string;
  to: string;
  body: string;
  timestamp: number;
}

export type WhatsAppCloudSendResult = {
  messageId: string;
  to: string;
};
