// Persistence for response-audit results — same KV pattern as
// extensions/github-repo-report/src/audit-log.ts: shared state DB via the
// official plugin KV API, namespace-scoped, JSON-serializable values only.
import type { OpenClawPluginApi } from "../api.js";
import type { AuditTriggerReason } from "./heuristic-filter.js";

export type AuditFlagCategory = "hallucination" | "fabricated_quote" | "false_action";

export type StoredAuditRecord = {
  runId: string;
  sessionKey?: string;
  agentId?: string;
  channel?: string;
  chatId?: string;
  prompt?: string;
  finalText: string;
  toolsExecuted: string[];
  triggerReasons: AuditTriggerReason[];
  flagged: boolean;
  category?: AuditFlagCategory;
  reason?: string;
  auditedAt: number;
};

const AUDIT_NAMESPACE = "amigao-audit";
const AUDIT_MAX_ENTRIES = 5_000;

export async function persistAuditResult(
  api: OpenClawPluginApi,
  record: StoredAuditRecord,
): Promise<void> {
  const store = api.runtime.state.openKeyedStore<StoredAuditRecord>({
    namespace: AUDIT_NAMESPACE,
    maxEntries: AUDIT_MAX_ENTRIES,
  });
  await store.register(`${record.auditedAt}:${record.runId}`, stripUndefinedValues(record));
}

// The plugin KV store requires JSON-serializable values with no explicit
// `undefined` fields (confirmed live in audit-log.ts's stripUndefinedValues —
// same failure mode applies here).
function stripUndefinedValues<T extends Record<string, unknown>>(obj: T): T {
  const result = {} as T;
  for (const [key, value] of Object.entries(obj)) {
    if (value !== undefined) {
      (result as Record<string, unknown>)[key] = value;
    }
  }
  return result;
}
