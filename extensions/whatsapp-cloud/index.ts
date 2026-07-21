// WhatsApp Cloud plugin entrypoint registers its OpenClaw integration.
import { defineBundledChannelEntry } from "openclaw/plugin-sdk/channel-entry-contract";

export default defineBundledChannelEntry({
  id: "whatsapp-cloud",
  name: "WhatsApp Cloud API",
  description: "Meta WhatsApp Cloud API (Graph API) channel plugin for OpenClaw.",
  importMetaUrl: import.meta.url,
  plugin: {
    specifier: "./channel-plugin-api.js",
    exportName: "whatsAppCloudPlugin",
  },
  runtime: {
    specifier: "./api.js",
    exportName: "setWhatsAppCloudRuntime",
  },
});
