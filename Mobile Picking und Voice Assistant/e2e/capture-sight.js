const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('playwright');
const { mockPwaApi } = require('./helpers/pwa-api');

const PROJECT_ROOT = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(PROJECT_ROOT, '..');
const ARTIFACTS_DIR = path.join(REPO_ROOT, '.claude', 'artifacts');

const baseURL = process.env.VISUAL_BASE_URL || 'http://127.0.0.1:4173';
const routePath = process.env.VISUAL_ROUTE || '/';
const viewName = (process.env.VISUAL_VIEW || 'all').toLowerCase();
const rootSelector = process.env.VISUAL_SELECTOR || '#app';
const timeoutMs = Number(process.env.VISUAL_TIMEOUT_MS || 10000);
const useLiveApi = process.env.VISUAL_USE_LIVE_API === '1';
const targetUrl = new URL(routePath, baseURL).toString();
const baseUrlObject = new URL(baseURL);
const startStaticServer =
  baseUrlObject.protocol === 'http:' &&
  ['127.0.0.1', 'localhost'].includes(baseUrlObject.hostname) &&
  String(baseUrlObject.port || '80') === '4173';

async function selectPickerIfNeeded(page) {
  const pickerButton = page.locator('.picker-option').first();
  const isPickerScreen = await pickerButton.isVisible().catch(() => false);
  if (isPickerScreen) {
    await pickerButton.click();
    await page.locator('.pick-list-card[data-id]').first().waitFor({ state: 'visible', timeout: timeoutMs });
  }
}

const VIEW_CONFIGS = {
  list: {
    readyDescription: 'Picking-Liste ist geladen',
    selectors: ['#main', '.pick-list-card[data-id], .pick-card[data-id]'],
    action: async (page) => {
      await selectPickerIfNeeded(page);
    },
  },
  detail: {
    readyDescription: 'Picking-Detail mit bestaetigbarer Zeile ist sichtbar',
    selectors: ['#main .detail-compact', '#main .btn-confirm'],
    action: async (page) => {
      await selectPickerIfNeeded(page);
      const firstPicking = page.locator('.pick-list-card[data-id], .pick-card[data-id]').first();
      await firstPicking.waitFor({ state: 'visible', timeout: timeoutMs });
      await firstPicking.click();
    },
  },
  alert: {
    readyDescription: 'Quality-Alert-Formular ist sichtbar',
    selectors: ['#qa-description', '#qa-priority', '#qa-submit'],
    action: async (page) => {
      await selectPickerIfNeeded(page);
      const firstPicking = page.locator('.pick-list-card[data-id], .pick-card[data-id]').first();
      await firstPicking.waitFor({ state: 'visible', timeout: timeoutMs });
      await firstPicking.click();
      const alertButton = page.locator('#btn-alert');
      await alertButton.waitFor({ state: 'visible', timeout: timeoutMs });
      await alertButton.click();
    },
  },
};

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function isReachable(url) {
  try {
    const response = await fetch(url, { redirect: 'follow' });
    return response.status < 500;
  } catch {
    return false;
  }
}

