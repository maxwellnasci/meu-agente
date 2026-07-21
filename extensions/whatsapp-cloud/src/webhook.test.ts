import type { IncomingMessage, ServerResponse } from "node:http";
// WhatsApp Cloud tests cover webhook handler behavior, including the
// per-sender dispatch queue that guards against openclaw/openclaw#91914.
import { Readable } from "node:stream";
import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { WhatsAppCloudChannelRuntime } from "./inbound.js";
import type { ResolvedWhatsAppCloudAccount } from "./types.js";

const dispatchWhatsAppCloudInboundEvent = vi.hoisted(() => vi.fn());
const resolveWhatsAppCloudAppSecret = vi.hoisted(() => vi.fn(async () => "test-secret"));
const resolveWhatsAppCloudVerifyToken = vi.hoisted(() => vi.fn(async () => "verify-token"));
const verifyWhatsAppCloudSignature = vi.hoisted(() => vi.fn(() => true));

vi.mock("./inbound.js", () => ({ dispatchWhatsAppCloudInboundEvent }));
vi.mock("./accounts.js", () => ({
  resolveWhatsAppCloudAppSecret,
  resolveWhatsAppCloudVerifyToken,
}));
vi.mock("./webhook-signature.js", () => ({ verifyWhatsAppCloudSignature }));

let createWhatsAppCloudWebhookHandler: typeof import("./webhook.js").createWhatsAppCloudWebhookHandler;
let enqueueWhatsAppCloudSenderDispatch: typeof import("./webhook.js").enqueueWhatsAppCloudSenderDispatch;
let resetWhatsAppCloudWebhookReplayCacheForTest: typeof import("./webhook.js").resetWhatsAppCloudWebhookReplayCacheForTest;
let resetWhatsAppCloudWebhookSenderQueueForTest: typeof import("./webhook.js").resetWhatsAppCloudWebhookSenderQueueForTest;

beforeAll(async () => {
  ({
    createWhatsAppCloudWebhookHandler,
    enqueueWhatsAppCloudSenderDispatch,
    resetWhatsAppCloudWebhookReplayCacheForTest,
    resetWhatsAppCloudWebhookSenderQueueForTest,
  } = await import("./webhook.js"));
});

const PHONE_NUMBER_ID = "1138532409351860";
const ACCOUNT: ResolvedWhatsAppCloudAccount = {
  accountId: "default",
  enabled: true,
  phoneNumberId: PHONE_NUMBER_ID,
  verifyToken: undefined,
  appSecret: undefined,
  accessToken: undefined,
  dmPolicy: "open",
  allowFrom: [],
};
const CFG = {} as OpenClawConfig;
const CHANNEL_RUNTIME = {} as WhatsAppCloudChannelRuntime;

function textMessagePayload(params: { from: string; id: string; body?: string }) {
  return {
    object: "whatsapp_business_account",
    entry: [
      {
        id: "waba-id",
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: { phone_number_id: PHONE_NUMBER_ID },
              contacts: [{ profile: { name: "Test" }, wa_id: params.from }],
              messages: [
                {
                  from: params.from,
                  id: params.id,
                  timestamp: "1752480000",
                  type: "text",
                  text: { body: params.body ?? "oi" },
                },
              ],
            },
          },
        ],
      },
    ],
  };
}

function fakeReq(body: unknown): IncomingMessage {
  const raw = JSON.stringify(body);
  const stream = Readable.from([Buffer.from(raw, "utf-8")]);
  return Object.assign(stream, {
    method: "POST",
    headers: { "x-hub-signature-256": "sha256=irrelevant-mocked" },
    socket: { remoteAddress: "203.0.113.10" },
  }) as unknown as IncomingMessage;
}

function fakeRes(): ServerResponse & { statusCode: number; body: string } {
  const res = {
    statusCode: 0,
    body: "",
    setHeader() {},
    end(chunk?: string) {
      res.body = chunk ?? "";
    },
  };
  return res as unknown as ServerResponse & { statusCode: number; body: string };
}

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

/** Lets pending microtasks (queue chaining, mock async calls) settle before asserting. */
function flushAsync(): Promise<void> {
  return new Promise((resolve) => {
    setImmediate(resolve);
  });
}

