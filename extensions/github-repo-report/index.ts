// GitHub Repo Report plugin entrypoint registers its OpenClaw integration.
import { definePluginEntry } from "./api.js";
import { registerGithubRepoReportPlugin } from "./src/plugin.js";

export default definePluginEntry({
  id: "github-repo-report",
  name: "GitHub Repo Report",
  description:
    "Fetches and summarizes one allow-listed GitHub repository (read-only, host-process only, never touches the sandbox).",
  register: registerGithubRepoReportPlugin,
});
