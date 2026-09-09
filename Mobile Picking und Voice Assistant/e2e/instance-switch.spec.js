const { test, expect } = require('@playwright/test');
const { mockPwaApi, loginPwa } = require('./helpers/pwa-api');

test('Lagername und Kopfaktionen bleiben auf schmalen Telefonen vollständig sichtbar', async ({ page }) => {
  await mockPwaApi(page, {
    instances: [
      { name: 'local', display_name: 'Lager 1' },
      { name: 'lager-2', display_name: 'Lager 2' },
    ],
  });
  await page.goto('/');
  await loginPwa(page);
  for (const width of [320, 390, 412]) {
    await page.setViewportSize({ width, height: 844 });
    const layout = await page.locator('#instance-switch').evaluate((select) => {
      const style = getComputedStyle(select);
      const context = document.createElement('canvas').getContext('2d');
      context.font = style.font;
      return {
        labelSpace: select.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
        // Native selects also reserve space for the dropdown arrow.
        neededSpace: Math.ceil(context.measureText(select.selectedOptions[0].textContent).width) + 20,
        controlsFit: [...document.querySelectorAll('#instance-switch, .header-actions button, #picker-indicator')]
          .every((node) => {
            const box = node.getBoundingClientRect();
            return box.left >= 0 && box.right <= innerWidth && box.height >= 44;
          }),
      };
    });
    expect(layout.labelSpace, `Lagername bei ${width}px`).toBeGreaterThanOrEqual(layout.neededSpace);
    expect(layout.controlsFit, `Kopfaktionen bei ${width}px`).toBe(true);
  }
});

test('Lager-Umschalter tauscht die authentifizierte Sitzung für Folge-Requests', async ({ page }) => {
  const api = await mockPwaApi(page, {
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
  await loginPwa(page);

  const select = page.locator('#instance-switch');
  await expect(select).toBeVisible();
  await expect(select).toHaveValue('local');
  await select.selectOption('lager-2');

  await expect(page.locator('#instance-switch')).toHaveValue('lager-2');
  await expect.poll(() => api.getSwitchInstanceRequests()).toEqual([{ odoo_instance: 'lager-2' }]);
  await expect.poll(() => api.getPrincipal()?.odoo_instance).toBe('lager-2');
  await expect.poll(() => pickingsInstanceHeaders).toEqual([null, null]);
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
  await loginPwa(page);

  await expect(page.locator('#instance-switch')).toBeHidden();
  expect(pickingsInstanceHeaders).toEqual([null]);
});
