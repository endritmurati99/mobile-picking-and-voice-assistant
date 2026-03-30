const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');

async function choosePicker(page, name = 'Endrit Murati') {
  await expect(page.getByRole('heading', { name: 'Profil auswählen' })).toBeVisible();
  await page.getByRole('button', { name }).click();
}

async function triggerResume(page) {
  await page.evaluate(() => {
    document.dispatchEvent(new Event('visibilitychange'));
  });
}

function readViewportMetrics(page, selectors = {}) {
  return page.evaluate((input) => {
    const root = document.documentElement;
    const metrics = {
      scrollWidth: root.scrollWidth,
      innerWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    };

    for (const [key, selector] of Object.entries(input)) {
      const rect = document.querySelector(selector)?.getBoundingClientRect();
      metrics[key] = rect
        ? { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: rect.width, height: rect.height }
        : null;
    }

    return metrics;
  }, selectors);
}

test.describe('small mobile layout', () => {
  test.use({
    viewport: { width: 320, height: 568 },
    isMobile: true,
    hasTouch: true,
  });

  test('keeps list, detail, and quality alert usable at 320px width', async ({ page }) => {
    await mockPwaApi(page);
    await page.goto('/');
    await choosePicker(page);

    await expect(page.getByText('4x Brick 2x2 orange')).toBeVisible();

    const listMetrics = await readViewportMetrics(page, {
      firstCard: '.pick-list-card',
      filterRow: '.header-row--filters',
    });
    expect(listMetrics.scrollWidth).toBeLessThanOrEqual(listMetrics.innerWidth);
    expect(listMetrics.firstCard.top).toBeLessThan(listMetrics.viewportHeight - 40);
    expect(listMetrics.filterRow.right).toBeLessThanOrEqual(listMetrics.innerWidth + 1);

    await page.getByText('4x Brick 2x2 orange').click();
    await expect(page.locator('#main .btn-confirm')).toBeVisible();

    const detailMetrics = await readViewportMetrics(page, {
      floatingNav: '#nav',
      confirmButton: '.btn-confirm',
    });
    expect(detailMetrics.scrollWidth).toBeLessThanOrEqual(detailMetrics.innerWidth);
    expect(detailMetrics.floatingNav.bottom).toBeLessThanOrEqual(detailMetrics.viewportHeight + 1);
    expect(detailMetrics.confirmButton.right).toBeLessThanOrEqual(detailMetrics.innerWidth + 1);

    await page.locator('#btn-alert').click();
    await expect(page.getByRole('heading', { name: 'Problem melden' })).toBeVisible();

    const qaMetrics = await readViewportMetrics(page, {
      qaActions: '.qa-actions',
      submitButton: '#qa-submit',
    });
    expect(qaMetrics.scrollWidth).toBeLessThanOrEqual(qaMetrics.innerWidth);
    expect(qaMetrics.qaActions.bottom).toBeLessThanOrEqual(qaMetrics.viewportHeight + 6);
    expect(qaMetrics.submitButton.width).toBeGreaterThan(120);
  });
});

test.describe('lifecycle refresh', () => {
  test('refreshes the list on resume and online events', async ({ page }) => {
    const api = await mockPwaApi(page);

    await page.goto('/');
    await choosePicker(page);
    await expect(page.getByText('4x Brick 2x2 orange')).toBeVisible();

    api.setPickings((pickings) => pickings.map((picking) => (
      picking.id === 1001
        ? { ...picking, primary_item_display: '6x Brick 2x2 orange', kit_name: 'LEGO Ente Reloaded' }
        : picking
    )));

    await triggerResume(page);
    await expect(page.getByText('6x Brick 2x2 orange')).toBeVisible();

    await page.waitForTimeout(950);

    api.setPickings((pickings) => pickings.map((picking) => (
      picking.id === 1001
        ? { ...picking, primary_item_display: '7x Brick 2x2 orange', kit_name: 'LEGO Ente Online' }
        : picking
    )));

    await page.evaluate(() => {
      window.dispatchEvent(new Event('online'));
    });
    await expect(page.getByText('7x Brick 2x2 orange')).toBeVisible();
  });

  test('keeps the active detail line when refreshing the current picking', async ({ page }) => {
    const api = await mockPwaApi(page);

    await page.goto('/');
    await choosePicker(page);
    await page.getByText('4x Brick 2x2 orange').click();
    await page.locator('.btn-confirm').click();

    await expect(page.locator('#main')).toContainText('Brick 2x2 hellgruen');
    await expect(page.locator('#main')).toContainText('2 / 2');

    api.setDetail((detail) => ({
      ...detail,
      move_lines: detail.move_lines.map((line, index) => (
        index === 1
          ? {
              ...line,
              product_name: 'Brick 2x2 neongruen',
              product_short_name: 'Brick 2x2 neongruen',
              ui_display: 'Brick 2x2 neongruen',
            }
          : line
      )),
    }));

    await triggerResume(page);
    await expect(page.locator('#main')).toContainText('Brick 2x2 neongruen');
    await expect(page.locator('#main')).toContainText('2 / 2');
  });

  test('does not auto-refresh while the quality alert form is open', async ({ page }) => {
    const api = await mockPwaApi(page);

    await page.goto('/');
    await choosePicker(page);
    await page.getByText('4x Brick 2x2 orange').click();
    await page.locator('#btn-alert').click();

    const description = page.getByLabel('Beschreibung');
    await description.fill('Beschaedigte Ecke an der Verpackung');
    const detailRequestsBefore = api.getDetailRequests();
    const pickingsRequestsBefore = api.getPickingsRequests();

    api.setDetail((detail) => ({
      ...detail,
      move_lines: detail.move_lines.map((line) => ({
        ...line,
        ui_display: `${line.ui_display} aktualisiert`,
      })),
    }));

    await triggerResume(page);
    await page.waitForTimeout(150);

    expect(api.getDetailRequests()).toBe(detailRequestsBefore);
    expect(api.getPickingsRequests()).toBe(pickingsRequestsBefore);
    await expect(page.getByRole('heading', { name: 'Problem melden' })).toBeVisible();
    await expect(description).toHaveValue('Beschaedigte Ecke an der Verpackung');
  });
});
