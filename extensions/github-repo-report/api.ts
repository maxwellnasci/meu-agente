// GitHub Repo Report API module exposes the plugin public contract.
export {
  definePluginEntry,
  type AnyAgentTool,
  type OpenClawPluginApi,
  type PluginLogger,
} from "openclaw/plugin-sdk/plugin-entry";
export { resolvePreferredOpenClawTmpDir, type TempWorkspace } from "openclaw/plugin-sdk/temp-path";
