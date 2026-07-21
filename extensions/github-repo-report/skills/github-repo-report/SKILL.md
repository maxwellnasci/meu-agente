---
name: github-repo-report
description: Fetch and summarize one of Max's allow-listed GitHub repositories.
---

# GitHub Repo Report

Use the `github_repo_report` tool when Max asks about the contents,
structure, or code of one of his GitHub projects.

## Nicknames → real repo slugs

Max refers to his repos by short nicknames in conversation. Map them to the
exact `repo` value the tool expects (case-sensitive, must match exactly):

| Max says | Pass as `repo` |
|---|---|
| "mox" | `Mox---Sistemas` |
| "meu-agente" / "o agente" | `meu-agente` |
| "arbo" | `arbo` |

Do not guess other spellings ("Mox", "mox-sistemas", etc.) — the tool only
accepts the exact slugs above.

## What the tool returns

A single structured text report: file tree with sizes, plus the full content
of README/package.json/manifest files it finds. It does not execute any code
from the repo. Answer Max's question using the report contents — do not
speculate about files the report didn't include.

## Availability

Only `Mox---Sistemas` is enabled for real calls right now (first test round,
2026-07-15). Calling the tool with `meu-agente` or `arbo` will pause for
Max's manual approval instead of running automatically — that is expected,
not a bug. Tell Max the request needs his approval rather than retrying.