describe("enqueueWhatsAppCloudSenderDispatch", () => {
  beforeEach(() => {
    resetWhatsAppCloudWebhookSenderQueueForTest();
  });

  it("runs tasks for the same key strictly in sequence", async () => {
    const order: string[] = [];
    const first = deferred();
    const second = deferred();

    enqueueWhatsAppCloudSenderDispatch("same-key", async () => {
      order.push("first-start");
      await first.promise;
      order.push("first-end");
    });
    enqueueWhatsAppCloudSenderDispatch("same-key", async () => {
      order.push("second-start");
      await second.promise;
      order.push("second-end");
    });

    await flushAsync();
    // The second task must not have started while the first is still pending.
    expect(order).toEqual(["first-start"]);

    first.resolve();
    await flushAsync();
    await flushAsync();
    expect(order).toEqual(["first-start", "first-end", "second-start"]);

    second.resolve();
    await flushAsync();
    expect(order).toEqual(["first-start", "first-end", "second-start", "second-end"]);
  });

  it("runs tasks for different keys concurrently", async () => {
    const order: string[] = [];
    const a = deferred();
    const b = deferred();

    enqueueWhatsAppCloudSenderDispatch("key-a", async () => {
      order.push("a-start");
      await a.promise;
      order.push("a-end");
    });
    enqueueWhatsAppCloudSenderDispatch("key-b", async () => {
      order.push("b-start");
      await b.promise;
      order.push("b-end");
    });

    await flushAsync();
    // Both must have started even though neither has resolved yet.
    expect(order).toEqual(["a-start", "b-start"]);

    a.resolve();
    b.resolve();
    await flushAsync();
    await flushAsync();
    expect(order).toContain("a-end");
    expect(order).toContain("b-end");
  });

  it("does not let a rejected task block later tasks for the same key", async () => {
    const order: string[] = [];

    enqueueWhatsAppCloudSenderDispatch("same-key", async () => {
      order.push("first");
      throw new Error("boom");
    });
    enqueueWhatsAppCloudSenderDispatch("same-key", async () => {
      order.push("second");
    });

    await flushAsync();
    await flushAsync();
    expect(order).toEqual(["first", "second"]);
  });
});

describe("createWhatsAppCloudWebhookHandler", () => {
  beforeEach(() => {
    dispatchWhatsAppCloudInboundEvent.mockReset();
    resetWhatsAppCloudWebhookReplayCacheForTest();
    resetWhatsAppCloudWebhookSenderQueueForTest();
  });

  it("acks Meta immediately without waiting for dispatch to settle", async () => {
    const gate = deferred();
    dispatchWhatsAppCloudInboundEvent.mockImplementation(async () => {
      await gate.promise;
    });
    const handler = createWhatsAppCloudWebhookHandler({
      cfg: CFG,
      account: ACCOUNT,
      channelRuntime: CHANNEL_RUNTIME,
    });

    const res = fakeRes();
    await handler(fakeReq(textMessagePayload({ from: "5511900000001", id: "wamid-1" })), res);

    expect(res.statusCode).toBe(200);
    gate.resolve();
  });

  it("serializes dispatch calls for the same sender across separate requests", async () => {
    const order: string[] = [];
    const first = deferred();
    dispatchWhatsAppCloudInboundEvent.mockImplementation(
      async (params: { msg: { messageId: string } }) => {
        order.push(`start-${params.msg.messageId}`);
        if (params.msg.messageId === "wamid-1") {
          await first.promise;
        }
        order.push(`end-${params.msg.messageId}`);
      },
    );
    const handler = createWhatsAppCloudWebhookHandler({
      cfg: CFG,
      account: ACCOUNT,
      channelRuntime: CHANNEL_RUNTIME,
    });

    await handler(fakeReq(textMessagePayload({ from: "5511900000001", id: "wamid-1" })), fakeRes());
    await handler(fakeReq(textMessagePayload({ from: "5511900000001", id: "wamid-2" })), fakeRes());

    await flushAsync();
    await flushAsync();
    // The second message from the same sender must not start until the
    // first one's dispatch has fully settled.
    expect(order).toEqual(["start-wamid-1"]);

    first.resolve();
    await flushAsync();
    await flushAsync();
    expect(order).toEqual(["start-wamid-1", "end-wamid-1", "start-wamid-2", "end-wamid-2"]);
  });

  it("dispatches different senders concurrently", async () => {
    const order: string[] = [];
    const gates: Record<string, ReturnType<typeof deferred>> = {
      "wamid-a": deferred(),
      "wamid-b": deferred(),
    };
    dispatchWhatsAppCloudInboundEvent.mockImplementation(
      async (params: { msg: { messageId: string } }) => {
        order.push(`start-${params.msg.messageId}`);
        await gates[params.msg.messageId]?.promise;
        order.push(`end-${params.msg.messageId}`);
      },
    );
    const handler = createWhatsAppCloudWebhookHandler({
      cfg: CFG,
      account: ACCOUNT,
      channelRuntime: CHANNEL_RUNTIME,
    });

    await handler(fakeReq(textMessagePayload({ from: "5511900000001", id: "wamid-a" })), fakeRes());
    await handler(fakeReq(textMessagePayload({ from: "5511900000002", id: "wamid-b" })), fakeRes());

    await flushAsync();
    // Different senders must not wait on each other.
    expect(order).toEqual(["start-wamid-a", "start-wamid-b"]);

    gates["wamid-a"]?.resolve();
    gates["wamid-b"]?.resolve();
  });
});