async function waitForUrl(url, timeout) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeout) {
    if (await isReachable(url)) {
      return;
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function ensureStaticServer() {
  if (!startStaticServer) {
    return null;
  }

  if (await isReachable(baseURL)) {
    return null;
  }

  const server = spawn(
    process.env.PYTHON || 'python',
    ['-m', 'http.server', baseUrlObject.port || '4173', '--directory', 'pwa'],
    {
      cwd: PROJECT_ROOT,
      stdio: 'ignore',
      windowsHide: true,
    }
  );

  await Promise.race([
    waitForUrl(baseURL, timeoutMs),
    new Promise((_, reject) => server.once('error', reject)),
  ]);

  return server;
}

function stopServer(server) {
  if (!server || server.killed) {
    return;
  }
  server.kill();
}

async function waitForAppShell(page) {
  await page.goto(targetUrl, { waitUntil: 'networkidle' });
  await page.waitForSelector(rootSelector, { state: 'visible', timeout: timeoutMs });
  await page.waitForFunction(
    ({ selector }) => {
      const root = document.querySelector(selector);
      if (!root) {
        return false;
      }
      const text = root.textContent || '';
      return text.trim().length > 0 && !/Wird geladen/i.test(text);
    },
    { selector: rootSelector },
    { timeout: timeoutMs }
  );
}

async function waitForSemanticReadyState(page, requestedView, readySelectors) {
  const checks = [];
  for (const selector of readySelectors) {
    await page.waitForSelector(selector, { state: 'visible', timeout: timeoutMs });
    checks.push({
      selector,
      state: 'visible',
    });
  }

  const mainText = await page.locator('#main').innerText();
  if (/Wird geladen/i.test(mainText)) {
    throw new Error(`View ${requestedView} ist nicht im Ready-State: Ladezustand noch sichtbar.`);
  }

  if (requestedView === 'list') {
    await page.waitForFunction(() => {
      const status = document.querySelector('#status-indicator');
      if (!status) return false;
      const text = (status.textContent || '').trim();
      const isOnline = status.classList.contains('online') && text === 'Online';
      const isOffline = status.classList.contains('offline') && text === 'Offline';
      return isOnline || isOffline;
    }, { timeout: timeoutMs });
    checks.push({
      selector: '#status-indicator',
      state: 'network-status-settled',
    });
  }

  return checks;
}

function getOutputPath(requestedView) {
  const outputName = process.env.VISUAL_OUTPUT || `ui_state-${requestedView}.png`;
  return path.join(ARTIFACTS_DIR, outputName);
}

async function writeMetadata(requestedView, screenshotPath, readyChecks) {
  const metadataPath = screenshotPath.replace(/\.png$/i, '.json');
  const metadata = {
    capturedAt: new Date().toISOString(),
    outputPath: screenshotPath,
    baseURL,
    routePath,
    viewName: requestedView,
    rootSelector,
    useLiveApi,
    readyState: VIEW_CONFIGS[requestedView]?.readyDescription || requestedView,
    readyChecks,
    viewport: {
      width: 390,
      height: 844,
      deviceScaleFactor: 2,
    },
    screenshotMode: 'viewport-css-scale',
  };

  fs.writeFileSync(metadataPath, JSON.stringify(metadata, null, 2), 'utf8');
  return metadataPath;
}

async function captureView(browser, requestedView) {
  const config = VIEW_CONFIGS[requestedView];
  if (!config) {
    throw new Error(`Unsupported VISUAL_VIEW: ${requestedView}`);
  }

  const context = await browser.newContext({
    ignoreHTTPSErrors: baseUrlObject.protocol === 'https:',
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
    serviceWorkers: 'block',
  });

  try {
    const page = await context.newPage();
    if (!useLiveApi) {
      await mockPwaApi(page);
    }

    await waitForAppShell(page);
    await config.action(page);
    const readyChecks = await waitForSemanticReadyState(page, requestedView, config.selectors);
    await sleep(250);

    const screenshotPath = getOutputPath(requestedView);
    await page.screenshot({
      path: screenshotPath,
      fullPage: false,
      animations: 'disabled',
      scale: 'css',
    });

    const metadataPath = await writeMetadata(requestedView, screenshotPath, readyChecks);
    console.log(`[VISUAL-SIGHT] ${requestedView} screenshot captured at: ${screenshotPath}`);
    console.log(`[VISUAL-SIGHT] ${requestedView} metadata written to: ${metadataPath}`);
    return {
      view: requestedView,
      screenshotPath,
      metadataPath,
      readyChecks,
      useLiveApi,
    };
  } finally {
    await context.close();
  }
}

function writeIndex(results) {
  const indexPath = path.join(ARTIFACTS_DIR, 'ui_state-index.json');
  const index = {
    capturedAt: new Date().toISOString(),
    baseURL,
    routePath,
    useLiveApi,
    note: 'Lies zuerst diese Datei und nur bei Bedarf die einzelnen PNG-Artefakte.',
    captures: results,
  };
  fs.writeFileSync(indexPath, JSON.stringify(index, null, 2), 'utf8');
  console.log(`[VISUAL-SIGHT] Index written to: ${indexPath}`);
}

async function main() {
  fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });

  let server = null;
  let browser;

  try {
    server = await ensureStaticServer();

    browser = await chromium.launch({ headless: true });
    const requestedViews = viewName === 'all' ? ['list', 'detail', 'alert'] : [viewName];
    const results = [];
    for (const requestedView of requestedViews) {
      const result = await captureView(browser, requestedView);
      results.push(result);
    }
    writeIndex(results);
  } catch (error) {
    console.error(`[VISUAL-SIGHT-ERROR] ${error.message}`);
    process.exitCode = 1;
  } finally {
    if (browser) {
      await browser.close();
    }
    stopServer(server);
  }
}

main();
