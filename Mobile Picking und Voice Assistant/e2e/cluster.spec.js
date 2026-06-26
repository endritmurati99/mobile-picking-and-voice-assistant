const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');

// Stateful Cluster-API-Mock: getBatch spiegelt die picked-Flags wider, die
// confirm-line setzt, damit der Fortschritt im Rundgang real hochzaehlt.
async function mockClusterApi(page) {
  const lines = [
    {
      id: 5001, picking_id: 1001, picking_name: 'WH/INT/00007',
      box_index: 1, box_color: '#A299FF',
      package_name: 'CLUSTER-B1/WH/INT/00007',
      product_name: 'Brick 2x2 orange', product_barcode: '4006381333931',
      tracking: 'none', quantity_demand: 4, picked: false,
      location_src: 'WH/Stock/Lager Links/L-E1-P1', location_src_short: 'L-E1-P1',
      voice_instruction_short: 'L-E1-P1. 4 Stueck. Brick 2x2 orange.',
    },
    {
      id: 5002, picking_id: 1002, picking_name: 'WH/INT/00008',
      box_index: 2, box_color: '#FF8A7E',
      package_name: 'CLUSTER-B2/WH/INT/00008',
      product_name: 'Motorblock', product_barcode: '9780201379624',
      tracking: 'serial', quantity_demand: 1, picked: false,
      location_src: 'WH/Stock/Halle A/A-12', location_src_short: 'A-12',
      voice_instruction_short: 'A-12. 1 Stueck. Motorblock.',
    },
  ];
  const confirmRequests = [];
  let validated = false;

  function batchPayload() {
    const done = lines.filter((l) => l.picked).length;
    return {
      batch_id: 9001,
      name: 'BATCH/0001',
      state: validated ? 'done' : 'in_progress',
      picker: 'Lena Lager',
      boxes: [
        { picking_id: 1001, picking_name: 'WH/INT/00007', box_index: 1, box_color: '#A299FF', package_name: 'CLUSTER-B1/WH/INT/00007' },
        { picking_id: 1002, picking_name: 'WH/INT/00008', box_index: 2, box_color: '#FF8A7E', package_name: 'CLUSTER-B2/WH/INT/00008' },
      ],
      lines: JSON.parse(JSON.stringify(lines)),
      progress: { total: lines.length, done, ratio: lines.length ? done / lines.length : 0 },
    };
  }

  await page.route('**/api/cluster/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const json = (status, body) => route.fulfill({
      status, contentType: 'application/json', body: JSON.stringify(body),
    });

    if (path === '/api/cluster/suggestions' && method === 'GET') {
      return json(200, [{
        zone: 'Lager Links', picking_ids: [1001, 1002],
        order_count: 2, line_count: 2,
        picking_names: ['WH/INT/00007', 'WH/INT/00008'],
      }]);
    }
    if (path === '/api/cluster/batches' && method === 'POST') {
      return json(200, batchPayload());
    }
    if (path === '/api/cluster/batches/9001' && method === 'GET') {
      return json(200, batchPayload());
    }
    if (path === '/api/cluster/batches/9001/confirm-line' && method === 'POST') {
      const body = JSON.parse(request.postData() || '{}');
      confirmRequests.push(body);
      const line = lines.find((l) => l.id === body.move_line_id);
      if (line) line.picked = true;
      const done = lines.filter((l) => l.picked).length;
      return json(200, {
        success: true, recorded_serial: body.serial_number || '',
        progress: { total: lines.length, done, ratio: done / lines.length },
      });
    }
    if (path === '/api/cluster/batches/9001/validate' && method === 'POST') {
      validated = true;
      return json(200, { success: true, batch_complete: true, message: 'Batch abgeschlossen.' });
    }
    return json(404, { detail: `${method} ${path} nicht gemockt` });
  });

  return { getConfirmRequests: () => confirmRequests };
}

async function enterCluster(page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Lena Lager' }).click();
  await page.locator('[data-cluster-start]').first().click();
  await expect(page.getByText('Batch zusammenstellen')).toBeVisible();
}

