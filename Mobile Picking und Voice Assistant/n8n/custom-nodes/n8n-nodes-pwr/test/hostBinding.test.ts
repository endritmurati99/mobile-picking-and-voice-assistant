import assert from "node:assert/strict";
import test from "node:test";
import type {IExecuteFunctions} from "n8n-workflow";
import {PwrSignedHttpRequest} from "../src/nodes/PwrSignedHttpRequest/PwrSignedHttpRequest.node";

type Params = Record<string, unknown>;

function makeContext(options: {baseUrl: string; params: Params}): {
  ctx: IExecuteFunctions;
  sent: {url?: string};
} {
  const sent: {url?: string} = {};
  const params: Params = {
    method: "POST",
    target: "/api/internal/n8n/v2/events/accept",
    bodyMode: "json",
    jsonProperty: "data",
    contentType: "application/json",
    deliveryGenerationProperty: "delivery_generation",
    idempotencyKeyProperty: "idempotency_key",
    responseMode: "json",
    timeoutMs: 5000,
    ...options.params,
  };
  const ctx = {
    getInputData: () => [
      {json: {data: {event_id: "event-1"}, delivery_generation: 1, idempotency_key: "key-1"}},
    ],
    getCredentials: async () => ({
      baseUrl: options.baseUrl,
      activeKeyId: "n2b-test",
      activeSecretBase64: Buffer.from("2".repeat(32)).toString("base64"),
      legacyCallbackSecret: "",
    }),
    getNodeParameter: (name: string) => params[name],
    getNode: () => ({
      id: "1",
      name: "Signed Request",
      type: "n8n-nodes-pwr.pwrSignedHttpRequest",
      typeVersion: 1,
      position: [0, 0] as [number, number],
      parameters: {},
    }),
    helpers: {
      httpRequest: async (requestOptions: {url: string}) => {
        sent.url = requestOptions.url;
        return {statusCode: 200, body: Buffer.from("{}", "utf8")};
      },
    },
  } as unknown as IExecuteFunctions;
  return {ctx, sent};
}

test("declares a required host property", () => {
  const property = new PwrSignedHttpRequest().description.properties.find(
    (candidate) => candidate.name === "host",
  );
  assert.ok(property, "node must expose a 'host' property");
  assert.equal(property?.required, true);
});

test("fails closed when the credential's baseUrl hostname differs from the declared host", async () => {
  const {ctx, sent} = makeContext({
    baseUrl: "http://odoo:8069",
    params: {host: "backend"},
  });
  await assert.rejects(
    () => new PwrSignedHttpRequest().execute.call(ctx),
    (error: Error) =>
      /declared host 'backend'/.test(error.message) && /'odoo'/.test(error.message),
  );
  assert.equal(sent.url, undefined, "no request may be dispatched");
});

test("refuses the near-miss suffix host backend.attacker.example", async () => {
  const {ctx, sent} = makeContext({
    baseUrl: "http://backend.attacker.example:8000",
    params: {host: "backend"},
  });
  await assert.rejects(
    () => new PwrSignedHttpRequest().execute.call(ctx),
    (error: Error) =>
      /declared host 'backend'/.test(error.message) &&
      /'backend\.attacker\.example'/.test(error.message),
  );
  assert.equal(sent.url, undefined, "no request may be dispatched");
});

test("refuses a declared host that merely contains the credential hostname", async () => {
  const {ctx, sent} = makeContext({
    baseUrl: "http://backend:8000",
    params: {host: "backend.attacker.example"},
  });
  await assert.rejects(() => new PwrSignedHttpRequest().execute.call(ctx), /host_mismatch/);
  assert.equal(sent.url, undefined, "no request may be dispatched");
});

test("fails closed when no host is declared at all", async () => {
  const {ctx, sent} = makeContext({baseUrl: "http://backend:8000", params: {host: ""}});
  await assert.rejects(
    () => new PwrSignedHttpRequest().execute.call(ctx),
    /declares no host/,
  );
  assert.equal(sent.url, undefined, "no request may be dispatched");
});

test("sends when the declared host matches the credential hostname exactly", async () => {
  const {ctx, sent} = makeContext({baseUrl: "http://backend:8000", params: {host: "backend"}});
  await new PwrSignedHttpRequest().execute.call(ctx);
  assert.equal(sent.url, "http://backend:8000/api/internal/n8n/v2/events/accept");
});
