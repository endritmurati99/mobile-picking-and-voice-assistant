const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');
const { login } = require('./helpers/login');

// Stateful Cluster-API-Mock: getBatch spiegelt die picked-Flags wider, die
// confirm-line setzt, damit der Fortschritt im Rundgang real hochzaehlt.
async function mockClusterApi(page, options = {}) {
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
  if (options.missingFirstPackage) {
    delete lines[0].package_name;
  }
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
        {
          picking_id: 1001, picking_name: 'WH/INT/00007', box_index: 1, box_color: '#A299FF',
          ...(options.missingFirstPackage ? {} : { package_name: 'CLUSTER-B1/WH/INT/00007' }),
        },
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
      return json(200, [
        {
          zone: 'Lager Links', picking_ids: [1001, 1002],
          order_count: 2, line_count: 2,
          picking_names: ['WH/INT/00007', 'WH/INT/00008'],
          delivery_date: '2026-07-09', score: 85,
          reasons: ['Ausliefertag 2026-07-09', 'Zone Lager Links', '1 gemeinsame Produkte'],
          warnings: ['2 Aufträge sind gültig, empfohlen sind 4-8.'], product_overlap_count: 1,
        },
        {
          zone: 'Lager Rechts', picking_ids: [1003, 1004],
          order_count: 2, line_count: 5,
          picking_names: ['WH/INT/00009', 'WH/INT/00010'],
          delivery_date: '2026-07-09', score: 75,
          reasons: ['Ausliefertag 2026-07-09', 'Zone Lager Rechts'], warnings: [], product_overlap_count: 0,
        },
        {
          zone: 'Hochregal', picking_ids: [1005, 1006],
          order_count: 2, line_count: 4,
          picking_names: ['WH/INT/00011', 'WH/INT/00012'],
          delivery_date: '2026-07-10', score: 70,
          reasons: ['Ausliefertag 2026-07-10', 'Zone Hochregal'], warnings: [], product_overlap_count: 0,
        },
      ]);
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
    if (path === '/api/cluster/batches/active' && method === 'GET') {
      // Kein laufender Batch beim Betreten des Cluster-Modus -> Auswahl anzeigen.
      return json(200, null);
    }
    return json(404, { detail: `${method} ${path} nicht gemockt` });
  });

  return { getConfirmRequests: () => confirmRequests };
}

async function enterCluster(page) {
  await login(page);
  await page.locator('[data-cluster-start]').first().click();
  await expect(page.getByText('Cluster zusammenstellen')).toBeVisible();
}

// Simuliert einen HID-Barcode-Scanner (pwa/js/scanner.js initHIDScanner):
// Zeichen als schnelle keydown-Events, abgeschlossen mit Enter. Der Listener
// haengt am `document` und ignoriert Tastatureingaben, solange ein
// input/textarea/select fokussiert ist -- deshalb hier erst den Fokus loesen.
async function scanBarcode(page, barcode) {
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  });
  await page.keyboard.type(barcode, { delay: 0 });
  await page.keyboard.press('Enter');
}

