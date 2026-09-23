// WhatsApp Cloud plugin module calls the Python Orchestrator's synchronous
// `/v1/turn` endpoint, which owns the agent turn end-to-end and always
// resolves with a reply_text (it turns its own internal failures into a
// fallback message instead of an HTTP error - see orchestrator/src/orchestrator/main.py).
// This client only has to handle the case where the Orchestrator itself is
// unreachable (down, network error, timeout).
import { fetchWithSsrFGuard } from "openclaw/plugin-sdk/ssrf-runtime";

const DEFAULT_ORCHESTRATOR_URL = "http://host.docker.internal:8000";
// Slightly above the Orchestrator's own ORCHESTRATOR_TURN_TIMEOUT_SEC (default
// 90s, see orchestrator/src/orchestrator/config.py): the Orchestrator always
// resolves /v1/turn within its own timeout, so the client timeout only needs
// to cover network/process failures beyond that.
const DEFAULT_TURN_TIMEOUT_MS = 95_000;
const TURN_ENDPOINT_PATH = "/v1/turn";

export class OrchestratorClientError extends Error {
  readonly status?: number;
  constructor(message: string, options?: { cause?: unknown; status?: number }) {
    super(message, options);
    this.name = "OrchestratorClientError";
    this.status = options?.status;
  }
}

export type OrchestratorTurnRequest = {
  sessionKey: string;
  text: string;
  from: string;
};

export type OrchestratorTurnResult = {
  replyText: string;
};

function resolveOrchestratorBaseUrl(): string {
  return (process.env.ORCHESTRATOR_URL || DEFAULT_ORCHESTRATOR_URL).replace(/\/+$/, "");
}

function resolveOrchestratorTurnTimeoutMs(): number {
  const raw = process.env.ORCHESTRATOR_TURN_TIMEOUT_MS;
  const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_TURN_TIMEOUT_MS;
}

/**
 * Token de autenticacao do Orquestrador (ORCHESTRATOR_API_TOKEN). Deve ser
 * identico ao configurado no servidor Python (orchestrator/.env). Retorna
 * undefined quando ausente ou vazio - nesse caso o header e omitido e o
 * servidor decide (401 com token ativo la, modo dev sem autenticacao caso
 * contrario).
 */
export function resolveOrchestratorApiToken(env: NodeJS.ProcessEnv = process.env): string | undefined {
  const raw = env.ORCHESTRATOR_API_TOKEN;
  const token = raw?.trim();
  return token ? token : undefined;
}

function buildTurnHeaders(env: NodeJS.ProcessEnv = process.env): Record<string, string> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const token = resolveOrchestratorApiToken(env);
  if (token !== undefined) {
    headers["authorization"] = `Bearer ${token}`;
  }
  return headers;
}

function buildOrchestratorSsrFPolicy(baseUrl: string) {
  const hostname = new URL(baseUrl).hostname;
  return {
    hostnameAllowlist: [hostname],
    // The Orchestrator is a trusted internal sidecar service, typically
    // reached over localhost or a private network address.
    allowPrivateNetwork: true,
  };
}

/**
 * Sends one turn to the Orchestrator's `/v1/turn` endpoint and returns the
 * reply text it produced. Throws OrchestratorClientError only when the
 * Orchestrator itself could not be reached or returned a malformed response
 * - callers are expected to fall back to their own safe reply text in that
 * case, since the Orchestrator's own errors never reach this far (they are
 * already folded into `reply_text` before the HTTP 200).
 */
export async function callOrchestratorTurn(
  request: OrchestratorTurnRequest,
): Promise<OrchestratorTurnResult> {
  const baseUrl = resolveOrchestratorBaseUrl();
  const url = `${baseUrl}${TURN_ENDPOINT_PATH}`;

  let guarded: Awaited<ReturnType<typeof fetchWithSsrFGuard>> | undefined;
  let responseText: string;
  let responseOk: boolean;
  let responseStatus: number;
  try {
    guarded = await fetchWithSsrFGuard({
      url,
      init: {
        method: "POST",
        headers: buildTurnHeaders(),
        body: JSON.stringify({
          session_key: request.sessionKey,
          text: request.text,
          from: request.from,
        }),
        signal: AbortSignal.timeout(resolveOrchestratorTurnTimeoutMs()),
      },
      policy: buildOrchestratorSsrFPolicy(baseUrl),
      auditContext: "orchestrator-turn",
    });
    responseOk = guarded.response.ok;
    responseStatus = guarded.response.status;
    responseText = await guarded.response.text();
  } catch (err) {
    throw new OrchestratorClientError(`Failed to reach Orchestrator at ${url}`, { cause: err });
  } finally {
    await guarded?.release();
  }

  if (!responseOk) {
    throw new OrchestratorClientError(`Orchestrator returned ${responseStatus}: ${responseText}`, {
      status: responseStatus,
    });
  }

  let parsed: { reply_text?: unknown };
  try {
    parsed = JSON.parse(responseText) as { reply_text?: unknown };
  } catch (err) {
    throw new OrchestratorClientError("Orchestrator response was not valid JSON", { cause: err });
  }

  if (typeof parsed.reply_text !== "string" || !parsed.reply_text) {
    throw new OrchestratorClientError("Orchestrator response did not include a reply_text string");
  }

  return { replyText: parsed.reply_text };
}
