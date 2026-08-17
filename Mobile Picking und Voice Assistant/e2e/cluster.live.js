/**
 * LIVE end-to-end cluster click-through against the REAL running stack.
 *
 * Unlike e2e/cluster.spec.js (mocked API), this drives the actual PWA at
 * https://localhost (Caddy -> FastAPI backend -> Odoo masterfischer_o19) with NO
 * route mocking. It logs in as a picker, builds a multi-order cluster batch,
 * walks + confirms every line, validates the whole batch, and asserts the
 * completion screen. Screenshots + video are written to .claude/artifacts.
 *
 * Run:  LIVE_CLUSTER_CONFIRM=1 node e2e/cluster.live.js
 * Env:  LIVE_BASE_URL (default https://localhost), HEADED=0 to run headless,
 *       SUGGEST_ZONE to choose a suggested zone (otherwise the first suggestion),
 *       ODOO_URL/ODOO_DB and optional ODOO_LOGIN/ODOO_PASSWORD for verification.
 */
const { chromium, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const BASE = process.env.LIVE_BASE_URL || 'https://localhost';
const HEADED = process.env.HEADED !== '0';
const LOGIN = process.env.PWA_LOGIN || 'lena.lager';
const PASSWORD = process.env.PWA_PASSWORD || 'admin';
const ODOO_URL = (process.env.ODOO_URL || 'http://127.0.0.1:8069').replace(/\/$/, '');
const ODOO_DB = process.env.ODOO_DB || 'masterfischer_o19';
const ODOO_LOGIN = process.env.ODOO_LOGIN || LOGIN;
const ODOO_PASSWORD = process.env.ODOO_PASSWORD || PASSWORD;
const OUT = path.join(__dirname, '..', '.claude', 'artifacts', 'cluster-live');
fs.mkdirSync(OUT, { recursive: true });

if (process.env.LIVE_CLUSTER_CONFIRM !== '1') {
  console.error('Refusing destructive live test. Set LIVE_CLUSTER_CONFIRM=1 explicitly.');
  process.exit(2);
}

async function odooRpc(service, method, args) {
  const response = await fetch(`${ODOO_URL}/jsonrpc`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0', method: 'call', id: `${Date.now()}-${Math.random()}`,
      params: { service, method, args },
    }),
  });
  if (!response.ok) throw new Error(`Odoo JSON-RPC returned HTTP ${response.status}`);
  const body = await response.json();
  if (body.error) throw new Error(body.error?.data?.message || body.error?.message || 'Odoo JSON-RPC error');
  if (!Object.hasOwn(body, 'result')) throw new Error('Odoo JSON-RPC returned no result');
  return body.result;
}

async function verifyBatchInOdoo(batchId) {
  const uid = await odooRpc('common', 'authenticate', [
    ODOO_DB, ODOO_LOGIN, ODOO_PASSWORD, { interactive: true },
  ]);
  if (!uid) throw new Error(`Odoo login failed for ${ODOO_LOGIN}@${ODOO_DB}`);

  const execute = (model, method, args, kwargs = {}) => odooRpc('object', 'execute_kw', [
    ODOO_DB, uid, ODOO_PASSWORD, model, method, args, kwargs,
  ]);
  const [batch] = await execute('stock.picking.batch', 'search_read', [
    [['id', '=', batchId]],
  ], { fields: ['id', 'name', 'state', 'picking_ids'], limit: 1 });
  if (!batch) throw new Error(`Odoo batch ${batchId} not found`);
  if (batch.state !== 'done') throw new Error(`Odoo batch ${batchId} state is ${batch.state}, expected done`);
  if (!Array.isArray(batch.picking_ids) || batch.picking_ids.length < 2) {
    throw new Error(`Odoo batch ${batchId} contains fewer than two pickings`);
  }

  const pickings = await execute('stock.picking', 'search_read', [
    [['id', 'in', batch.picking_ids]],
  ], { fields: ['id', 'name', 'state'], limit: batch.picking_ids.length });
  const open = pickings.filter((picking) => picking.state !== 'done');
  if (open.length) throw new Error(`Pickings not done: ${open.map((p) => p.name).join(', ')}`);

  const lines = await execute('stock.move.line', 'search_read', [
    [['picking_id', 'in', batch.picking_ids]],
  ], { fields: ['picking_id', 'result_package_id'], limit: 500 });
  const packageByPicking = new Map();
  for (const line of lines) {
    const pickingId = line.picking_id?.[0];
    const packageId = line.result_package_id?.[0];
    const packageName = line.result_package_id?.[1];
    if (!pickingId || !packageId) throw new Error(`Move line without target package in batch ${batchId}`);
    const previous = packageByPicking.get(pickingId);
    if (previous && previous.id !== packageId) {
      throw new Error(`Picking ${pickingId} uses multiple target packages`);
    }
    packageByPicking.set(pickingId, { id: packageId, name: packageName });
  }
  if (packageByPicking.size !== batch.picking_ids.length) {
    throw new Error(`Expected one packaged result for each of ${batch.picking_ids.length} pickings`);
  }
  const packageIds = [...packageByPicking.values()].map((pkg) => pkg.id);
  if (new Set(packageIds).size !== packageIds.length) {
    throw new Error('Two pickings share the same target package');
  }
  return {
    batchId: batch.id,
    batchName: batch.name,
    state: batch.state,
    pickingCount: batch.picking_ids.length,
    packages: [...packageByPicking.values()].map((pkg) => pkg.name),
  };
}

