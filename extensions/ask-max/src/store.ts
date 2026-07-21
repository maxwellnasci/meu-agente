// Persistence for the single in-flight ask-max escalation — same KV pattern
// as extensions/response-audit/src/audit-store.ts: shared state DB via the
// official plugin KV API, namespace-scoped, JSON-serializable values only.
// Backed by SQLite (not an in-memory map) on purpose: the operator may take
// a while to reply, and the gateway process itself is not guaranteed to stay
// up in the meantime (see docs/SESSAO_2026-07-18.md — a ~9h gap from the
// notebook being powered off happened the same day this was designed).
import type { OpenClawPluginApi } from "../api.js";

export type PendingAskMaxTarget = {
  channel: string;
  to: string;
  accountId?: string;
  threadId?: string | number;
};

export type PendingAskMaxRecord = {
  question: string;
  context?: string;
  askedAt: number;
  /** Where the original question came from — where the eventual answer must be routed back to. */
  origin: PendingAskMaxTarget;
};

const ASK_MAX_NAMESPACE = "amigao-ask-max";
const ASK_MAX_MAX_ENTRIES = 4;
const PENDING_KEY = "pending";

function askMaxStore(api: OpenClawPluginApi) {
  return api.runtime.state.openKeyedStore<PendingAskMaxRecord>({
    namespace: ASK_MAX_NAMESPACE,
    maxEntries: ASK_MAX_MAX_ENTRIES,
  });
}

/**
 * Atomically creates the pending record only if none exists yet. This is
 * what enforces "one question at a time" without a separate check-then-set
 * race window.
 */
export async function tryCreatePendingAskMax(
  api: OpenClawPluginApi,
  record: PendingAskMaxRecord,
): Promise<boolean> {
  return await askMaxStore(api).registerIfAbsent(PENDING_KEY, stripUndefinedValues(record));
}

/** Atomically reads and clears the pending record — used once the operator answers. */
export async function consumePendingAskMax(
  api: OpenClawPluginApi,
): Promise<PendingAskMaxRecord | undefined> {
  return await askMaxStore(api).consume(PENDING_KEY);
}

// The plugin KV store requires JSON-serializable values with no explicit
// `undefined` fields (confirmed live in github-repo-report's audit-log.ts;
// same failure mode applies here). Recursive because `origin` is nested.
function stripUndefinedValues<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((item) => stripUndefinedValues(item)) as unknown as T;
  }
  if (value && typeof value === "object") {
    const result: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      if (entry !== undefined) {
        result[key] = stripUndefinedValues(entry);
      }
    }
    return result as T;
  }
  return value;
}
