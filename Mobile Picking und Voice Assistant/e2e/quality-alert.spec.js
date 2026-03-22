const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');

test('submits a quality alert from the active picking context', async ({ page }) => {
  const api = await mockPwaApi(page);

  await page.goto('/');
  await page.getByText('WH/INT/00007').click();

  await page.locator('#btn-alert').click();

  await expect(page.getByRole('heading', { name: 'Problem melden' })).toBeVisible();
  await page.locator('#qa-description').fill('Beschaedigter Artikel an Fach A-12.');
  await page.locator('#qa-priority').selectOption('2');
  await page.locator('#qa-submit').click();

  await expect(page.locator('body')).toContainText('Alert QA-100 erstellt');
  await expect(page.locator('#main')).toContainText('Brick 2x2 orange');
  await expect.poll(() => api.getLastQualityRequest()).toMatchObject({
    contentType: expect.stringContaining('multipart/form-data'),
  });
});
