// Composes the ask_orchestrator tool.
import type { OpenClawPluginApi } from "../api.js";
import { createAskOrchestratorTool } from "./ask-orchestrator-tool.js";

export function registerOrchestratorBridgePlugin(api: OpenClawPluginApi): void {
  api.registerTool(createAskOrchestratorTool(api));
}
