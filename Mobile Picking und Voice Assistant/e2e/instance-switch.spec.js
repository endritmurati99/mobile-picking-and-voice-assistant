const { test, expect } = require('@playwright/test');
const { mockPwaApi } = require('./helpers/pwa-api');
const { login } = require('./helpers/login');

// `X-Odoo-Instance` ist toter Code (siehe pwa/js/api.js:225-233): die PWA
// sendet seit der Session-Cookie-Umstellung KEINE Identitaetsheader mehr.
// Ein Lagerwechsel ist heute ein neuer Login gegen die Ziel-Instanz per
// `POST /api/auth/switch-instance` -- das Backend liest die Instanz aus dem
// Sitzungs-Cookie, nicht aus einem Header (pwa/js/app.js switchInstance(),
// Kommentar ab Zeile ~665).
test('Lager-Umschalter meldet sich in der Zielinstanz neu an und laedt die Pickings neu', async ({ page }) => {
  await mockPwaApi(page, {
    instances: [
      { name: 'local', display_name: 'Lager 1' },
      { name: 'lager-2', display_name: 'Lager 2' },
    ],
  });

  const switchInstanceRequests = [];
  await page.route('**/api/auth/switch-instance', async (route) => {
    switchInstanceRequests.push(JSON.parse(route.request().postData() || '{}'));
    // Nur mitschneiden, die eigentliche Antwort liefert weiterhin mockPwaApi.
    await route.fallback();
  });

  let pickingsRequests = 0;
  await page.route('**/api/pickings', async (route) => {
    pickingsRequests += 1;
    await route.fallback();
  });

  await login(page);

  const select = page.locator('#instance-switch');
  await expect(select).toBeVisible();
  await expect(select).toHaveValue('local');
  const pickingsRequestsAfterLogin = pickingsRequests;

  await select.selectOption('lager-2');

  // Request ging mit der Ziel-Instanz raus (statt eines toten Headers auf
  // /api/pickings) und die UI (der Instanz-Switcher) zeigt die neue Instanz.
  await expect.poll(() => switchInstanceRequests.length).toBe(1);
  expect(switchInstanceRequests[0]).toMatchObject({ odoo_instance: 'lager-2' });
  await expect(select).toHaveValue('lager-2');

  // Nach dem Wechsel wird die Liste in der neuen Instanz neu geladen.
  await expect.poll(() => pickingsRequests).toBeGreaterThan(pickingsRequestsAfterLogin);
});

test('Lager-Umschalter verwirft gespeicherte Alt-Instanz wenn nur lokal verfuegbar ist', async ({ page }) => {
  await mockPwaApi(page);

  await page.addInitScript(() => {
    localStorage.setItem('picking-assistant-odoo-instance', 'lager-2');
  });

  await login(page);

  await expect(page.locator('#instance-switch')).toBeHidden();
  // setActiveInstance('local') (pwa/js/api.js) raeumt den Storage-Key auf,
  // statt ihn auf 'local' zu setzen -- das ist der eigentliche "verwerfen".
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem('picking-assistant-odoo-instance')))
    .toBeNull();
});