let shotN = 0;
async function shot(page, label) {
  const file = path.join(OUT, `${String(++shotN).padStart(2, '0')}-${label}.png`);
  await page.screenshot({ path: file, fullPage: false }).catch(() => {});
  console.log(`  📸 ${path.basename(file)}`);
}

async function dismissBlockers(page) {
  // Best-effort: a zone-preference modal can appear on first list load.
  for (const sel of ['#zone-picker-cancel']) {
    const el = page.locator(sel);
    if (await el.count().catch(() => 0)) {
      if (await el.first().isVisible().catch(() => false)) {
        await el.first().click().catch(() => {});
      }
    }
  }
}

(async () => {
  const browser = await chromium.launch({ headless: !HEADED, slowMo: HEADED ? 250 : 0 });
  const context = await browser.newContext({
    baseURL: BASE,
    ignoreHTTPSErrors: true,
    viewport: { width: 412, height: 915 },
    deviceScaleFactor: 2,
    serviceWorkers: 'block',
    recordVideo: { dir: path.join(OUT, 'video'), size: { width: 412, height: 915 } },
  });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message));

  const result = {
    ok: false, step: 'start', batchId: null, batchName: null,
    orderCount: 0, confirmed: 0, odoo: null, errors: [],
  };
  try {
    console.log(`▶ LIVE cluster test against ${BASE}`);

    // 1) Login mit denselben Odoo-Zugangsdaten, die auch im Odoo-Web gelten.
    result.step = 'login';
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('#login-user').waitFor({ timeout: 20_000 });
    await shot(page, 'login');
    await page.locator('#login-user').fill(LOGIN);
    await page.locator('#login-password').fill(PASSWORD);
    await page.locator('#login-submit').click();

    // 2) Reach the queue/list; dismiss any zone modal; open cluster mode
    result.step = 'open-cluster';
    await page.locator('[data-cluster-start]').first().waitFor({ timeout: 20_000 });
    await dismissBlockers(page);
    await shot(page, 'queue');
    await page.locator('[data-cluster-start]').first().click();

    // 3) Cluster select: either via auto-suggestion (SUGGEST_ZONE) or manual pick ids
    result.step = 'select';
    await page.getByText('Cluster zusammenstellen').waitFor({ timeout: 15_000 });
    await shot(page, 'cluster-select');
    const ZONE = process.env.SUGGEST_ZONE;
    if (ZONE) {
      const apply = page.locator(`[data-suggestion-zone="${ZONE}"]`).getByRole('button', { name: 'Vorschlag wählen' });
      await apply.first().click();
      result.entry = `suggestion:${ZONE}`;
    } else {
      await page.getByRole('button', { name: 'Vorschlag wählen' }).first().click();
      result.entry = 'suggestion:first';
    }
    const startBtn = page.locator('[data-cluster-confirm]');
    await expect(startBtn).toBeEnabled({ timeout: 5_000 });
    await shot(page, 'cluster-selected');

    // 4) Start batch -> walk view
    result.step = 'walk';
    const [createResponse] = await Promise.all([
      page.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.request().method() === 'POST' && url.pathname === '/api/cluster/batches';
      }, { timeout: 20_000 }),
      startBtn.click(),
    ]);
    if (!createResponse.ok()) {
      throw new Error(`Batch creation returned HTTP ${createResponse.status()}: ${await createResponse.text()}`);
    }
    const createdBatch = await createResponse.json();
    result.batchId = Number(createdBatch.batch_id);
    result.orderCount = Array.isArray(createdBatch.boxes) ? createdBatch.boxes.length : 0;
    if (!Number.isInteger(result.batchId) || result.orderCount < 2) {
      throw new Error('Batch creation did not return a valid batch with at least two orders');
    }
    await page.locator('.cluster-progress__count').waitFor({ timeout: 20_000 });
    await page.locator('.cluster-box-chip').first().waitFor({ timeout: 10_000 });
    const batchTitle = await page.locator('.cluster-progress__title').first().textContent().catch(() => '');
    result.batchName = (batchTitle || '').trim();
    console.log(`  batch: ${result.batchName} | progress ${await page.locator('.cluster-progress__count').textContent()}`);
    await shot(page, 'walk-start');

    // 5) Confirm every stop, progress-driven (each confirm re-renders via loadBatch).
    //    For every stop: Empfaengerkarton bestaetigen (richtige picking_id), dann ggf. Serial.
    result.step = 'confirm';
    const countLoc = page.locator('.cluster-progress__count');
    const parseCount = async () => {
      const t = (await countLoc.textContent().catch(() => '')) || '';
      const m = t.match(/(\d+)\s*\/\s*(\d+)/);
      return m ? { done: +m[1], total: +m[2] } : { done: 0, total: 0 };
    };
    let { done, total } = await parseCount();
    if (total < 1) throw new Error('Cluster contains no pickable lines');
    let safety = 0;
    while (total > 0 && done < total && safety++ < total + 5) {
      const btn = page.locator('[data-stop-confirm]').first();
      await btn.waitFor({ state: 'visible', timeout: 10_000 });
      const article = btn.locator('xpath=ancestor::*[@data-stop-picking][1]');
      const pickingId = await article.getAttribute('data-stop-picking').catch(() => null);
      await btn.scrollIntoViewIfNeeded().catch(() => {});
      await btn.click();
      // Empfaengerkarton-Bestaetigung: den RICHTIGEN Karton (gleiche picking_id) tappen.
      const cartonTitle = page.locator('#carton-title');
      await cartonTitle.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {});
      if (await cartonTitle.isVisible().catch(() => false)) {
        const choice = pickingId
          ? page.locator(`[data-carton-pick="${pickingId}"]`).first()
          : page.locator('[data-carton-pick]').first();
        await choice.click();
      }
      // A serial/lot line would pop the serial modal; fill it if present.
      const serialInput = page.locator('#serial-input');
      if (await serialInput.isVisible().catch(() => false)) {
        await serialInput.fill(`SN-LIVE-${Date.now()}-${safety}`);
        await page.locator('#serial-confirm').click();
      }
      // Deterministically wait for the progress counter to advance by one.
      await expect(countLoc).toHaveText(`${done + 1} / ${total}`, { timeout: 15_000 });
      ({ done, total } = await parseCount());
      result.confirmed = done;
    }
    console.log(`  confirmed lines; progress now ${done} / ${total}`);
    await shot(page, 'walk-all-confirmed');

    // 6) Validate the whole batch
    result.step = 'validate';
    const validateBtn = page.locator('[data-cluster-validate]');
    await expect(validateBtn).toBeEnabled({ timeout: 15_000 });
    await validateBtn.click();

    // 7) Completion screen
    result.step = 'complete';
    await page.locator('.cluster-complete').waitFor({ timeout: 20_000 });
    await expect(page.getByText('fertig')).toBeVisible({ timeout: 5_000 });
    await shot(page, 'complete');

    // 8) Unabhaengige Postcondition direkt in Odoo: der grüne Screen allein
    // beweist weder action_done noch getrennte Ziel-Packages je Auftrag.
    result.step = 'verify-odoo';
    result.odoo = await verifyBatchInOdoo(result.batchId);
    if (consoleErrors.length) throw new Error(`Browser console errors: ${consoleErrors.join(' | ')}`);
    result.ok = true;
    console.log(`  Odoo: ${result.odoo.batchName}, ${result.odoo.pickingCount} pickings, ${result.odoo.packages.length} packages`);
    console.log('✅ LIVE cluster flow completed and verified in Odoo.');
  } catch (err) {
    result.errors.push(`${result.step}: ${err.message}`);
    console.error(`❌ FAILED at step "${result.step}": ${err.message}`);
    await shot(page, `FAIL-${result.step}`);
    const txt = await page.locator('body').innerText().catch(() => '');
    fs.writeFileSync(path.join(OUT, 'fail-page.txt'), txt);
  } finally {
    if (consoleErrors.length) {
      result.errors.push(...consoleErrors.map((e) => 'console: ' + e));
      console.log(`  console errors (${consoleErrors.length}):`);
      consoleErrors.slice(0, 10).forEach((e) => console.log('    - ' + e));
    }
    fs.writeFileSync(path.join(OUT, 'result.json'), JSON.stringify(result, null, 2));
    await context.close();
    await browser.close();
    console.log(`RESULT: ${JSON.stringify(result)}`);
    process.exit(result.ok ? 0 : 1);
  }
})();
