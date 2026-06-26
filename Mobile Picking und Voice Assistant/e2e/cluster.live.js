/**
 * LIVE end-to-end cluster click-through against the REAL running stack.
 *
 * Unlike e2e/cluster.spec.js (mocked API), this drives the actual PWA at
 * https://localhost (Caddy -> FastAPI backend -> Odoo masterfischer) with NO
 * route mocking. It logs in as a picker, builds a multi-order cluster batch,
 * walks + confirms every line, validates the whole batch, and asserts the
 * completion screen. Screenshots + video are written to .claude/artifacts.
 *
 * Run:  node e2e/cluster.live.js
 * Env:  LIVE_BASE_URL (default https://localhost), HEADED=0 to run headless,
 *       PICK_IDS="323,347" to choose which open pickings to bundle.
 */
const { chromium, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const BASE = process.env.LIVE_BASE_URL || 'https://localhost';
const HEADED = process.env.HEADED !== '0';
const PICK_IDS = (process.env.PICK_IDS || '323,347').split(',').map((s) => s.trim()).filter(Boolean);
const OUT = path.join(__dirname, '..', '.claude', 'artifacts', 'cluster-live');
fs.mkdirSync(OUT, { recursive: true });

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

  const result = { ok: false, step: 'start', batchName: null, confirmed: 0, errors: [] };
  try {
    console.log(`▶ LIVE cluster test against ${BASE} (pickings ${PICK_IDS.join('+')})`);

    // 1) Login: pick a picker
    result.step = 'login';
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('[data-picker-id]').first().waitFor({ timeout: 20_000 });
    await shot(page, 'login');
    const max = page.locator('[data-picker-id="7"]');
    if (await max.count()) await max.click(); else await page.locator('[data-picker-id]').first().click();

    // 2) Reach the queue/list; dismiss any zone modal; open cluster mode
    result.step = 'open-cluster';
    await page.locator('[data-cluster-start]').first().waitFor({ timeout: 20_000 });
    await dismissBlockers(page);
    await shot(page, 'queue');
    await page.locator('[data-cluster-start]').first().click();

    // 3) Cluster select: either via auto-suggestion (SUGGEST_ZONE) or manual pick ids
    result.step = 'select';
    await page.getByText('Batch zusammenstellen').waitFor({ timeout: 15_000 });
    await shot(page, 'cluster-select');
    const ZONE = process.env.SUGGEST_ZONE;
    if (ZONE) {
      const apply = page.locator(`[data-suggestion-zone="${ZONE}"]`).getByRole('button', { name: 'Übernehmen' });
      await apply.first().click();
      result.entry = `suggestion:${ZONE}`;
    } else {
      for (const id of PICK_IDS) {
        const pick = page.locator(`[data-cluster-pick-id="${id}"]`);
        await pick.waitFor({ timeout: 10_000 });
        await pick.click();
      }
      result.entry = `manual:${PICK_IDS.join('+')}`;
    }
    const startBtn = page.locator('[data-cluster-confirm]');
    await expect(startBtn).toBeEnabled({ timeout: 5_000 });
    await shot(page, 'cluster-selected');

    // 4) Start batch -> walk view
    result.step = 'walk';
    await startBtn.click();
    await page.locator('.cluster-progress__count').waitFor({ timeout: 20_000 });
    await page.locator('.cluster-box-chip').first().waitFor({ timeout: 10_000 });
    const batchTitle = await page.locator('.cluster-progress__title').first().textContent().catch(() => '');
    result.batchName = (batchTitle || '').trim();
    console.log(`  batch: ${result.batchName} | progress ${await page.locator('.cluster-progress__count').textContent()}`);
    await shot(page, 'walk-start');

    // 5) Confirm every stop (DOM re-renders after each confirm via loadBatch)
    result.step = 'confirm';
    for (let i = 0; i < 40; i++) {
      const btns = page.locator('[data-stop-confirm]');
      const n = await btns.count();
      if (n === 0) break;
      await btns.first().scrollIntoViewIfNeeded().catch(() => {});
      await btns.first().click();
      // A serial/lot line would pop the serial modal; fill it if present.
      const serialInput = page.locator('#serial-input');
      if (await serialInput.isVisible().catch(() => false)) {
        await serialInput.fill(`SN-LIVE-${i + 1}`);
        await page.locator('#serial-confirm').click();
      }
      await page.waitForLoadState('networkidle').catch(() => {});
      await page.waitForTimeout(500);
      result.confirmed = i + 1;
    }
    const finalCount = await page.locator('.cluster-progress__count').textContent().catch(() => '?');
    console.log(`  confirmed lines; progress now ${finalCount}`);
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
    result.ok = true;
    console.log('✅ LIVE cluster flow completed end-to-end.');
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
