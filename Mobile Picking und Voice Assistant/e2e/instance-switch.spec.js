const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');

test('Lager-Umschalter setzt X-Odoo-Instance-Header auf Folge-Requests', async ({ page }) => {
  await mockPwaApi(page, {
    instances: [
      { name: 'local', display_name: 'Lager 1' },
      { name: 'lager-2', display_name: 'Lager 2' },
    ],
  });

  const pickingsInstanceHeaders = [];
  await page.route('**/api/pickings', async (route) => {
    pickingsInstanceHeaders.push(route.request().headers()['x-odoo-instance'] || null);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Lena Lager' }).click();

  const select = page.locator('#instance-switch');
  await expect(select).toBeVisible();
  await expect(select).toHaveValue('local');
  await select.selectOption('lager-2');

  await expect(page.locator('#instance-switch')).toHaveValue('lager-2');
  await page.getByRole('button', { name: 'Lena Lager' }).click();

  expect(pickingsInstanceHeaders).toContain(null);
  expect(pickingsInstanceHeaders).toContain('lager-2');
});

test('Lager-Umschalter verwirft gespeicherte Alt-Instanz wenn nur lokal verfuegbar ist', async ({ page }) => {
  await mockPwaApi(page);

  const pickingsInstanceHeaders = [];
  await page.route('**/api/pickings', async (route) => {
    pickingsInstanceHeaders.push(route.request().headers()['x-odoo-instance'] || null);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });

  await page.addInitScript(() => {
    localStorage.setItem('picking-assistant-odoo-instance', 'lager-2');
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Lena Lager' }).click();

  await expect(page.locator('#instance-switch')).toBeHidden();
  expect(pickingsInstanceHeaders).toEqual([null]);
});
