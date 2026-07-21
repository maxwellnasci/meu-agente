// Fixed, closed parameter schema for github_repo_report — no free-text or
// command field, so the model cannot escalate this tool into arbitrary exec.
// Uses a flat string enum (not Type.Union([Type.Literal(...)])) because some
// providers reject anyOf in tool schemas — see root CLAUDE.md, Code section.
import { stringEnum } from "openclaw/plugin-sdk/compat";
import { Type } from "typebox";
import { GITHUB_REPO_SLUGS } from "./repo-registry.js";

export const GithubRepoReportSchema = Type.Object(
  {
    repo: stringEnum(GITHUB_REPO_SLUGS, {
      description:
        "Repository to fetch and summarize. Only repos marked enabled in repo-registry.ts actually run; the rest require manual approval.",
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
