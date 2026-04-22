import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { assessAlert } from '../assess-alert-v2.mjs';

describe('V2 Assess Alert — Scoring Heuristic', () => {

  // ── Scrap cases ──────────────────────────────────────────────

  it('Totalschaden → scrap, confidence > 0.6', () => {
    const r = assessAlert({ description: 'Totalschaden am Gehaeuse, komplett zerstoert' });
    assert.equal(r.disposition, 'scrap');
    assert.ok(r.confidence > 0.6, `confidence ${r.confidence} should be > 0.6`);
  });

  it('Bruch + gebrochen → scrap with additive score', () => {
    const r = assessAlert({ description: 'Bruch an der Seite, Deckel gebrochen' });
    assert.equal(r.disposition, 'scrap');
    assert.ok(r.scores.scrap >= 16, `scrap score ${r.scores.scrap} should be >= 16`);
  });

  it('eingedrueckt allein → scrap (weight 7 >= threshold)', () => {
    const r = assessAlert({ description: 'Karton stark eingedrueckt auf der rechten Seite' });
    assert.equal(r.disposition, 'scrap');
  });

  // ── Quarantine cases ─────────────────────────────────────────

  it('defekt → quarantine', () => {
    const r = assessAlert({ description: 'Artikel ist defekt, Funktion eingeschraenkt' });
    assert.equal(r.disposition, 'quarantine');
  });

  it('feucht + gerissen → quarantine with high confidence', () => {
    const r = assessAlert({ description: 'Verpackung feucht und gerissen, Inhalt moeglicherweise betroffen' });
    assert.equal(r.disposition, 'quarantine');
    assert.ok(r.confidence > 0.55, `confidence ${r.confidence} should be > 0.55`);
  });

  it('Fotos > 0 raises quarantine score', () => {
    const base = assessAlert({ description: 'Leichte Auffaelligkeit', photo_count: 0 });
    const withPhotos = assessAlert({ description: 'Leichte Auffaelligkeit', photo_count: 2 });
    assert.ok(withPhotos.scores.quarantine > base.scores.quarantine);
  });

  it('Prioritaet 1 raises quarantine + scrap scores', () => {
    const normal = assessAlert({ description: 'Artikel defekt', priority: '0' });
    const urgent = assessAlert({ description: 'Artikel defekt', priority: '1' });
    assert.ok(urgent.scores.quarantine > normal.scores.quarantine);
    assert.ok(urgent.scores.scrap > normal.scores.scrap);
  });

  it('schimmel → quarantine (weight 7)', () => {
    const r = assessAlert({ description: 'Schimmelbefall an der Unterseite sichtbar' });
    assert.equal(r.disposition, 'quarantine');
  });

  // ── Rework cases ─────────────────────────────────────────────

  it('Kratzer auf Verpackung → rework', () => {
    const r = assessAlert({ description: 'Kleiner Kratzer auf der Verpackung' });
    assert.equal(r.disposition, 'rework');
  });

  it('Etikett + Kleber → rework with additive score', () => {
    const r = assessAlert({ description: 'Etikett schief, Kleber loest sich' });
    assert.equal(r.disposition, 'rework');
    assert.ok(r.scores.rework >= 5);
  });

  it('falsch etikettiert → rework (weight 4)', () => {
    const r = assessAlert({ description: 'Artikel falsch etikettiert, falsches Produkt-Label' });
    assert.equal(r.disposition, 'rework');
  });

  // ── Sellable / Default cases ─────────────────────────────────

  it('empty description → sellable, low confidence', () => {
    const r = assessAlert({ description: '' });
    assert.equal(r.disposition, 'sellable');
    assert.ok(r.confidence < 0.6, `confidence ${r.confidence} should be < 0.6`);
  });

  it('neutral description → sellable', () => {
    const r = assessAlert({ description: 'Ware sieht gut aus, alles in Ordnung' });
    assert.equal(r.disposition, 'sellable');
  });

  it('short description → lower confidence than long', () => {
    const short = assessAlert({ description: 'ok' });
    const long = assessAlert({ description: 'Die Ware sieht in Ordnung aus, keine Maengel erkennbar' });
    assert.ok(short.confidence <= long.confidence, `short ${short.confidence} should be <= long ${long.confidence}`);
  });

  // ── Negation cases ───────────────────────────────────────────

  it('"nicht defekt" → sellable (negation strips keyword)', () => {
    const r = assessAlert({ description: 'Ware ist nicht defekt, alles funktioniert' });
    assert.equal(r.disposition, 'sellable');
  });

  it('"kein Bruch" → does not trigger scrap', () => {
    const r = assessAlert({ description: 'Kein Bruch erkennbar, Zustand gut' });
    assert.notEqual(r.disposition, 'scrap');
  });

  it('"ohne Beschaedigung" → sellable', () => {
    const r = assessAlert({ description: 'Artikel ohne Beschaedigung erhalten' });
    assert.equal(r.disposition, 'sellable');
  });

  it('"kaum Kratzer" → does not trigger rework', () => {
    const r = assessAlert({ description: 'Kaum Kratzer sichtbar, Zustand akzeptabel' });
    // kaum negates "kratzer", so no rework score
    assert.notEqual(r.disposition, 'rework');
  });

  // ── Mixed / Edge cases ───────────────────────────────────────

  it('mixed: "nicht defekt aber Kratzer" → rework (only kratzer scores)', () => {
    const r = assessAlert({ description: 'Nicht defekt, aber leichter Kratzer am Rand sichtbar' });
    assert.equal(r.disposition, 'rework');
  });

  it('many photos + priority 1 → at least quarantine', () => {
    const r = assessAlert({ description: 'Auffaelligkeit', priority: '1', photo_count: 3 });
    assert.ok(['quarantine', 'scrap'].includes(r.disposition), `expected quarantine or scrap, got ${r.disposition}`);
  });

  it('confidence always between 0.1 and 0.95', () => {
    const cases = [
      { description: '' },
      { description: 'Totalschaden zerstoert gebrochen eingedrueckt explodiert' },
      { description: 'ok', priority: '0', photo_count: 0 },
      { description: 'defekt', priority: '1', photo_count: 5 },
    ];
    for (const c of cases) {
      const r = assessAlert(c);
      assert.ok(r.confidence >= 0.1 && r.confidence <= 0.95,
        `confidence ${r.confidence} out of range for ${JSON.stringify(c)}`);
    }
  });

  it('return object has all required fields', () => {
    const r = assessAlert({ description: 'Test' });
    assert.ok('disposition' in r);
    assert.ok('confidence' in r);
    assert.ok('scores' in r);
    assert.ok('totalMatches' in r);
    assert.ok('topScore' in r);
    assert.ok('action' in r);
    assert.ok(['sellable', 'rework', 'quarantine', 'scrap'].includes(r.disposition));
  });
});

