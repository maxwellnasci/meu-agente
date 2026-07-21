import { describe, expect, it } from "vitest";
import type { OpenClawPluginApi } from "../api.js";
import { resolveAskMaxTarget } from "./config.js";

function fakeApi(pluginConfig: Record<string, unknown> | undefined): OpenClawPluginApi {
  return { pluginConfig } as OpenClawPluginApi;
}

describe("resolveAskMaxTarget", () => {
  it("returns null when pluginConfig is missing", () => {
    expect(resolveAskMaxTarget(fakeApi(undefined))).toBeNull();
  });

  it("returns null when channel is missing", () => {
    expect(resolveAskMaxTarget(fakeApi({ to: "5541999999999" }))).toBeNull();
  });

  it("returns null when to is missing", () => {
    expect(resolveAskMaxTarget(fakeApi({ channel: "whatsapp-cloud" }))).toBeNull();
  });

  it("returns null when channel or to is blank", () => {
    expect(resolveAskMaxTarget(fakeApi({ channel: "  ", to: "5541999999999" }))).toBeNull();
  });

  it("resolves a minimal target without accountId", () => {
    expect(resolveAskMaxTarget(fakeApi({ channel: "whatsapp-cloud", to: "5541999999999" }))).toEqual({
      channel: "whatsapp-cloud",
      to: "5541999999999",
    });
  });

  it("includes accountId when present", () => {
    expect(
      resolveAskMaxTarget(
        fakeApi({ channel: "whatsapp-cloud", to: "5541999999999", accountId: "default" }),
      ),
    ).toEqual({ channel: "whatsapp-cloud", to: "5541999999999", accountId: "default" });
  });

  it("trims whitespace", () => {
    expect(
      resolveAskMaxTarget(fakeApi({ channel: " whatsapp-cloud ", to: " 5541999999999 " })),
    ).toEqual({
      channel: "whatsapp-cloud",
      to: "5541999999999",
    });
  });

  it("ignores non-string values", () => {
    expect(resolveAskMaxTarget(fakeApi({ channel: 123, to: "5541999999999" }))).toBeNull();
  });
});
