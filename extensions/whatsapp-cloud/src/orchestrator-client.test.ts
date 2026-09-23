// Cobre o envio de ORCHESTRATOR_API_TOKEN pelo cliente do Orquestrador:
// com token configurado, `callOrchestratorTurn` inclui
// `Authorization: Bearer <token>`; sem token (ausente/vazio), o header e
// omitido e a chamada segue sem autenticacao (o servidor decide: 401 com
// token ativo la, modo dev caso contrario).
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchWithSsrFGuard = vi.hoisted(() => vi.fn());

vi.mock("openclaw/plugin-sdk/ssrf-runtime", () => ({ fetchWithSsrFGuard }));

let callOrchestratorTurn: typeof import("./orchestrator-client.js").callOrchestratorTurn;
let resolveOrchestratorApiToken: typeof import("./orchestrator-client.js").resolveOrchestratorApiToken;

const TURN_REQUEST = { sessionKey: "sess-1", text: "oi", from: "5511999999999" };

function mockOkReply() {
  fetchWithSsrFGuard.mockResolvedValue({
    response: {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ reply_text: "ola" }),
    },
    release: async () => {},
  });
}

function sentHeaders(): Record<string, string> {
  const init = fetchWithSsrFGuard.mock.calls[0]?.[0]?.init as
    | { headers?: Record<string, string> }
    | undefined;
  return init?.headers ?? {};
}

beforeEach(async () => {
  vi.resetModules();
  fetchWithSsrFGuard.mockReset();
  mockOkReply();
  delete process.env.ORCHESTRATOR_API_TOKEN;
  ({ callOrchestratorTurn, resolveOrchestratorApiToken } = await import("./orchestrator-client.js"));
});

describe("resolveOrchestratorApiToken", () => {
  it("retorna o token quando configurado", () => {
    process.env.ORCHESTRATOR_API_TOKEN = "segredo-123";
    expect(resolveOrchestratorApiToken()).toBe("segredo-123");
  });

  it("retorna undefined quando ausente, vazio ou so espacos", () => {
    expect(resolveOrchestratorApiToken()).toBeUndefined();
    process.env.ORCHESTRATOR_API_TOKEN = "";
    expect(resolveOrchestratorApiToken()).toBeUndefined();
    process.env.ORCHESTRATOR_API_TOKEN = "   ";
    expect(resolveOrchestratorApiToken()).toBeUndefined();
  });
});

describe("callOrchestratorTurn auth header", () => {
  it("inclui Authorization: Bearer quando ORCHESTRATOR_API_TOKEN esta presente", async () => {
    process.env.ORCHESTRATOR_API_TOKEN = "segredo-123";
    const result = await callOrchestratorTurn(TURN_REQUEST);
    expect(result).toEqual({ replyText: "ola" });
    expect(sentHeaders()["authorization"]).toBe("Bearer segredo-123");
  });

  it("omite o header de autorizacao quando o token nao esta configurado", async () => {
    const result = await callOrchestratorTurn(TURN_REQUEST);
    expect(result).toEqual({ replyText: "ola" });
    expect(sentHeaders()).not.toHaveProperty("authorization");
  });

  it("omite o header de autorizacao quando o token esta vazio", async () => {
    process.env.ORCHESTRATOR_API_TOKEN = "";
    const result = await callOrchestratorTurn(TURN_REQUEST);
    expect(result).toEqual({ replyText: "ola" });
    expect(sentHeaders()).not.toHaveProperty("authorization");
  });
});

describe("callOrchestratorTurn status", () => {
  function mockHttpError(status: number, body: string) {
    fetchWithSsrFGuard.mockResolvedValue({
      response: {
        ok: false,
        status,
        text: async () => body,
      },
      release: async () => {},
    });
  }

  it("expoe status 401 quando o Orquestrador retorna 401", async () => {
    mockHttpError(401, "Unauthorized");
    const { OrchestratorClientError } = await import("./orchestrator-client.js");
    await expect(callOrchestratorTurn(TURN_REQUEST)).rejects.toMatchObject({
      name: "OrchestratorClientError",
      status: 401,
    });
    try {
      await callOrchestratorTurn(TURN_REQUEST);
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(OrchestratorClientError);
      expect((err as InstanceType<typeof OrchestratorClientError>).status).toBe(401);
    }
  });

  it("expoe status 403 quando o Orquestrador retorna 403", async () => {
    mockHttpError(403, "Forbidden");
    try {
      await callOrchestratorTurn(TURN_REQUEST);
      expect.unreachable();
    } catch (err) {
      const { OrchestratorClientError } = await import("./orchestrator-client.js");
      expect(err).toBeInstanceOf(OrchestratorClientError);
      expect((err as InstanceType<typeof OrchestratorClientError>).status).toBe(403);
    }
  });

  it("deixa status undefined em falha de rede", async () => {
    fetchWithSsrFGuard.mockRejectedValue(new Error("boom"));
    try {
      await callOrchestratorTurn(TURN_REQUEST);
      expect.unreachable();
    } catch (err) {
      const { OrchestratorClientError } = await import("./orchestrator-client.js");
      expect(err).toBeInstanceOf(OrchestratorClientError);
      expect((err as InstanceType<typeof OrchestratorClientError>).status).toBeUndefined();
    }
  });
});
