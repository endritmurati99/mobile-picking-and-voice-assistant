import {randomUUID} from "node:crypto";
import type {
  IDataObject,
  IExecuteFunctions,
  IHttpRequestOptions,
  INodeExecutionData,
  INodeType,
  INodeTypeDescription,
} from "n8n-workflow";
import {NodeConnectionTypes, NodeOperationError} from "n8n-workflow";
import {decodeBase64Secret} from "../../security/pwrSignature";
import {buildSignedRequest} from "../../security/signedRequest";

const MAX_TIMEOUT_MS = 30000;

export class PwrSignedHttpRequest implements INodeType {
  description: INodeTypeDescription = {
    displayName: "PWR Signed HTTP Request",
    name: "pwrSignedHttpRequest",
    icon: "fa:lock",
    group: ["transform"],
    version: 1,
    description:
      "Builds and sends a canonically-signed HTTP request to the PWR backend using outbound HMAC credentials.",
    defaults: {name: "PWR Signed HTTP Request"},
    inputs: [NodeConnectionTypes.Main],
    outputs: [NodeConnectionTypes.Main],
    credentials: [
      {
        name: "pwrOutboundHmac",
        required: true,
      },
    ],
    properties: [
      {
        displayName: "Method",
        name: "method",
        type: "options",
        options: [
          {name: "GET", value: "GET"},
          {name: "POST", value: "POST"},
          {name: "PUT", value: "PUT"},
          {name: "PATCH", value: "PATCH"},
          {name: "DELETE", value: "DELETE"},
        ],
        default: "POST",
        required: true,
      },
      {
        displayName: "Target",
        name: "target",
        type: "string",
        default: "",
        required: true,
        description: "Relative path only, e.g. /api/internal/n8n/v2/events/accept",
      },
      {
        displayName: "Host",
        name: "host",
        type: "string",
        default: "",
        required: true,
        description:
          "Hostname this node is declared to reach, e.g. backend. Must equal the hostname of the bound pwrOutboundHmac credential's Base URL; execution fails closed otherwise.",
      },
      {
        displayName: "Body Mode",
        name: "bodyMode",
        type: "options",
        options: [
          {name: "None", value: "none"},
          {name: "JSON", value: "json"},
          {name: "Binary", value: "binary"},
          {name: "Literal UTF-8 (test only)", value: "literalUtf8"},
        ],
        default: "none",
        required: true,
      },
      {
        displayName: "JSON Property",
        name: "jsonProperty",
        type: "string",
        default: "data",
        displayOptions: {show: {bodyMode: ["json"]}},
        description: "Name of the item JSON field whose value is serialized exactly once with JSON.stringify().",
      },
      {
        displayName: "Binary Property",
        name: "binaryProperty",
        type: "string",
        default: "data",
        displayOptions: {show: {bodyMode: ["binary"]}},
      },
      {
        displayName: "Literal Body",
        name: "literalBody",
        type: "string",
        default: "",
        displayOptions: {show: {bodyMode: ["literalUtf8"]}},
        description: "Verifier-restricted synthetic test mode only. Requires a reviewed test_only=true registry entry.",
      },
      {
        displayName: "Content Type",
        name: "contentType",
        type: "string",
        default: "application/json",
        required: true,
      },
      {
        displayName: "Delivery Generation Property",
        name: "deliveryGenerationProperty",
        type: "string",
        default: "delivery_generation",
        description: "Name of the item JSON field holding the delivery generation integer.",
      },
      {
        displayName: "Idempotency Key Property",
        name: "idempotencyKeyProperty",
        type: "string",
        default: "idempotency_key",
        description: "Name of the item JSON field holding the idempotency key string.",
      },
      {
        displayName: "Response Mode",
        name: "responseMode",
        type: "options",
        options: [
          {name: "JSON", value: "json"},
          {name: "Binary", value: "binary"},
        ],
        default: "json",
        required: true,
      },
      {
        displayName: "Timeout (ms)",
        name: "timeoutMs",
        type: "number",
        default: 10000,
        description: "Capped at 30000ms.",
      },
    ],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const output: INodeExecutionData[] = [];

    const credentials = await this.getCredentials("pwrOutboundHmac", 0);
    const baseUrl = credentials.baseUrl as string;
    const keyId = credentials.activeKeyId as string;
    const secret = decodeBase64Secret(
      "active_secret",
      credentials.activeSecretBase64 as string,
    );
    const legacyCallbackSecret = (credentials.legacyCallbackSecret as string) || undefined;

    let credentialHost: string;
    try {
      credentialHost = new URL(baseUrl).hostname.toLowerCase();
    } catch {
      throw new NodeOperationError(
        this.getNode(),
        `PWR signed request credential has an unparseable Base URL '${baseUrl}'`,
      );
    }
    if (!credentialHost) {
      throw new NodeOperationError(
        this.getNode(),
        `PWR signed request credential Base URL '${baseUrl}' has no hostname`,
      );
    }

    for (let i = 0; i < items.length; i++) {
      const item = items[i];

      // The workflow file declares which host this node may reach, and the
      // static workflow verifier checks that declaration against
      // allowed_target_hosts. Bind the declaration to the host actually
      // dialled -- the credential's Base URL -- so the file is not merely
      // decorative. Compare parsed hostnames for exact equality: a prefix,
      // suffix or substring comparison would let 'backend.attacker.example'
      // pass for 'backend'.
      const declaredHost = String(this.getNodeParameter("host", i) ?? "").trim().toLowerCase();
      if (!declaredHost) {
        throw new NodeOperationError(
          this.getNode(),
          `PWR signed request declares no host; a host equal to the credential Base URL ` +
            `hostname '${credentialHost}' is required (host_mismatch)`,
        );
      }
      if (declaredHost !== credentialHost) {
        throw new NodeOperationError(
          this.getNode(),
          `PWR signed request host_mismatch: declared host '${declaredHost}' does not equal the ` +
            `pwrOutboundHmac credential Base URL hostname '${credentialHost}' (baseUrl '${baseUrl}')`,
        );
      }

      const method = this.getNodeParameter("method", i) as string;
      const target = this.getNodeParameter("target", i) as string;
      const bodyMode = this.getNodeParameter("bodyMode", i) as
        | "none"
        | "json"
        | "binary"
        | "literalUtf8";
      const contentType = this.getNodeParameter("contentType", i) as string;
      const deliveryGenerationProperty = this.getNodeParameter(
        "deliveryGenerationProperty",
        i,
      ) as string;
      const idempotencyKeyProperty = this.getNodeParameter(
        "idempotencyKeyProperty",
        i,
      ) as string;
      const responseMode = this.getNodeParameter("responseMode", i) as "json" | "binary";
      const requestedTimeoutMs = this.getNodeParameter("timeoutMs", i) as number;
      const timeoutMs = Math.min(requestedTimeoutMs, MAX_TIMEOUT_MS);

      let body: Buffer;
      switch (bodyMode) {
        case "none":
          body = Buffer.alloc(0);
          break;
        case "json": {
          const jsonProperty = this.getNodeParameter("jsonProperty", i) as string;
          const value = item.json[jsonProperty];
          body = Buffer.from(JSON.stringify(value), "utf8");
          break;
        }
        case "binary": {
          const binaryProperty = this.getNodeParameter("binaryProperty", i) as string;
          body = await this.helpers.getBinaryDataBuffer(i, binaryProperty);
          break;
        }
        case "literalUtf8": {
          const literalBody = this.getNodeParameter("literalBody", i) as string;
          body = Buffer.from(literalBody, "utf8");
          break;
        }
        default:
          throw new NodeOperationError(this.getNode(), `Unsupported bodyMode: ${bodyMode}`);
      }

      const deliveryGeneration = Number(item.json[deliveryGenerationProperty]);
      const idempotencyKey = String(item.json[idempotencyKeyProperty]);

      const prepared = buildSignedRequest({
        baseUrl,
        method,
        target,
        body,
        contentType,
        deliveryGeneration,
        idempotencyKey,
        timestamp: Math.floor(Date.now() / 1000),
        nonce: randomUUID(),
        keyId,
        secret,
        legacyCallbackSecret,
      });

      const requestOptions: IHttpRequestOptions = {
        url: prepared.url,
        method: method as IHttpRequestOptions["method"],
        headers: prepared.headers,
        body: prepared.body,
        json: false,
        encoding: "arraybuffer",
        disableFollowRedirect: true,
        returnFullResponse: true,
        timeout: timeoutMs,
      };

      const response = await this.helpers.httpRequest(requestOptions);
      const statusCode: number = response.statusCode;

      if (statusCode >= 300 && statusCode < 400) {
        throw new NodeOperationError(
          this.getNode(),
          `PWR signed request received a redirect (status ${statusCode}); redirects are not followed.`,
        );
      }

      const responseBytes: Buffer = Buffer.isBuffer(response.body)
        ? response.body
        : Buffer.from(response.body ?? "");

      if (responseMode === "json") {
        let parsed: unknown;
        try {
          parsed = JSON.parse(responseBytes.toString("utf8"));
        } catch (error) {
          throw new NodeOperationError(
            this.getNode(),
            "PWR signed request response was not valid JSON",
          );
        }
        output.push({
          json: (parsed ?? {}) as IDataObject,
        });
      } else {
        const binary = await this.helpers.prepareBinaryData(responseBytes);
        output.push({
          json: {},
          binary: {data: binary},
        });
      }
    }

    return [output];
  }
}
