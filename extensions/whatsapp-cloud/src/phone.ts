// WhatsApp Cloud plugin module implements phone behavior.
export function normalizeWhatsAppCloudPhoneNumber(raw: string): string {
  const trimmed = raw.trim().replace(/^whatsapp-cloud:/i, "");
  return trimmed.replace(/[^\d]/g, "");
}

export function normalizeWhatsAppCloudAllowFrom(raw: string): string {
  if (raw.trim() === "*") {
    return "*";
  }
  return normalizeWhatsAppCloudPhoneNumber(raw);
}

const BRAZIL_MOBILE_MISSING_NINE = /^55(\d{2})([6-9]\d{7})$/;

/**
 * Meta's inbound webhook `from` field drops the leading "9" that Brazilian
 * mobile numbers carry, but the Graph API send endpoint requires it (target
 * must match the number as registered in the recipient allowlist/contact).
 * Expand 55DDNNNNNNNN (8-digit subscriber) to 55DD9NNNNNNNN before sending.
 */
export function toWhatsAppCloudSendableNumber(raw: string): string {
  const normalized = normalizeWhatsAppCloudPhoneNumber(raw);
  const match = normalized.match(BRAZIL_MOBILE_MISSING_NINE);
  if (!match) {
    return normalized;
  }
  return `55${match[1]}9${match[2]}`;
}
