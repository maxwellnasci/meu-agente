// Fixed, closed parameter schema for github_repo_report — no free-text or
// command field, so the model cannot escalate this tool into arbitrary exec.
// Uses a flat string enum (not Type.Union([Type.Literal(...)])) because some
// providers reject anyOf in tool schemas — see root CLAUDE.md, Code section.
// The enum is built from the resolved plugin config (src/config.ts) at
// register() time, not a compile-time constant — see plugin.ts. An empty
// slugs list must never reach here: stringEnum([]) drops the `enum` field
// entirely and degrades to an unconstrained string (src/agents/schema/string-enum.ts).
import { stringEnum } from "openclaw/plugin-sdk/compat";
import { Type } from "typebox";

export function createGithubRepoReportSchema(slugs: readonly string[]) {
  return Type.Object(
    {
      repo: stringEnum(slugs, {
        description:
          "Repository to fetch and summarize. Only repos marked enabled in the plugin config actually run; the rest require manual approval.",
      }),
      ref: Type.Optional(
        Type.String({
          description:
            "Git ref (branch, tag, or commit) to fetch. Defaults to the repo's default branch.",
        }),
      ),
    },
    { additionalProperties: false },
  );
}
