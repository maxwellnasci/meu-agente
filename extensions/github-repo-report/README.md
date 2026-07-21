# GitHub Repo Report (plugin)

Narrow, read-only agent tool: fetches one allow-listed GitHub repository
(`https://github.com/maxwellnasci/<repo>`) via the GitHub REST tarball API
and returns a structured text report (file tree, sizes, README, manifest).

Runs entirely in the gateway/host process — never touches the Docker
sandbox, never opens a network exception in `sandbox.docker.network`. See
`docs/SESSAO_2026-07-15.md` in the `meu-agente` repo for the full
architecture investigation and design rationale.

## Design constraints

- **No free-text/command field.** `parameters` is `{ repo: enum, ref?:
  string }` — structurally impossible for the model to escalate this into
  arbitrary exec (`src/schema.ts`).
- **Closed repo enum.** `src/repo-registry.ts` is the single source of truth
  for which repos exist and which are `enabled`. Only `Mox---Sistemas` is
  enabled in the first test round; `meu-agente` and `arbo` are declared in
  the schema but blocked until manually enabled.
- **Trusted policy gate.** `src/policy.ts` auto-allows calls for enabled
  repos and requires manual approval for the rest — modeled on
  `src/skills/workshop/policy.ts` in core.
- **Defense in depth.** `src/tool.ts`'s `execute()` independently re-checks
  `isGithubRepoEnabled()` before running, even though the policy layer
  should already have blocked a disabled repo.
- **Async audit, never blocking.** `src/audit-log.ts` logs every request
  (allowed or requiring approval) via the `agent_end` hook — fire-and-forget,
  never `before_agent_finalize` — into the shared `state/openclaw.sqlite` via
  the official plugin KV API (`api.runtime.state.openKeyedStore`).

## Enable

1. Enable the plugin:

```json
{
  "plugins": {
    "entries": {
      "github-repo-report": { "enabled": true }
    }
  }
}
```

2. Allow the tool inside the sandbox (it is blocked by default —
   `DEFAULT_TOOL_ALLOW` in `src/agents/sandbox/constants.ts` only lists core
   built-ins):

```json
{
  "tools": {
    "sandbox": {
      "tools": {
        "alsoAllow": ["github_repo_report"]
      }
    }
  }
}
```

Not done yet in this repo's live `openclaw.json` — apply only after
reviewing/testing this plugin's code.

## Enabling more repos later

Edit `src/repo-registry.ts` and flip `enabled: true` for the repo you want
to allow. That is the only file that needs to change — schema, policy, and
tool all read from this registry.
