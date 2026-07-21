// Per-turn capture buffer for the response-audit plugin.
//
// agent_end's `messages: unknown[]` is explicitly not a stable plugin
// contract (see audit-log.ts in extensions/github-repo-report for the prior
// finding). So instead of parsing it, this module accumulates the pieces we
// need from earlier, typed hooks — before_agent_run (user prompt),
// after_tool_call (which tools actually ran), reply_payload_sending (the
// exact text delivered to the channel) — keyed by runId, and agent_end reads
// the accumulated record back out.
//
// Mirrors the insertion-ordered Map + prune-from-front pattern in
// extensions/github-repo-report/src/audit-log.ts (pruneStalePendingRecords).

export type CapturedTurn = {
  runId: string;
  prompt?: string;
  finalText: string;
  toolsExecuted: string[];
  sessionKey?: string;
  agentId?: string;
  channel?: string;
  chatId?: string;
  senderId?: string;
  startedAt: number;
};

const MAX_TURNS = 200;
const TURN_TTL_MS = 10 * 60_000;

const turns = new Map<string, CapturedTurn>();

function pruneStaleTurns(now: number): void {
  for (const [runId, turn] of turns) {
    if (now - turn.startedAt <= TURN_TTL_MS && turns.size <= MAX_TURNS) {
      break;
    }
    turns.delete(runId);
  }
}

function getOrCreateTurn(runId: string): CapturedTurn {
  const existing = turns.get(runId);
  if (existing) {
    return existing;
  }
  const now = Date.now();
  pruneStaleTurns(now);
  const created: CapturedTurn = {
    runId,
    finalText: "",
    toolsExecuted: [],
    startedAt: now,
  };
  turns.set(runId, created);
  return created;
}

export function rememberTurnPrompt(params: {
  runId: string;
  prompt: string;
  sessionKey?: string;
  agentId?: string;
  channel?: string;
  chatId?: string;
  senderId?: string;
}): void {
  const turn = getOrCreateTurn(params.runId);
  turn.prompt = params.prompt;
  turn.sessionKey = params.sessionKey;
  turn.agentId = params.agentId;
  turn.channel = params.channel;
  turn.chatId = params.chatId;
  turn.senderId = params.senderId;
}

export function rememberTurnToolExecuted(params: { runId: string; toolName: string }): void {
  const turn = getOrCreateTurn(params.runId);
  if (!turn.toolsExecuted.includes(params.toolName)) {
    turn.toolsExecuted.push(params.toolName);
  }
}

export function rememberTurnFinalText(params: { runId: string; text: string }): void {
  if (!params.text) {
    return;
  }
  const turn = getOrCreateTurn(params.runId);
  turn.finalText = turn.finalText ? `${turn.finalText}\n${params.text}` : params.text;
}

/** Reads and removes the captured record for a run. Call once per agent_end. */
export function takeCapturedTurn(runId: string): CapturedTurn | undefined {
  const turn = turns.get(runId);
  turns.delete(runId);
  return turn;
}

export function peekCapturedTurnCountForTest(): number {
  return turns.size;
}

export function clearCapturedTurnsForTest(): void {
  turns.clear();
}
