import type {
  IExecuteFunctions,
  INodeExecutionData,
  INodeType,
  INodeTypeDescription,
} from "n8n-workflow";
import {NodeConnectionTypes} from "n8n-workflow";
import {
  decodeBase64Secret,
  PwrSignatureError,
  verifyInbound,
} from "../../security/pwrSignature";

export class PwrSignatureGate implements INodeType {
  description: INodeTypeDescription = {
    displayName: "PWR Signature Gate",
    name: "pwrSignatureGate",
    icon: "fa:shield-alt",
    group: ["transform"],
    version: 1,
    description:
      "Verifies the PWR inbound HMAC signature on a raw webhook body before any business node runs.",
    defaults: {name: "PWR Signature Gate"},
    inputs: [NodeConnectionTypes.Main],
    outputs: [NodeConnectionTypes.Main, NodeConnectionTypes.Main],
    outputNames: ["Verified", "Rejected"],
    credentials: [
      {
        name: "pwrInboundHmac",
        required: true,
      },
    ],
    properties: [
      {
        displayName: "Expected Method",
        name: "expectedMethod",
        type: "string",
        default: "POST",
        required: true,
        description:
          "The HTTP method that must have been signed. Fixed in workflow JSON; cannot be derived from request data.",
      },
      {
        displayName: "Expected Target",
        name: "expectedTarget",
        type: "string",
        default: "",
        required: true,
        description:
          "The request path that must have been signed. Fixed in workflow JSON; cannot be derived from request data.",
      },
    ],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const verifiedOutput: INodeExecutionData[] = [];
    const rejectedOutput: INodeExecutionData[] = [];

    const maxSkewSeconds = 300;

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      const expectedMethod = this.getNodeParameter("expectedMethod", i) as string;
      const expectedTarget = this.getNodeParameter("expectedTarget", i) as string;

      try {
        const credentials = await this.getCredentials("pwrInboundHmac", i);
        const activeKeyId = credentials.activeKeyId as string;
        const activeSecretBase64 = credentials.activeSecretBase64 as string;
        const previousKeyId = (credentials.previousKeyId as string) || "";
        const previousSecretBase64 = (credentials.previousSecretBase64 as string) || "";

        const keys = {
          active: {
            keyId: activeKeyId,
            secret: decodeBase64Secret("active_secret", activeSecretBase64),
          },
          previous:
            previousKeyId && previousSecretBase64
              ? {
                  keyId: previousKeyId,
                  secret: decodeBase64Secret("previous_secret", previousSecretBase64),
                }
              : undefined,
        };

        const rawBody = await this.helpers.getBinaryDataBuffer(i, "data");
        const headers = (item.json.headers as Record<string, unknown>) ?? {};
        const query = (item.json.query as Record<string, unknown>) ?? {};

        const verified = verifyInbound({
          expectedMethod,
          expectedTarget,
          headers,
          query,
          rawBody,
          keys,
          nowSeconds: Math.floor(Date.now() / 1000),
          maxSkewSeconds,
        });

        const verifiedItem: INodeExecutionData = {
          ...item,
          json: {
            ...item.json,
            pwr: {
              verified: true,
              key_id: verified.keyId,
              timestamp: verified.timestamp,
              nonce: verified.nonce,
              signed_method: verified.signedMethod,
              signed_target: verified.signedTarget,
              delivery_generation: verified.deliveryGeneration,
              body_sha256: verified.bodySha256,
            },
          },
        };
        verifiedOutput.push(verifiedItem);
      } catch (error) {
        const statusCode = error instanceof PwrSignatureError ? error.statusCode : 500;
        const reasonCode =
          error instanceof PwrSignatureError ? error.reasonCode : "internal_error";
        rejectedOutput.push({
          json: {
            pwr: {
              verified: false,
              status_code: statusCode,
              reason_code: reasonCode,
            },
          },
        });
      }
    }

    return [verifiedOutput, rejectedOutput];
  }
}
