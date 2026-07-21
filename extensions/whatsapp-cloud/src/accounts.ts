// WhatsApp Cloud plugin module implements accounts behavior.
import { normalizeOptionalAccountId } from "openclaw/plugin-sdk/account-id";
import {
  DEFAULT_ACCOUNT_ID,
  listCombinedAccountIds,
  resolveAccountEntry,
  resolveListedDefaultAccountId,
  resolveMergedAccountConfig,
  type OpenClawConfig,
} from "openclaw/plugin-sdk/account-resolution";
import { resolveConfiguredSecretInputString } from "openclaw/plugin-sdk/secret-input-runtime";
import { normalizeStringEntries } from "openclaw/plugin-sdk/string-coerce-runtime";
import { normalizeWhatsAppCloudAllowFrom } from "./phone.js";
import type { ResolvedWhatsAppCloudAccount, WhatsAppCloudChannelConfig } from "./types.js";

const CHANNEL_ID = "whatsapp-cloud";

function getChannelConfig(cfg: OpenClawConfig): WhatsAppCloudChannelConfig | undefined {
  return cfg?.channels?.[CHANNEL_ID] as WhatsAppCloudChannelConfig | undefined;
}

function parseList(raw: unknown): string[] {
  if (!raw) {
    return [];
  }
  const entries = Array.isArray(raw)
    ? raw
    : typeof raw === "string"
      ? normalizeStringEntries(raw.split(","))
      : [raw];
  return entries.map((entry) => normalizeWhatsAppCloudAllowFrom(String(entry))).filter(Boolean);
}

function hasBaseAccount(channelCfg: WhatsAppCloudChannelConfig | undefined): boolean {
  return Boolean(channelCfg?.phoneNumberId || channelCfg?.accessToken);
}

export function listWhatsAppCloudAccountIds(cfg: OpenClawConfig): string[] {
  const channelCfg = getChannelConfig(cfg);
  return listCombinedAccountIds({
    configuredAccountIds: Object.keys(channelCfg?.accounts ?? {}),
    implicitAccountId: hasBaseAccount(channelCfg) ? DEFAULT_ACCOUNT_ID : undefined,
  });
}

export function resolveDefaultWhatsAppCloudAccountId(cfg: OpenClawConfig): string {
  const channelCfg = getChannelConfig(cfg);
  return resolveListedDefaultAccountId({
    accountIds: listWhatsAppCloudAccountIds(cfg),
    configuredDefaultAccountId: normalizeOptionalAccountId(channelCfg?.defaultAccount),
  });
}

export function resolveWhatsAppCloudAccount(
  cfg: OpenClawConfig,
  accountId?: string | null,
): ResolvedWhatsAppCloudAccount {
  const channelCfg = getChannelConfig(cfg) ?? {};
  const id = normalizeOptionalAccountId(accountId) ?? resolveDefaultWhatsAppCloudAccountId(cfg);
  const accountConfig = resolveAccountEntry(channelCfg.accounts, id);
  const channelConfig: Record<string, unknown> & WhatsAppCloudChannelConfig = { ...channelCfg };
  const accountEntries:
    | Record<string, Partial<Record<string, unknown> & WhatsAppCloudChannelConfig>>
    | undefined = channelCfg.accounts
    ? Object.fromEntries(
        Object.entries(channelCfg.accounts).map(([accountKey, account]) => [
          accountKey,
          { ...account },
        ]),
      )
    : undefined;
  const merged = resolveMergedAccountConfig<Record<string, unknown> & WhatsAppCloudChannelConfig>({
    channelConfig,
    accounts: accountEntries,
    accountId: id,
    omitKeys: ["defaultAccount"],
  });

  return {
    accountId: id,
    enabled: channelCfg.enabled !== false && accountConfig?.enabled !== false,
    phoneNumberId: String(merged.phoneNumberId ?? "").trim(),
    verifyToken: merged.verifyToken,
    appSecret: merged.appSecret,
    accessToken: merged.accessToken,
    dmPolicy: merged.dmPolicy ?? "allowlist",
    allowFrom: parseList(merged.allowFrom),
  };
}

export function isWhatsAppCloudAccountConfigured(account: ResolvedWhatsAppCloudAccount): boolean {
  return Boolean(account.phoneNumberId && account.accessToken && account.appSecret);
}

async function resolveWhatsAppCloudSecret(params: {
  cfg: OpenClawConfig;
  accountId: string;
  field: "verifyToken" | "appSecret" | "accessToken";
  value: ResolvedWhatsAppCloudAccount["verifyToken"];
}): Promise<string | undefined> {
  const path =
    params.accountId === DEFAULT_ACCOUNT_ID
      ? `channels.whatsapp-cloud.${params.field}`
      : `channels.whatsapp-cloud.accounts.${params.accountId}.${params.field}`;
  const resolved = await resolveConfiguredSecretInputString({
    config: params.cfg,
    env: process.env,
    value: params.value,
    path,
  });
  return resolved.value;
}

export async function resolveWhatsAppCloudVerifyToken(
  cfg: OpenClawConfig,
  account: ResolvedWhatsAppCloudAccount,
): Promise<string | undefined> {
  return await resolveWhatsAppCloudSecret({
    cfg,
    accountId: account.accountId,
    field: "verifyToken",
    value: account.verifyToken,
  });
}

export async function resolveWhatsAppCloudAppSecret(
  cfg: OpenClawConfig,
  account: ResolvedWhatsAppCloudAccount,
): Promise<string | undefined> {
  return await resolveWhatsAppCloudSecret({
    cfg,
    accountId: account.accountId,
    field: "appSecret",
    value: account.appSecret,
  });
}

export async function resolveWhatsAppCloudAccessToken(
  cfg: OpenClawConfig,
  account: ResolvedWhatsAppCloudAccount,
): Promise<string | undefined> {
  return await resolveWhatsAppCloudSecret({
    cfg,
    accountId: account.accountId,
    field: "accessToken",
    value: account.accessToken,
  });
}

export function inspectWhatsAppCloudAccount(cfg: OpenClawConfig, accountId?: string | null) {
  const account = resolveWhatsAppCloudAccount(cfg, accountId);
  return {
    enabled: account.enabled,
    configured: isWhatsAppCloudAccountConfigured(account),
    phoneNumberId: account.phoneNumberId,
  };
}
