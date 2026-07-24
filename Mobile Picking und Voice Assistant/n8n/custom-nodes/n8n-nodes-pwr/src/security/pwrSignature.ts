import {
  createHash,
  createHmac,
  timingSafeEqual,
} from "node:crypto";

export type HmacKey = {keyId: string; secret: Buffer};
export type HmacKeys = {active: HmacKey; previous?: HmacKey};

export type SigningFields = {
  method: string;
  target: string;
  deliveryGeneration: string;
  timestamp: string;
  nonce: string;
  bodySha256: string;
};

export type VerifyInput = {
  expectedMethod: string;
  expectedTarget: string;
  headers: Record<string, unknown>;
  query: Record<string, unknown>;
  rawBody: Buffer;
  keys: HmacKeys;
  nowSeconds: number;
  maxSkewSeconds: number;
};

export type VerifiedInbound = {
  keyId: string;
  timestamp: number;
  nonce: string;
  signedMethod: string;
  signedTarget: string;
  deliveryGeneration: number;
  bodySha256: string;
};

export class PwrSignatureError extends Error {
  constructor(
    public readonly statusCode: number,
    public readonly reasonCode: string,
  ) {
    super(reasonCode);
  }
}

const generationPattern = /^[1-9][0-9]*$/;
const noncePattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const signaturePattern = /^v1=[0-9a-f]{64}$/;

export function decodeBase64Secret(name: string, encoded: string): Buffer {
  const secret = Buffer.from(encoded, "base64");
  if (
    secret.length < 32 ||
    secret.toString("base64").replace(/=+$/, "") !== encoded.replace(/=+$/, "")
  ) {
    throw new Error(`${name}_must_be_valid_base64_with_32_bytes`);
  }
  return secret;
}

export function sha256Hex(body: Buffer): string {
  return createHash("sha256").update(body).digest("hex");
}

export function buildSigningBytes(fields: SigningFields): Buffer {
  if (!generationPattern.test(fields.deliveryGeneration)) {
    throw new PwrSignatureError(400, "invalid_delivery_generation");
  }
  return Buffer.from(
    [
      fields.method,
      fields.target,
      fields.deliveryGeneration,
      fields.timestamp,
      fields.nonce,
      fields.bodySha256,
    ].join("\n"),
    "utf8",
  );
}

export function signHmac(secret: Buffer, signingBytes: Buffer): string {
  return `v1=${createHmac("sha256", secret).update(signingBytes).digest("hex")}`;
}

function header(headers: Record<string, unknown>, name: string): string {
  const value = headers[name] ?? headers[name.toLowerCase()];
  if (typeof value !== "string" || value.length === 0) {
    throw new PwrSignatureError(401, "missing_signature_header");
  }
  return value;
}

export function verifyInbound(input: VerifyInput): VerifiedInbound {
  if (Object.keys(input.query).length !== 0) {
    throw new PwrSignatureError(400, "query_not_allowed");
  }
  const keyId = header(input.headers, "x-pwr-key-id");
  const timestampText = header(input.headers, "x-pwr-timestamp");
  const nonce = header(input.headers, "x-pwr-nonce");
  const method = header(input.headers, "x-pwr-signed-method");
  const target = header(input.headers, "x-pwr-signed-target");
  const generation = header(input.headers, "x-pwr-delivery-generation");
  const supplied = header(input.headers, "x-pwr-signature");
  const key = [input.keys.active, input.keys.previous].find(
    (candidate) => candidate?.keyId === keyId,
  );
  if (!key) {
    throw new PwrSignatureError(401, "unknown_key_id");
  }
  if (
    !/^[0-9]+$/.test(timestampText) ||
    !noncePattern.test(nonce) ||
    !generationPattern.test(generation)
  ) {
    throw new PwrSignatureError(400, "malformed_signature_metadata");
  }
  const timestamp = Number(timestampText);
  if (
    !Number.isSafeInteger(timestamp) ||
    Math.abs(input.nowSeconds - timestamp) > input.maxSkewSeconds
  ) {
    throw new PwrSignatureError(409, "timestamp_outside_window");
  }
  if (method !== input.expectedMethod || target !== input.expectedTarget) {
    throw new PwrSignatureError(401, "signed_request_mismatch");
  }
  if (!signaturePattern.test(supplied)) {
    throw new PwrSignatureError(401, "malformed_signature");
  }
  const bodySha256 = sha256Hex(input.rawBody);
  const expected = signHmac(
    key.secret,
    buildSigningBytes({
      method,
      target,
      deliveryGeneration: generation,
      timestamp: timestampText,
      nonce,
      bodySha256,
    }),
  );
  const suppliedBytes = Buffer.from(supplied, "utf8");
  const expectedBytes = Buffer.from(expected, "utf8");
  if (
    suppliedBytes.length !== expectedBytes.length ||
    !timingSafeEqual(suppliedBytes, expectedBytes)
  ) {
    throw new PwrSignatureError(401, "invalid_signature");
  }
  return {
    keyId,
    timestamp,
    nonce,
    signedMethod: method,
    signedTarget: target,
    deliveryGeneration: Number(generation),
    bodySha256,
  };
}
