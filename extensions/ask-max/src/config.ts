// Resolves the fixed operator escalation target from this plugin's own
// config (openclaw.json -> plugins.entries.ask-max.config), never from a
// value baked into source — see openclaw/CLAUDE.md, Security/Release:
// "Never commit real phone numbers... live config".
import type { OpenClawPluginApi } from "../api.js";
import type { PendingAskMaxTarget } from "./store.js";

export function resolveAskMaxTarget(api: OpenClawPluginApi): PendingAskMaxTarget | null {
  const raw = api.pluginConfig;
  const channel = readNonEmptyString(raw?.channel);
  const to = readNonEmptyString(raw?.to);
  if (!channel || !to) {
    return null;
  }
  const accountId = readNonEmptyString(raw?.accountId);
  return accountId ? { channel, to, accountId } : { channel, to };
}

export type AskMaxDisplay = {
  operatorName: string;
  assistantName: string;
};

export const DEFAULT_OPERATOR_NAME = "Max";
export const DEFAULT_ASSISTANT_NAME = "Amigão";

export function resolveAskMaxDisplay(api: OpenClawPluginApi): AskMaxDisplay {
  const raw = api.pluginConfig;
  return {
    operatorName: readNonEmptyString(raw?.operatorName) ?? DEFAULT_OPERATOR_NAME,
    assistantName: readNonEmptyString(raw?.assistantName) ?? DEFAULT_ASSISTANT_NAME,
  };
}

function readNonEmptyString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}
