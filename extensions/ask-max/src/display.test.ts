import { describe, expect, it } from "vitest";
import type { OpenClawPluginApi } from "../api.js";
import { buildEscalationText } from "./ask-max-tool.js";
import {
  DEFAULT_ASSISTANT_NAME,
  DEFAULT_OPERATOR_NAME,
  resolveAskMaxDisplay,
} from "./config.js";

function fakeApi(pluginConfig: Record<string, unknown> | undefined): OpenClawPluginApi {
  return { pluginConfig } as OpenClawPluginApi;
}

describe("resolveAskMaxDisplay", () => {
  it("returns defaults when nothing is configured", () => {
    expect(resolveAskMaxDisplay(fakeApi(undefined))).toEqual({
      operatorName: DEFAULT_OPERATOR_NAME,
      assistantName: DEFAULT_ASSISTANT_NAME,
    });
  });

  it("resolves a custom operator name", () => {
    expect(resolveAskMaxDisplay(fakeApi({ operatorName: "Dra. Ana" })).operatorName).toBe("Dra. Ana");
  });

  it("resolves a custom assistant brand", () => {
    expect(resolveAskMaxDisplay(fakeApi({ assistantName: "ClinicaBot" })).assistantName).toBe("ClinicaBot");
  });

  it("falls back to defaults on blank values", () => {
    expect(resolveAskMaxDisplay(fakeApi({ operatorName: "  ", assistantName: "" }))).toEqual({
      operatorName: DEFAULT_OPERATOR_NAME,
      assistantName: DEFAULT_ASSISTANT_NAME,
    });
  });
});

describe("buildEscalationText", () => {
  it("addresses the configured operator and assistant brand", () => {
    const text = buildEscalationText({
      question: "Pode confirmar?",
      operatorName: "Carlos",
      assistantName: "SuporteBot",
    });
    expect(text).toContain("SuporteBot");
    expect(text).toContain("Carlos");
    expect(text).toContain("Pode confirmar?");
  });

  it("includes context when provided", () => {
    const text = buildEscalationText({
      question: "q",
      context: "cliente X",
      operatorName: "Max",
      assistantName: "Amigão",
    });
    expect(text).toContain("cliente X");
  });
});
