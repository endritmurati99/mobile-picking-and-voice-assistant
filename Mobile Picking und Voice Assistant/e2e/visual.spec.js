const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');

async function disableMotion(page) {
  await page.addStyleTag({
    content: `
      *,
      *::before,
      *::after {
        animation: none !important;
        transition: none !important;
        caret-color: transparent !important;
      }
    `,
  });
}

async function expectVisualSnapshot(locator, name) {
  await expect(locator).toHaveScreenshot(name, {
    animations: 'disabled',
    caret: 'hide',
    scale: 'css',
  });
}

test('picking list matches the mobile visual baseline', async ({ page }) => {
  await mockPwaApi(page);
  await page.goto('/');
  await expect(page.getByText('WH/INT/00007')).toBeVisible();
  await disableMotion(page);
  await expectVisualSnapshot(page.locator('#app'), 'picking-list.png');
});

test('picking detail matches the mobile visual baseline', async ({ page }) => {
  await mockPwaApi(page);
  await page.goto('/');
  await page.getByText('WH/INT/00007').click();
  await expect(page.locator('#main')).toContainText('Brick 2x2 orange');
  await disableMotion(page);
  await expectVisualSnapshot(page.locator('#app'), 'picking-detail.png');
});

test('quality alert matches the mobile visual baseline', async ({ page }) => {
  await mockPwaApi(page);
  await page.goto('/');
  await page.getByText('WH/INT/00007').click();
  await page.locator('#btn-alert').click();
  await expect(page.getByRole('heading', { name: 'Problem melden' })).toBeVisible();
  await disableMotion(page);
  await expectVisualSnapshot(page.locator('#app'), 'quality-alert.png');
});
