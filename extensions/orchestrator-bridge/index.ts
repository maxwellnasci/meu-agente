// Orchestrator Bridge plugin entrypoint registers its OpenClaw integration.
import { definePluginEntry } from "./api.js";
import { registerOrchestratorBridgePlugin } from "./src/plugin.js";

export default definePluginEntry({
  id: "orchestrator-bridge",
  name: "Orchestrator Bridge",
  description:
    "Lets the agent delegate a task to the project's LangGraph orchestrator (n8n and Python/code automation specialists) via its /v1/turn API.",
  register: registerOrchestratorBridgePlugin,
});
