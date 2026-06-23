const { test, expect } = require('@playwright/test');
const { mockPwaApi, createPickingDetail } = require('./helpers/pwa-api');

async function openPicking(page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Lena Lager' }).click();
  await page.getByText('4x Brick 2x2 orange').click();
  await expect(page.locator('#main .btn-confirm')).toBeVisible();
}

// Issue 1: der "Alle bestaetigen"-Pfad darf serialisierte Positionen NICHT
// ueberspringen, sondern muss pro Serial-Position die Seriennummer erfassen.
test('confirm-all erfasst die Seriennummer fuer serialisierte Positionen (kein Skip)', async ({ page }) => {
  const detail = createPickingDetail();
  detail.move_lines[1].tracking = 'serial'; // Position 502 ist serialisiert (zuletzt)
  const api = await mockPwaApi(page, { detail });

  await openPicking(page);

  // confirm_all ist nur per Voice-Intent verdrahtet -> programmatisch ausloesen.
  // Promise NICHT awaiten, sonst blockiert evaluate auf dem Serial-Modal.
  await page.evaluate(() => { window._app.triggerConfirmAll(); });

  // Fuer die serialisierte Position erscheint das Seriennummer-Modal.
  await expect(page.locator('#serial-input')).toBeVisible();
  await expect(page.locator('#serial-product-name')).toContainText('Brick 2x2 hellgruen');
  await page.locator('#serial-input').fill('SN-TEST-1');
  await page.locator('#serial-confirm').click();

  // Beide Positionen wurden bestaetigt, die serielle mit serial_number.
  await expect.poll(() => api.getConfirmCalls()).toBe(2);
  await expect.poll(() => api.getLastConfirmRequest()).toMatchObject({
    move_line_id: 502,
    serial_number: 'SN-TEST-1',
  });
});

// Issue 5: Escape schliesst das Serial-Modal als "Ueberspringen" (serial_number '').
test('Escape im Serial-Modal ueberspringt und bestaetigt ohne Seriennummer', async ({ page }) => {
  const detail = createPickingDetail();
  detail.move_lines[0].tracking = 'serial'; // aktuelle Position ist serialisiert
  const api = await mockPwaApi(page, { detail });

  await openPicking(page);
  await page.locator('#main .btn-confirm').click();
  await expect(page.locator('#serial-input')).toBeVisible();

  await page.keyboard.press('Escape');

  await expect(page.locator('#serial-input')).toBeHidden();
  await expect.poll(() => api.getConfirmCalls()).toBe(1);
  await expect.poll(() => api.getLastConfirmRequest()).toMatchObject({
    move_line_id: 501,
    serial_number: '',
  });
});

// Issue 5: Klick auf den Backdrop schliesst das Serial-Modal als "Ueberspringen".
test('Backdrop-Klick ueberspringt das Serial-Modal', async ({ page }) => {
  const detail = createPickingDetail();
  detail.move_lines[0].tracking = 'serial';
  const api = await mockPwaApi(page, { detail });

  await openPicking(page);
  await page.locator('#main .btn-confirm').click();
  await expect(page.locator('#serial-input')).toBeVisible();

  // Klick oben links auf das Overlay, ausserhalb der modal-sheet.
  await page.locator('#app-overlay').click({ position: { x: 5, y: 5 } });

  await expect(page.locator('#serial-input')).toBeHidden();
  await expect.poll(() => api.getConfirmCalls()).toBe(1);
  await expect.poll(() => api.getLastConfirmRequest()).toMatchObject({
    serial_number: '',
  });
});
