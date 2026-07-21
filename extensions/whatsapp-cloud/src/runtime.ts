// WhatsApp Cloud plugin module implements runtime behavior.
import { createPluginRuntimeStore, type PluginRuntime } from "openclaw/plugin-sdk/runtime-store";

const { setRuntime: setWhatsAppCloudRuntime, getRuntime: getWhatsAppCloudRuntime } =
  createPluginRuntimeStore<PluginRuntime>({
    pluginId: "whatsapp-cloud",
    errorMessage: "WhatsApp Cloud runtime not initialized - plugin not registered",
  });

export { getWhatsAppCloudRuntime, setWhatsAppCloudRuntime };
