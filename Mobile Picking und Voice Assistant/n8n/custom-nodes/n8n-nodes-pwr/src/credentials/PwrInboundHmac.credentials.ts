import type {ICredentialType, INodeProperties} from "n8n-workflow";

export class PwrInboundHmac implements ICredentialType {
  name = "pwrInboundHmac";
  displayName = "PWR Inbound HMAC";
  properties: INodeProperties[] = [
    {displayName: "Active Key ID", name: "activeKeyId", type: "string", default: "", required: true},
    {displayName: "Active Secret Base64", name: "activeSecretBase64", type: "string", typeOptions: {password: true}, default: "", required: true},
    {displayName: "Previous Key ID", name: "previousKeyId", type: "string", default: ""},
    {displayName: "Previous Secret Base64", name: "previousSecretBase64", type: "string", typeOptions: {password: true}, default: ""},
  ];
}
