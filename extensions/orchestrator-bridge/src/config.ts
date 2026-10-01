// Resolves this plugin's own config (openclaw.json ->
// plugins.entries.orchestrator-bridge.config), never a value baked into
// source - same pattern as ask-max/src/config.ts.
import type { OpenClawPluginApi } from "../api.js";

export interface OrchestratorBridgeTarget {
  url: string;
  timeoutSeconds: number;
  token?: string;
}

const DEFAULT_TIMEOUT_SECONDS = 160;

// O token de autenticacao do orquestrador NAO entra no configSchema/
// openclaw.json de proposito: o orquestrador exige o MESMO valor em
// ORCHESTRATOR_API_TOKEN e falha fechado (401) sem ele - ver
// orchestrator/src/orchestrator/main.py:verify_api_token. Gravar o
// segredo no JSON duplicaria a superficie de vazamento (arquivo de
// config, backups, `openclaw doctor`, suporte) sem necessidade real: o
// valor so precisa existir no ambiente do processo do gateway (ver
// docker-compose.yml, environment.ORCHESTRATOR_API_TOKEN).
export function resolveOrchestratorToken(): string | undefined {
  return readNonEmptyString(process.env.ORCHESTRATOR_API_TOKEN);
}

export function resolveOrchestratorTarget(api: OpenClawPluginApi): OrchestratorBridgeTarget | null {
  const raw = api.pluginConfig;
  const url = readNonEmptyString(raw?.url);
  if (!url) {
    return null;
  }
  const timeoutSeconds = readPositiveNumber(raw?.timeoutSeconds) ?? DEFAULT_TIMEOUT_SECONDS;
  const token = resolveOrchestratorToken();
  return { url, timeoutSeconds, token };
}

function readNonEmptyString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function readPositiveNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : undefined;
}
