const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');
const { login } = require('./helpers/login');

async function choosePicker(page, name = 'lena.lager') {
  const searchInput = page.locator('#search-input');
  if (await searchInput.isEnabled().catch(() => false)) return;

  await login(page, name, { goto: false });
  await expect(page.locator('#picker-indicator')).toBeVisible();
  await expect(searchInput).toBeEnabled();
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
  await expect(page.locator('#picker-indicator')).toHaveAttribute('data-short-label', 'LL');

  await page.getByText('LEGO Ente').click();

  await expect(page.locator('#header')).toBeVisible();
  await expect(page.locator('#header')).toHaveClass(/header--compact/);
  await expect(page.locator('#main')).toContainText('LEGO Ente');
  await expect(page.locator('#main')).toContainText('Brick 2x2 orange');
  await expect(page.locator('#main')).toContainText('1 / 2');
  await expect(page.locator('#main')).toContainText('L-E1-P1');
  await expect(page.locator('.detail-product-hero__media')).toBeVisible();
  await expect(page.locator('.detail-line-list')).toBeVisible();
  await expect(page.locator('#main')).toContainText('Barcode absenden');
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

test('toggles and remembers dark mode from the header', async ({ page }) => {
  await mockPwaApi(page);

  await page.goto('/');
  await choosePicker(page);

  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.locator('#theme-toggle').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('#theme-toggle')).toHaveAttribute('aria-pressed', 'true');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});
