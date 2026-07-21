// Audit trail for github_repo_report calls.
//
// The trusted policy (policy.ts) records every request attempt — allowed or
// requiring approval — into a small in-memory pending map, keyed by
// toolCallId. The agent_end hook below is fire-and-forget (never awaited in
// the reply path — confirmed in docs/SESSAO_2026-07-15.md by tracing
// src/agents/harness/agent-end-side-effects.ts), and flushes matching
// pending records into the shared state DB via the official plugin KV API
// (api.runtime.state.openKeyedStore, which physically writes into
// state/openclaw.sqlite) once the run finishes. This deliberately avoids
// parsing agent_end's opaque `messages: unknown[]` transcript, whose shape
// is not a stable plugin contract.
import type { OpenClawPluginApi } from "../api.js";

type AuditDecision = "auto-allow" | "require-approval" | "block";

type PendingAuditRecord = {
  runId?: string;
  toolCallId?: string;
  repo: string;
  ref?: string;
  decision: AuditDecision;
  sessionKey?: string;
  agentId?: string;
  requestedAt: number;
};

type StoredAuditRecord = PendingAuditRecord & {
  runSuccess?: boolean;
  runError?: string;
  flushedAt: number;
};

const MAX_PENDING_RECORDS = 200;
const PENDING_RECORD_TTL_MS = 10 * 60_000;

const pendingRecords = new Map<string, PendingAuditRecord>();

// Mirrors the replay-cache prune pattern in
// extensions/whatsapp-cloud/src/webhook.ts (rememberWebhookMessage):
// insertion-ordered Map, prune from the front until under the cap and TTL.
function pruneStalePendingRecords(now: number): void {
  for (const [key, record] of pendingRecords) {
    if (
      now - record.requestedAt <= PENDING_RECORD_TTL_MS &&
      pendingRecords.size <= MAX_PENDING_RECORDS
    ) {
      break;
    }
    pendingRecords.delete(key);
  }
}

export function rememberPendingGithubRepoReportAudit(record: PendingAuditRecord): void {
  pruneStalePendingRecords(record.requestedAt);
  const key = record.toolCallId ?? `${record.runId ?? "no-run"}:${record.requestedAt}`;
  pendingRecords.set(key, record);
}

export function peekPendingGithubRepoReportAuditCountForTest(): number {
  return pendingRecords.size;
}

export function clearPendingGithubRepoReportAuditForTest(): void {
  pendingRecords.clear();
}

const AUDIT_NAMESPACE = "github-repo-report-audit";
const AUDIT_MAX_ENTRIES = 5_000;

export function registerGithubRepoReportAuditHook(api: OpenClawPluginApi): void {
  api.on("agent_end", async (event, ctx) => {
    if (pendingRecords.size === 0 || !ctx.runId) {
      return;
    }
    const matches: Array<[string, PendingAuditRecord]> = [];
    for (const [key, record] of pendingRecords) {
      if (record.runId === ctx.runId) {
        matches.push([key, record]);
      }
    }
    if (matches.length === 0) {
      return;
    }
    const store = api.runtime.state.openKeyedStore<StoredAuditRecord>({
      namespace: AUDIT_NAMESPACE,
      maxEntries: AUDIT_MAX_ENTRIES,
    });
    for (const [key, record] of matches) {
      const stored: StoredAuditRecord = {
        ...record,
        runSuccess: event.success,
        runError: event.error,
        flushedAt: Date.now(),
      };
      try {
        await store.register(`${record.requestedAt}:${key}`, stripUndefinedValues(stored));
      } finally {
        pendingRecords.delete(key);
      }
    }
  });
}

// The plugin KV store requires every stored value to be JSON-serializable;
// an explicit `undefined` field (e.g. no `ref` was passed) fails that check
// even though JSON.stringify would silently drop it. Confirmed live during
// the "analisa o mox" test on 2026-07-15 — see docs/SESSAO_2026-07-15.md.
function stripUndefinedValues<T extends Record<string, unknown>>(obj: T): T {
  const result = {} as T;
  for (const [key, value] of Object.entries(obj)) {
    if (value !== undefined) {
      (result as Record<string, unknown>)[key] = value;
    }
  }
  return result;
}
