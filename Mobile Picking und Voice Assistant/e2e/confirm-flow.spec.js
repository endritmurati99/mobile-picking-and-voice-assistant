const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');

test('confirms both move lines and reaches the completion view', async ({ page }) => {
  const api = await mockPwaApi(page);

  await page.goto('/');
  await page.locator('.pick-card[data-id]').first().click();

  await page.locator('.btn-confirm').click();

  await expect(page.locator('#main')).toContainText('Brick 2x2 hellgruen');
  await expect(page.locator('#main')).toContainText('2 / 2');
  await expect(page.locator('#main .btn-confirm')).toBeVisible();

  await page.locator('.btn-confirm').click();

  await expect(page.locator('#main')).toContainText('Alle Artikel erfasst.');
  await expect(page.locator('#main button')).toContainText('Liste');
  await expect.poll(() => api.getConfirmCalls()).toBe(2);
  await expect.poll(() => api.getLastConfirmRequest()).toMatchObject({
    move_line_id: 502,
    scanned_barcode: '9780201379624',
    quantity: 3,
  });
});
