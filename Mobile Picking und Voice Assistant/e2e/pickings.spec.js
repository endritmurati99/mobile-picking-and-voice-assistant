const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');

test('loads the picking list and opens the picking detail view', async ({ page }) => {
  await mockPwaApi(page);

  await page.goto('/');

  await expect(page.locator('#status-indicator')).toHaveText('Online');
  await expect(page.locator('.pick-card[data-id]')).toHaveCount(1);
  await expect(page.locator('.pick-card[data-id]').first()).toContainText('WH/INT/00007');

  await page.locator('.pick-card[data-id]').first().click();

  await expect(page.locator('#main')).toContainText('Brick 2x2 orange');
  await expect(page.locator('#main')).toContainText('1 / 2');
  await expect(page.locator('#main .btn-confirm')).toBeVisible();
});
