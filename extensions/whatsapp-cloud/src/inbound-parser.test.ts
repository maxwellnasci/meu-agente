import { describe, expect, it } from "vitest";
import { parseWhatsAppCloudWebhookPayload } from "./inbound-parser.js";

function textMessagePayload(overrides?: { body?: string; from?: string; id?: string }) {
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
              metadata: { display_phone_number: "15551465990", phone_number_id: "1138532409351860" },
              contacts: [{ profile: { name: "Max" }, wa_id: "5511999999999" }],
              messages: [
                {
                  from: overrides?.from ?? "5511999999999",
                  id: overrides?.id ?? "wamid.ABC123",
                  timestamp: "1752480000",
                  type: "text",
                  text: { body: overrides?.body ?? "oi amigao" },
                },
              ],
            },
          },
        ],
      },
    ],
  };
}

describe("parseWhatsAppCloudWebhookPayload", () => {
  it("extracts a text message and the phone_number_id", () => {
    const result = parseWhatsAppCloudWebhookPayload(textMessagePayload());
    expect(result.phoneNumberId).toBe("1138532409351860");
    expect(result.messages).toHaveLength(1);
    expect(result.messages[0]).toMatchObject({
      from: "5511999999999",
      messageId: "wamid.ABC123",
      body: "oi amigao",
    });
    expect(result.messages[0]?.timestamp).toBe(1752480000 * 1000);
  });

  it("returns no messages for a status-only payload", () => {
    const statusPayload = {
      entry: [
        {
          changes: [
            {
              field: "messages",
              value: {
                metadata: { phone_number_id: "1138532409351860" },
                statuses: [{ id: "wamid.ABC123", status: "delivered" }],
              },
            },
          ],
        },
      ],
    };
    const result = parseWhatsAppCloudWebhookPayload(statusPayload);
    expect(result.messages).toHaveLength(0);
    expect(result.phoneNumberId).toBe("1138532409351860");
  });

  it("skips non-text message types", () => {
    const payload = textMessagePayload();
    payload.entry[0].changes[0].value.messages[0] = {
      from: "5511999999999",
      id: "wamid.IMG1",
      timestamp: "1752480000",
      type: "image",
    } as unknown as (typeof payload.entry)[0]["changes"][0]["value"]["messages"][0];
    const result = parseWhatsAppCloudWebhookPayload(payload);
    expect(result.messages).toHaveLength(0);
  });

  it("ignores changes with a field other than messages", () => {
    const result = parseWhatsAppCloudWebhookPayload({
      entry: [{ changes: [{ field: "account_alerts", value: {} }] }],
    });
    expect(result.messages).toHaveLength(0);
  });

  it("handles malformed or empty bodies without throwing", () => {
    expect(parseWhatsAppCloudWebhookPayload(null).messages).toHaveLength(0);
    expect(parseWhatsAppCloudWebhookPayload({}).messages).toHaveLength(0);
    expect(parseWhatsAppCloudWebhookPayload({ entry: "not-an-array" }).messages).toHaveLength(0);
  });

  it("drops a message missing a text body", () => {
    const payload = textMessagePayload();
    payload.entry[0].changes[0].value.messages[0].text = { body: "" };
    const result = parseWhatsAppCloudWebhookPayload(payload);
    expect(result.messages).toHaveLength(0);
  });
});
