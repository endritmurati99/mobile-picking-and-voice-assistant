const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');

test('confirms both move lines and reaches the completion view', async ({ page }) => {
  const api = await mockPwaApi(page);

  await page.goto('/');
  await page.getByRole('button', { name: 'Endrit Murati' }).click();
  await page.getByText('4x Brick 2x2 orange').click();

  await page.locator('.btn-confirm').click();

  await expect(page.locator('#main')).toContainText('Brick 2x2 hellgruen');
  await expect(page.locator('#main')).toContainText('L-E2-P4');
  await expect(page.locator('#main')).toContainText('2 / 2');
  await expect(page.locator('#main .btn-confirm')).toBeVisible();

  await page.locator('.btn-confirm').click();

  await expect(page.locator('.completion-card')).toBeVisible();
  await expect(page.locator('#main')).toContainText('Auftrag abgeschlossen');
  await expect(page.locator('#main')).toContainText('Alle Artikel wurden erfasst und synchronisiert.');
  await expect(page.locator('#completion-list-btn')).toBeVisible();
  await expect(page.locator('#completion-next-btn')).toBeVisible();
  await expect.poll(() => api.getConfirmCalls()).toBe(2);
  await expect.poll(() => api.getLastConfirmRequest()).toMatchObject({
    move_line_id: 502,
    scanned_barcode: '9780201379624',
    quantity: 3,
  });
});
