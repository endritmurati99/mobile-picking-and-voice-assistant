const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');

async function bootDesktopList(page, viewport) {
  await mockPwaApi(page);
  await page.setViewportSize(viewport);
  await page.goto('/');
  await page.getByRole('button', { name: 'Endrit Murati' }).click();
  await expect(page.locator('.list-workspace')).toBeVisible();
}

test('desktop list uses a broad workspace without a narrow middle column', async ({ page }) => {
  await bootDesktopList(page, { width: 1366, height: 900 });

  const listMainWidth = await page.locator('.list-main').evaluate((node) => Math.round(node.getBoundingClientRect().width));
  await expect(page.locator('.list-summary')).toBeHidden();
  expect(listMainWidth).toBeGreaterThan(980);
  await expect(page.locator('.queue-overview--main')).toBeVisible();
  await expect(page.locator('.pick-list-card').first()).toBeVisible();
});

test('detail view becomes two-column on large desktop', async ({ page }) => {
  await bootDesktopList(page, { width: 1536, height: 960 });
  await page.getByText('4x Brick 2x2 orange').click();

  await expect(page.locator('.detail-workspace')).toBeVisible();
  await expect(page.locator('.detail-side')).toBeVisible();
  await expect(page.locator('.detail-compact__progress')).toBeHidden();

  const layout = await page.locator('.detail-workspace').evaluate((node) => {
    const main = node.querySelector('.detail-main');
    const side = node.querySelector('.detail-side');
    const mainBox = main.getBoundingClientRect();
    const sideBox = side.getBoundingClientRect();
    return {
      mainWidth: Math.round(mainBox.width),
      sideWidth: Math.round(sideBox.width),
      sideStartsAfterMain: sideBox.left > mainBox.left + mainBox.width * 0.7,
    };
  });

  expect(layout.mainWidth).toBeGreaterThan(layout.sideWidth);
  expect(layout.sideStartsAfterMain).toBe(true);
});

test('completion screen shows a substantial completion card with next-action CTA', async ({ page }) => {
  await bootDesktopList(page, { width: 1366, height: 900 });
  await page.getByText('4x Brick 2x2 orange').click();

  await page.locator('.btn-confirm').click();
  await page.locator('.btn-confirm').click();

  await expect(page.locator('.completion-card')).toBeVisible();
  await expect(page.locator('#completion-list-btn')).toBeVisible();
  await expect(page.locator('#completion-next-btn')).toBeVisible();
  await expect(page.locator('.completion-summary')).toContainText('Positionen');
});
