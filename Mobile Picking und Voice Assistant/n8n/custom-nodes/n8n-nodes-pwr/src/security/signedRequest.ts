import {buildSigningBytes, sha256Hex, signHmac} from "./pwrSignature";

export type SignedRequestInput = {
  baseUrl: string;
  method: string;
  target: string;
  body: Buffer;
  contentType: string;
  deliveryGeneration: number;
  idempotencyKey: string;
  timestamp: number;
  nonce: string;
  keyId: string;
  secret: Buffer;
  legacyCallbackSecret?: string;
};

export type PreparedSignedRequest = {
  url: string;
  headers: Record<string, string>;
  body: Buffer;
};

export function buildSignedRequest(input: SignedRequestInput): PreparedSignedRequest {
  if (
    !input.target.startsWith("/") ||
    input.target.startsWith("//") ||
    input.target.includes("?") ||
    input.target.includes("#") ||
    input.target.includes("://")
  ) {
    throw new Error("invalid_target");
  }
  const base = new URL(input.baseUrl);
  if (base.pathname !== "/" || base.search || base.hash) {
    throw new Error("invalid_base_url");
  }
  const url = new URL(input.target, base);
  if (url.origin !== base.origin || `${url.pathname}` !== input.target) {
    throw new Error("invalid_target");
  }
  const deliveryGeneration = String(input.deliveryGeneration);
  const signature = signHmac(
    input.secret,
    buildSigningBytes({
      method: input.method,
      target: input.target,
      deliveryGeneration,
      timestamp: String(input.timestamp),
      nonce: input.nonce,
      bodySha256: sha256Hex(input.body),
    }),
  );
  const headers: Record<string, string> = {
    "Content-Type": input.contentType,
    "Idempotency-Key": input.idempotencyKey,
    "X-PWR-Key-Id": input.keyId,
    "X-PWR-Timestamp": String(input.timestamp),
    "X-PWR-Nonce": input.nonce,
    "X-PWR-Signed-Method": input.method,
    "X-PWR-Signed-Target": input.target,
    "X-PWR-Delivery-Generation": deliveryGeneration,
    "X-PWR-Signature": signature,
  };
  if (input.legacyCallbackSecret) {
    headers["X-N8N-Callback-Secret"] = input.legacyCallbackSecret;
  }
  return {url: url.toString(), headers, body: input.body};
}