describe('V2 Assess Alert - Workflow Drift Protection', () => {
  const workflow = JSON.parse(
    readFileSync(new URL('../workflows/quality-alert-created.json', import.meta.url), 'utf8'),
  );
  const assessNode = workflow.nodes.find((node) => node.name === 'Assess Alert');

  it('workflow contains an Assess Alert function node', () => {
    assert.ok(assessNode);
    assert.equal(typeof assessNode.parameters?.functionCode, 'string');
  });

  const runWorkflowAssess = (payload) => {
    const functionCode = assessNode.parameters.functionCode;
    const fn = new Function('items', functionCode);
    const result = fn([
      {
        json: {
          body: {
            correlation_id: 'corr-test',
            schema_version: 'v1',
            occurred_at: '2026-03-31T10:00:00Z',
            payload,
          },
        },
      },
    ]);
    assert.ok(Array.isArray(result));
    assert.equal(result.length, 1);
    return result[0].json;
  };

  const goldenCases = [
    { name: 'empty description', payload: { alert_id: 1, description: '', priority: '0', photo_count: 0 } },
    {
      name: 'neutral description',
      payload: { alert_id: 2, description: 'Ware sieht gut aus, alles in Ordnung', priority: '0', photo_count: 0 },
    },
    {
      name: 'scrap indicator',
      payload: { alert_id: 3, description: 'Totalschaden am Gehaeuse, komplett zerstoert', priority: '0', photo_count: 1 },
    },
    {
      name: 'quarantine indicator',
      payload: { alert_id: 4, description: 'Verpackung feucht und gerissen', priority: '0', photo_count: 1 },
    },
    {
      name: 'rework indicator',
      payload: { alert_id: 5, description: 'Etikett schief, leichter Kratzer sichtbar', priority: '0', photo_count: 0 },
    },
    {
      name: 'negation case',
      payload: { alert_id: 6, description: 'Ware ist nicht defekt, alles funktioniert', priority: '0', photo_count: 0 },
    },
    {
      name: 'mixed signals',
      payload: { alert_id: 7, description: 'Nicht defekt, aber leichter Kratzer am Rand sichtbar', priority: '0', photo_count: 0 },
    },
    {
      name: 'priority and photos',
      payload: { alert_id: 8, description: 'Auffaelligkeit am Karton', priority: '1', photo_count: 3 },
    },
  ];

  for (const goldenCase of goldenCases) {
    it(`matches assessAlert module for ${goldenCase.name}`, () => {
      const expected = assessAlert(goldenCase.payload);
      const workflowResult = runWorkflowAssess(goldenCase.payload);

      assert.equal(workflowResult.ai_disposition, expected.disposition);
      assert.equal(workflowResult.ai_confidence, expected.confidence);
      assert.equal(workflowResult.ai_recommended_action, expected.action);
      assert.equal(workflowResult.schema_version, 'v1');
      assert.equal(workflowResult.alert_id, goldenCase.payload.alert_id);
      assert.equal(typeof workflowResult.latency_tracking?.started_at, 'string');
      assert.ok(workflowResult.latency_tracking?.total_duration_ms >= 0);
      assert.ok(workflowResult.latency_tracking?.stages?.heuristic_ms >= 0);
    });
  }
});