// Fuer ungetrackte Positionen (tracking:'none') ist der Confirm-Button erst
// bedienbar, nachdem der Artikel-Barcode verifiziert wurde (pwa/js/app.js
// syncClusterScanState()/handleClusterScan()) -- entweder per Scan oder per
// "Ohne Scan manuell" (`data-stop-manual`). Ohne das bleibt der Button
// disabled und zeigt "Gesperrt".
async function verifyClusterStopByScan(page, lineId, productBarcode) {
  await scanBarcode(page, productBarcode);
  await expect(page.locator(`[data-stop-confirm="${lineId}"]`)).toBeEnabled();
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
  await page.getByRole('button', { name: 'Vorschlag wählen' }).first().click();
  await page.locator('[data-cluster-confirm]').click();

  // Mark all lines as done so the validate button is enabled.
  await verifyClusterStopByScan(page, 5001, '4006381333931');
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
  await page.getByRole('button', { name: 'Vorschlag wählen' }).first().click();
  const startBtn = page.locator('[data-cluster-confirm]');
  await expect(startBtn).toContainText('(2/8)');

  // Batch starten -> Rundgang
  await startBtn.click();
  await expect(page.locator('.cluster-progress__count')).toHaveText('0 / 2');
  await expect(page.locator('.cluster-box-chip').first()).toBeVisible();
  await expect(page.getByText('CLUSTER-B1/WH/INT/00007').first()).toBeVisible();

  // Erste (nicht-serielle) Position: erst Artikel scannen, dann Empfaengerkarton bestaetigen
  await verifyClusterStopByScan(page, 5001, '4006381333931');
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
  await page.getByRole('button', { name: 'Vorschlag wählen' }).first().click();
  await page.locator('[data-cluster-confirm]').click();

  // Position 5001 (Auftrag 1001) bestaetigen, aber FALSCHEN Karton (Auftrag 1002) tippen
  await verifyClusterStopByScan(page, 5001, '4006381333931');
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

test('Cluster-Vorschlag kann ausgewählt und wieder entfernt werden', async ({ page }) => {
  await mockPwaApi(page);
  await mockClusterApi(page);

  await enterCluster(page);
  const firstSuggestion = page.locator('[data-suggestion-index="0"]');
  await firstSuggestion.getByRole('button').click();
  await expect(firstSuggestion).toHaveClass(/cluster-suggestion--selected/);
  await expect(page.locator('[data-cluster-confirm]')).toContainText('(2/8)');
  await firstSuggestion.getByRole('button').click();
  await expect(firstSuggestion).not.toHaveClass(/cluster-suggestion--selected/);
  await expect(page.locator('[data-cluster-confirm]')).toBeDisabled();
});

test('mehrere kompatible Vorschläge werden kombiniert und anderer Liefertag gesperrt', async ({ page }) => {
  await mockPwaApi(page);
  await mockClusterApi(page);
  await enterCluster(page);

  await page.locator('[data-suggestion-index="0"] button').click();
  await page.locator('[data-suggestion-index="1"] button').click();

  await expect(page.locator('[data-cluster-confirm]')).toContainText('(4/8)');
  await expect(page.locator('[data-suggestion-index="2"] button')).toBeDisabled();
  await expect(page.locator('[data-suggestion-index="2"] button')).toHaveText('Anderer Liefertag');
});

test('Cluster-Vorschlag zeigt fachliche Gruende', async ({ page }) => {
  await mockPwaApi(page);
  await mockClusterApi(page);

  await enterCluster(page);

  await expect(page.getByText(/Ausliefertag/i).first()).toBeVisible();
  await expect(page.getByText(/gemeinsame Produkte/i).first()).toBeVisible();
  await expect(page.getByText(/separater Karton/i)).toBeVisible();
  await expect(page.getByText('Vorschlag 1')).toBeVisible();
  await expect(page.getByText('Offene Aufträge')).toHaveCount(0);
});

test('Cluster-Karton: fehlender Zielkarton blockiert Confirm', async ({ page }) => {
  await mockPwaApi(page);
  const cluster = await mockClusterApi(page, { missingFirstPackage: true });

  await enterCluster(page);
  await page.getByRole('button', { name: 'Vorschlag wählen' }).first().click();
  await page.locator('[data-cluster-confirm]').click();

  await verifyClusterStopByScan(page, 5001, '4006381333931');
  await page.locator('[data-stop-confirm="5001"]').click();
  await expect(page.getByText(/Zielkarton fehlt/i)).toBeVisible();
  expect(cluster.getConfirmRequests()).toHaveLength(0);
});

// Neu (siehe Coordinator-Auftrag): beweist genau das Feature, das die
// obigen Tests jetzt beruecksichtigen -- ohne Scan/manuelle Freigabe bleibt
// der Confirm-Button einer ungetrackten Position gesperrt, ein falscher Scan
// bucht nichts, und erst der richtige Barcode schaltet frei.
test('Cluster-Stop bleibt ohne Scan oder manuelle Freigabe gesperrt', async ({ page }) => {
  await mockPwaApi(page);
  await mockClusterApi(page);

  await enterCluster(page);
  await page.getByRole('button', { name: 'Vorschlag wählen' }).first().click();
  await page.locator('[data-cluster-confirm]').click();

  const confirmBtn = page.locator('[data-stop-confirm="5001"]');
  await expect(confirmBtn).toBeDisabled();
  await expect(confirmBtn).toHaveText('Gesperrt');

  // Falscher Scan bucht nichts und laesst die Position gesperrt.
  await scanBarcode(page, 'FALSCHER-BARCODE-0000');
  await expect(page.getByText('Falscher Artikel. Es wurde nichts gebucht.')).toBeVisible();
  await expect(confirmBtn).toBeDisabled();
  await expect(confirmBtn).toHaveText('Gesperrt');

  // Richtiger Scan verifiziert den Artikel und schaltet den Confirm-Button frei.
  await scanBarcode(page, '4006381333931');
  await expect(page.getByText('Artikel geprüft. Jetzt den Zielkarton scannen.')).toBeVisible();
  await expect(confirmBtn).toBeEnabled();
  await expect(confirmBtn).toHaveText('Manuell');
});

// Alternative Freigabe zum Scan: der explizite "Ohne Scan manuell"-Button
// (data-stop-manual) umgeht die Scan-Pflicht und oeffnet direkt den
// Kartonwaehler -- der dokumentierte Ausweg, wenn der Barcode fehlt/kaputt ist.
test('Cluster-Stop: "Ohne Scan manuell" oeffnet den Kartonwaehler ohne vorherigen Scan', async ({ page }) => {
  await mockPwaApi(page);
  const cluster = await mockClusterApi(page);

  await enterCluster(page);
  await page.getByRole('button', { name: 'Vorschlag wählen' }).first().click();
  await page.locator('[data-cluster-confirm]').click();

  await expect(page.locator('[data-stop-confirm="5001"]')).toBeDisabled();
  await page.locator('[data-stop-manual="5001"]').click();
  await expect(page.locator('#carton-title')).toBeVisible();
  await page.locator('[data-carton-pick="1001"]').click();

  await expect(page.locator('.cluster-progress__count')).toHaveText('1 / 2');
  expect(cluster.getConfirmRequests()).toHaveLength(1);
});
