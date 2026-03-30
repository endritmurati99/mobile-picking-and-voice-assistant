const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');

async function choosePicker(page, name = 'Endrit Murati') {
  await expect(page.getByRole('heading', { name: 'Profil auswählen' })).toBeVisible();
  await page.getByRole('button', { name }).click();
}

test('loads the picking list and opens the picking detail view', async ({ page }) => {
  await mockPwaApi(page);

  await page.goto('/');

  await expect(page.locator('#main')).not.toContainText('LEGO Ente');
  await choosePicker(page);
  await expect(page.locator('#status-indicator')).toHaveText('Online');
  await expect(page.getByText('LEGO Ente')).toBeVisible();
  await expect(page.getByText('4x Brick 2x2 orange')).toBeVisible();
  await expect(page.getByText('WH/INT/00007')).toBeVisible();
  await expect(page.locator('#task-counter')).toHaveText('3 Aufgaben offen');
  await expect(page.locator('#picker-indicator')).toHaveAttribute('data-short-label', 'EM');

  await page.getByText('LEGO Ente').click();

  await expect(page.locator('#header')).toBeHidden();
  await expect(page.locator('#main')).toContainText('LEGO Ente');
  await expect(page.locator('#main')).toContainText('Brick 2x2 orange');
  await expect(page.locator('#main')).toContainText('1 / 2');
  await expect(page.locator('#main')).toContainText('L-E1-P1');
  await expect(page.locator('.detail-product-hero__media')).toBeVisible();
  await expect(page.locator('#main .btn-confirm')).toBeVisible();
  await expect(page.locator('#nav')).toBeVisible();
});

test('filters locally by search, urgency and preferred zone', async ({ page }) => {
  await mockPwaApi(page);

  await page.goto('/');
  await choosePicker(page);

  await page.locator('#search-toggle').click();
  const searchInput = page.locator('#search-input');
  await searchInput.fill('ente');

  await expect(page.getByText('LEGO Ente')).toBeVisible();
  await expect(page.getByText('1x Motorblock')).toBeHidden();
  await expect(page.locator('#task-counter')).toHaveText('1 Aufgabe offen');

  await searchInput.fill('motor');

  await expect(page.getByText('1x Motorblock')).toBeVisible();
  await expect(page.getByText('LEGO Ente')).toBeHidden();
  await expect(page.locator('#task-counter')).toHaveText('1 Aufgabe offen');

  await searchInput.fill('');
  await page.getByRole('button', { name: 'Dringend (2)' }).click();

  await expect(page.getByText('1x Motorblock')).toBeVisible();
  await expect(page.getByText('4x Brick 2x2 orange')).toBeVisible();
  await expect(page.getByText('2x Brick 1x4 blau')).toBeHidden();

  await page.getByRole('button', { name: 'Mein Bereich (0)' }).click();
  await expect(page.getByRole('heading', { name: 'Bevorzugten Bereich wählen' })).toBeVisible();
  await page.getByRole('button', { name: /Lager Links/ }).click();

  await expect(page.getByText('LEGO Ente')).toBeVisible();
  await expect(page.getByText('1x Motorblock')).toBeHidden();
  await expect(page.getByRole('button', { name: 'Lager Links (1)' })).toBeVisible();
  await expect(page.locator('#task-counter')).toHaveText('1 Aufgabe offen');
});

test('toggles high contrast mode from the header', async ({ page }) => {
  await mockPwaApi(page);

  await page.goto('/');
  await choosePicker(page);

  await expect(page.locator('body')).not.toHaveClass(/high-contrast/);
  await page.locator('#high-contrast-toggle').click();
  await expect(page.locator('body')).toHaveClass(/high-contrast/);
});
