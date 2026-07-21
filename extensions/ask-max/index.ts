// Ask Max plugin entrypoint registers its OpenClaw integration.
import { definePluginEntry } from "./api.js";
import { registerAskMaxPlugin } from "./src/plugin.js";

export default definePluginEntry({
  id: "ask-max",
  name: "Ask Max",
  description:
    "Lets the agent escalate a real doubt to the operator's WhatsApp instead of guessing, then routes the reply back to the original conversation.",
  register: registerAskMaxPlugin,
});
