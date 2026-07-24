import type {ICredentialType, INodeProperties} from "n8n-workflow";

export class PwrOutboundHmac implements ICredentialType {
  name = "pwrOutboundHmac";
  displayName = "PWR Outbound HMAC";
  properties: INodeProperties[] = [
    {displayName: "Base URL", name: "baseUrl", type: "string", default: "http://backend:8000", required: true},
    {displayName: "Active Key ID", name: "activeKeyId", type: "string", default: "", required: true},
    {displayName: "Active Secret Base64", name: "activeSecretBase64", type: "string", typeOptions: {password: true}, default: "", required: true},
    {displayName: "Legacy Callback Secret", name: "legacyCallbackSecret", type: "string", typeOptions: {password: true}, default: ""},
  ];
}
