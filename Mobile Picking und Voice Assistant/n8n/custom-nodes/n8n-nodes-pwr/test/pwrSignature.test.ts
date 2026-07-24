import assert from "node:assert/strict";
import test from "node:test";
import {
  buildSigningBytes,
  sha256Hex,
  signHmac,
  verifyInbound,
} from "../src/security/pwrSignature";

const body = Buffer.from(
  '{"event_id":"a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32"}',
  "utf8",
);

test("matches the frozen Python HMAC vector", () => {
  assert.equal(
    sha256Hex(body),
    "cdc9aeda6396616866f863a30ce8507232b2cecd6cdd68c206c24b8c128751fc",
  );
  const signingBytes = buildSigningBytes({
    method: "POST",
    target: "/webhook/quality-assessment-v2",
    deliveryGeneration: "1",
    timestamp: "1760000000",
    nonce: "123e4567-e89b-42d3-a456-426614174000",
    bodySha256: sha256Hex(body),
  });
  assert.equal(
    signHmac(Buffer.from("0".repeat(32), "utf8"), signingBytes),
    "v1=6466f16aca767c63504c2d002d729c35fdc12df969060bc4e7e76fd0c69a43d4",
  );
});

test("accepts previous key and rejects a query", () => {
  const input = {
    expectedMethod: "POST",
    expectedTarget: "/webhook/quality-assessment-v2",
    query: {},
    rawBody: body,
    nowSeconds: 1760000000,
    maxSkewSeconds: 300,
    headers: {
      "x-pwr-key-id": "previous",
      "x-pwr-timestamp": "1760000000",
      "x-pwr-nonce": "123e4567-e89b-42d3-a456-426614174000",
      "x-pwr-signed-method": "POST",
      "x-pwr-signed-target": "/webhook/quality-assessment-v2",
      "x-pwr-delivery-generation": "1",
      "x-pwr-signature":
        "v1=6466f16aca767c63504c2d002d729c35fdc12df969060bc4e7e76fd0c69a43d4",
    },
    keys: {
      active: {keyId: "active", secret: Buffer.from("1".repeat(32))},
      previous: {keyId: "previous", secret: Buffer.from("0".repeat(32))},
    },
  };
  assert.equal(verifyInbound(input).keyId, "previous");
  assert.throws(
    () => verifyInbound({...input, query: {debug: "1"}}),
    /query_not_allowed/,
  );
});
