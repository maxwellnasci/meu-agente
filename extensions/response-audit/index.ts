// Response Audit plugin entrypoint registers its OpenClaw integration.
import { definePluginEntry } from "./api.js";
import { registerResponseAuditPlugin } from "./src/plugin.js";

export default definePluginEntry({
  id: "response-audit",
  name: "Response Audit",
  description:
    "Post-delivery check for functional hallucination, fabricated quotes, and falsely-declared actions in agent replies.",
  register: registerResponseAuditPlugin,
});
