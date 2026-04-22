import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

const mainWorkflow = JSON.parse(
  readFileSync(new URL('../workflows/quality-alert-created.json', import.meta.url), 'utf8'),
);
const shadowWorkflow = JSON.parse(
  readFileSync(new URL('../workflows/quality-alert-ai-evaluation.json', import.meta.url), 'utf8'),
);

describe('Quality Shadow Evaluation Workflow', () => {
  it('quality-alert-created no longer contains the shadow subworkflow in the live path', () => {
    const executeNode = mainWorkflow.nodes.find((node) => node.name === 'Execute Shadow AI Evaluation');
    assert.equal(executeNode, undefined);
  });

  it('shadow workflow uses an internal execute-workflow trigger instead of a public webhook', () => {
    const triggerNode = shadowWorkflow.nodes.find(
      (node) => node.type === 'n8n-nodes-base.executeWorkflowTrigger',
    );
    const webhookNode = shadowWorkflow.nodes.find((node) => node.type === 'n8n-nodes-base.webhook');
    assert.ok(triggerNode);
    assert.equal(triggerNode.parameters?.inputSource, 'passthrough');
    assert.equal(webhookNode, undefined);
  });

  it('shadow workflow callback payload includes the strict comparison fields', () => {
    const callbackNode = shadowWorkflow.nodes.find((node) => node.name === 'Write Shadow Evaluation');
    assert.ok(callbackNode);
    const body = callbackNode.parameters?.bodyParametersJson || '';
    for (const requiredField of [
      'schema_version',
      'execution_id',
      'latency_tracking',
      'correlation_id',
      'alert_id',
      'category',
      'confidence',
      'reason',
      'model',
    ]) {
      assert.match(body, new RegExp(requiredField));
    }
  });
});
