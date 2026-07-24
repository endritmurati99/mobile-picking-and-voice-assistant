import assert from "node:assert/strict";
import test from "node:test";
import {buildSignedRequest} from "../src/security/signedRequest";

test("signs the same JSON bytes that the sender receives", () => {
  const prepared = buildSignedRequest({
    baseUrl: "http://backend:8000",
    method: "POST",
    target: "/api/internal/n8n/v2/events/accept",
    body: Buffer.from('{"event_id":"event-1"}', "utf8"),
    contentType: "application/json",
    deliveryGeneration: 3,
    idempotencyKey: "callback-1",
    timestamp: 1760000000,
    nonce: "123e4567-e89b-42d3-a456-426614174000",
    keyId: "n2b-test",
    secret: Buffer.from("2".repeat(32)),
  });
  assert.equal(prepared.url, "http://backend:8000/api/internal/n8n/v2/events/accept");
  assert.equal(prepared.body.toString("utf8"), '{"event_id":"event-1"}');
  assert.equal(prepared.headers["X-PWR-Delivery-Generation"], "3");
  assert.equal(prepared.headers["Idempotency-Key"], "callback-1");
});

test("rejects absolute, redirected, queried, and cross-host targets", () => {
  const common = {
    baseUrl: "http://backend:8000",
    method: "POST",
    body: Buffer.alloc(0),
    contentType: "application/octet-stream",
    deliveryGeneration: 1,
    idempotencyKey: "id-1",
    timestamp: 1760000000,
    nonce: "123e4567-e89b-42d3-a456-426614174000",
    keyId: "n2b-test",
    secret: Buffer.from("2".repeat(32)),
  };
  for (const target of [
    "http://attacker.invalid/x",
    "//attacker.invalid/x",
    "/safe?redirect=http://attacker.invalid",
    "/safe#fragment",
  ]) {
    assert.throws(() => buildSignedRequest({...common, target}), /invalid_target/);
  }
});
