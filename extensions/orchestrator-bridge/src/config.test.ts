import { afterEach, describe, expect, it } from "vitest";
import type { OpenClawPluginApi } from "../api.js";
import { resolveOrchestratorTarget, resolveOrchestratorToken } from "./config.js";

function fakeApi(pluginConfig: Record<string, unknown> | undefined): OpenClawPluginApi {
  return { pluginConfig } as OpenClawPluginApi;
}

const ORIGINAL_TOKEN = process.env.ORCHESTRATOR_API_TOKEN;

afterEach(() => {
  if (ORIGINAL_TOKEN === undefined) {
    delete process.env.ORCHESTRATOR_API_TOKEN;
  } else {
    process.env.ORCHESTRATOR_API_TOKEN = ORIGINAL_TOKEN;
  }
});

describe("resolveOrchestratorToken", () => {
  it("returns undefined when ORCHESTRATOR_API_TOKEN is unset", () => {
    delete process.env.ORCHESTRATOR_API_TOKEN;
    expect(resolveOrchestratorToken()).toBeUndefined();
  });

  it("returns undefined when ORCHESTRATOR_API_TOKEN is blank/whitespace", () => {
    process.env.ORCHESTRATOR_API_TOKEN = "   ";
    expect(resolveOrchestratorToken()).toBeUndefined();
  });

  it("returns the trimmed token when set", () => {
    process.env.ORCHESTRATOR_API_TOKEN = "  secret-token-123  ";
    expect(resolveOrchestratorToken()).toBe("secret-token-123");
  });
});

describe("resolveOrchestratorTarget", () => {
  afterEach(() => {
    delete process.env.ORCHESTRATOR_API_TOKEN;
  });

  it("returns null when pluginConfig is missing", () => {
    expect(resolveOrchestratorTarget(fakeApi(undefined))).toBeNull();
  });

  it("returns null when url is missing", () => {
    expect(resolveOrchestratorTarget(fakeApi({}))).toBeNull();
  });

  it("resolves url + default timeout without a token configured", () => {
    delete process.env.ORCHESTRATOR_API_TOKEN;
    expect(resolveOrchestratorTarget(fakeApi({ url: "http://orchestrator:8000/v1/turn" }))).toEqual({
      url: "http://orchestrator:8000/v1/turn",
      timeoutSeconds: 160,
      token: undefined,
    });
  });

  it("includes the token from env when configured, never from pluginConfig", () => {
    process.env.ORCHESTRATOR_API_TOKEN = "env-token";
    const target = resolveOrchestratorTarget(
      fakeApi({ url: "http://orchestrator:8000/v1/turn", token: "token-from-json-should-be-ignored" }),
    );
    expect(target?.token).toBe("env-token");
  });

  it("respects a custom timeoutSeconds", () => {
    expect(
      resolveOrchestratorTarget(fakeApi({ url: "http://orchestrator:8000/v1/turn", timeoutSeconds: 30 })),
    ).toEqual({ url: "http://orchestrator:8000/v1/turn", timeoutSeconds: 30, token: undefined });
  });
});