// #8: Wizard / pending_action: validate returns pending_action -> error toast, button re-enabled.
test('Cluster-Validate: pending_action wizard zeigt Fehler-Toast und entsperrt Button', async ({ page }) => {
  await mockPwaApi(page);
  await mockClusterApi(page);

  // Override the validate endpoint to return a pending_action (wizard) response.
  await page.route('**/api/cluster/batches/9001/validate', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: false,
        batch_complete: false,
        pending_action: 'stock.backorder.confirmation',
        message: 'Batch-Abschluss erfordert eine manuelle Bestätigung in Odoo (stock.backorder.confirmation).',
      }),
    });
  });

  await enterCluster(page);
  await page.getByRole('button', { name: 'Übernehmen' }).first().click();
  await page.locator('[data-cluster-confirm]').click();

  // Mark all lines as done so the validate button is enabled.
  await page.locator('[data-stop-confirm="5001"]').click();
  await page.locator('[data-carton-pick="1001"]').click();
  await page.locator('[data-stop-confirm="5002"]').click();
  await page.locator('[data-carton-pick="1002"]').click();
  await page.locator('#serial-input').fill('SN-TEST-W');
  await page.locator('#serial-confirm').click();

  const validateBtn = page.locator('[data-cluster-validate]');
  await expect(validateBtn).toBeEnabled();
  await validateBtn.click();

  // Error toast with supervisor escalation message must appear.
  await expect(page.getByText('Bitte Vorgesetzte:n informieren')).toBeVisible();

  // Button must be re-enabled so the picker can retry or escalate.
  await expect(validateBtn).toBeEnabled();
});

test('Cluster-Flow: Auswahl -> Rundgang -> Serial -> Abschluss', async ({ page }) => {
  await mockPwaApi(page);
  const cluster = await mockClusterApi(page);

  await enterCluster(page);

  // Vorschlag uebernehmen -> beide Auftraege ausgewaehlt
  await page.getByRole('button', { name: 'Übernehmen' }).first().click();
  const startBtn = page.locator('[data-cluster-confirm]');
  await expect(startBtn).toContainText('(2)');

  // Batch starten -> Rundgang
  await startBtn.click();
  await expect(page.locator('.cluster-progress__count')).toHaveText('0 / 2');
  await expect(page.locator('.cluster-box-chip').first()).toBeVisible();
  await expect(page.getByText('CLUSTER-B1/WH/INT/00007').first()).toBeVisible();

  // Erste (nicht-serielle) Position: zuerst Empfaengerkarton bestaetigen
  await page.locator('[data-stop-confirm="5001"]').click();
  await expect(page.locator('#carton-title')).toBeVisible();
  await page.locator('[data-carton-pick="1001"]').click();
  await expect(page.locator('.cluster-progress__count')).toHaveText('1 / 2');

  // Zweite Position: Karton bestaetigen, dann Serial-Modal (serialisiert)
  await page.locator('[data-stop-confirm="5002"]').click();
  await page.locator('[data-carton-pick="1002"]').click();
  await expect(page.locator('#serial-input')).toBeVisible();
  await page.locator('#serial-input').fill('SN-CLUSTER-1');
  await page.locator('#serial-confirm').click();
  await expect(page.locator('.cluster-progress__count')).toHaveText('2 / 2');

  // Batch abschliessen
  const validateBtn = page.locator('[data-cluster-validate]');
  await expect(validateBtn).toBeEnabled();
  await validateBtn.click();
  await expect(page.getByText('fertig')).toBeVisible();

  // Serial wurde fuer die serialisierte Position uebergeben
  const requests = cluster.getConfirmRequests();
  expect(requests).toHaveLength(2);
  expect(requests.find((r) => r.move_line_id === 5002)).toMatchObject({
    picking_id: 1002, serial_number: 'SN-CLUSTER-1',
  });
});

// Verwechslungsschutz (Akzeptanz #4): falscher Empfaengerkarton -> Warnung, kein Confirm.
test('Cluster-Karton: falscher Karton warnt und blockiert, richtiger geht durch', async ({ page }) => {
  await mockPwaApi(page);
  const cluster = await mockClusterApi(page);

  await enterCluster(page);
  await page.getByRole('button', { name: 'Übernehmen' }).first().click();
  await page.locator('[data-cluster-confirm]').click();

  // Position 5001 (Auftrag 1001) bestaetigen, aber FALSCHEN Karton (Auftrag 1002) tippen
  await page.locator('[data-stop-confirm="5001"]').click();
  await expect(page.locator('#carton-title')).toBeVisible();
  await page.locator('[data-carton-pick="1002"]').click();

  // Warnung erscheint, Modal bleibt offen, Fortschritt unveraendert, KEIN confirm-Request
  await expect(page.locator('#carton-warning')).toBeVisible();
  await expect(page.locator('#carton-title')).toBeVisible();
  await expect(page.locator('.cluster-progress__count')).toHaveText('0 / 2');
  expect(cluster.getConfirmRequests()).toHaveLength(0);

  // Richtigen Karton tippen -> Bestaetigung geht durch
  await page.locator('[data-carton-pick="1001"]').click();
  await expect(page.locator('.cluster-progress__count')).toHaveText('1 / 2');
  const reqs = cluster.getConfirmRequests();
  expect(reqs).toHaveLength(1);
  expect(reqs[0]).toMatchObject({ move_line_id: 5001, scanned_package: 'CLUSTER-B1/WH/INT/00007' });
});
