import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OpenClawPluginApi, OpenClawPluginToolContext } from "../api.js";
import { createAskOrchestratorTool } from "./ask-orchestrator-tool.js";

const ORIGINAL_TOKEN = process.env.ORCHESTRATOR_API_TOKEN;

function fakeApi(pluginConfig: Record<string, unknown>): { api: OpenClawPluginApi; warn: ReturnType<typeof vi.fn> } {
  const warn = vi.fn();
  const api = {
    pluginConfig,
    logger: { warn, info: vi.fn(), error: vi.fn(), debug: vi.fn() },
  } as unknown as OpenClawPluginApi;
  return { api, warn };
}

const CTX = { deliveryContext: { channel: "whatsapp-cloud", to: "5541900000000" } } as OpenClawPluginToolContext;

function asFetch(mock: ReturnType<typeof vi.fn>): typeof fetch {
  return mock as unknown as typeof fetch;
}

describe("createAskOrchestratorTool", () => {
  beforeEach(() => {
    delete process.env.ORCHESTRATOR_API_TOKEN;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    if (ORIGINAL_TOKEN === undefined) {
      delete process.env.ORCHESTRATOR_API_TOKEN;
    } else {
      process.env.ORCHESTRATOR_API_TOKEN = ORIGINAL_TOKEN;
    }
  });

  it("sends Authorization: Bearer <token> when ORCHESTRATOR_API_TOKEN is set", async () => {
    process.env.ORCHESTRATOR_API_TOKEN = "secret-token-abc";
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ reply_text: "ola" }),
    }));
    vi.stubGlobal("fetch", asFetch(fetchMock));

    const { api } = fakeApi({ url: "http://orchestrator:8000/v1/turn" });
    const tool = createAskOrchestratorTool(api)(CTX);
    const result = await tool.execute("call-1", { task: "faz algo" });

    expect(result.details).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer secret-token-abc");
  });

  it("omits the Authorization header when ORCHESTRATOR_API_TOKEN is not set", async () => {
    delete process.env.ORCHESTRATOR_API_TOKEN;
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ reply_text: "ola" }),
    }));
    vi.stubGlobal("fetch", asFetch(fetchMock));

    const { api } = fakeApi({ url: "http://orchestrator:8000/v1/turn" });
    const tool = createAskOrchestratorTool(api)(CTX);
    await tool.execute("call-1", { task: "faz algo" });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("never logs the token, even on an error response", async () => {
    process.env.ORCHESTRATOR_API_TOKEN = "super-secret-value";
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 401,
      text: async () => "Unauthorized",
    }));
    vi.stubGlobal("fetch", asFetch(fetchMock));

    const { api, warn } = fakeApi({ url: "http://orchestrator:8000/v1/turn" });
    const tool = createAskOrchestratorTool(api)(CTX);
    const result = await tool.execute("call-1", { task: "faz algo" });

    expect(result.details).toEqual({ ok: false, status: 401 });
    expect(warn).toHaveBeenCalledTimes(1);
    const loggedMessage = warn.mock.calls[0]?.[0];
    expect(String(loggedMessage)).not.toContain("super-secret-value");
    // A resposta textual pro usuario tambem nao pode conter o token.
    const userText = result.content[0]?.text ?? "";
    expect(userText).not.toContain("super-secret-value");
  });

  it("never logs the token on a network failure (unreachable/timeout)", async () => {
    process.env.ORCHESTRATOR_API_TOKEN = "another-secret-value";
    const fetchMock = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    vi.stubGlobal("fetch", asFetch(fetchMock));

    const { api, warn } = fakeApi({ url: "http://orchestrator:8000/v1/turn" });
    const tool = createAskOrchestratorTool(api)(CTX);
    await tool.execute("call-1", { task: "faz algo" });

    expect(warn).toHaveBeenCalledTimes(1);
    const loggedMessage = warn.mock.calls[0]?.[0];
    expect(String(loggedMessage)).not.toContain("another-secret-value");
  });

  it("reports not_configured when the orchestrator URL is missing, regardless of token", async () => {
    process.env.ORCHESTRATOR_API_TOKEN = "secret-token-abc";
    const { api } = fakeApi({});
    const tool = createAskOrchestratorTool(api)(CTX);
    const result = await tool.execute("call-1", { task: "faz algo" });
    expect(result.details).toEqual({ ok: false, reason: "not_configured" });
  });
});
