// Composes the ask_max tool and its resolve hook.
import type { OpenClawPluginApi } from "../api.js";
import { createAskMaxTool } from "./ask-max-tool.js";
import { registerAskMaxResolveHook } from "./resolve-hook.js";

export function registerAskMaxPlugin(api: OpenClawPluginApi): void {
  api.registerTool(createAskMaxTool(api));
  registerAskMaxResolveHook(api);
}
