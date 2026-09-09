const { test, expect } = require('@playwright/test');
const { mockPwaApi, loginPwa } = require('./helpers/pwa-api');

async function freezeClock(page) {
  await page.addInitScript((now) => {
    const RealDate = Date;
    class FrozenDate extends RealDate {
      constructor(...args) {
        super(...(args.length ? args : [now]));
      }

      static now() {
        return now;
      }
    }
    window.Date = FrozenDate;
  }, Date.parse('2026-09-09T10:00:00Z'));
}

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

async function expectVisualSnapshot(page, locator, name, options = {}) {
  // Snapshot the idle layout independently of the host's speech/audio timing.
  await page.evaluate(async () => (await import('/js/voice.js')).stopSpeaking());
  await expect(page.locator('#voice-status-indicator')).toHaveClass(/voice-status--idle/);
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  });
  if (options.clearHover) {
    await page.mouse.move(1, 1);
  }
  await expect(locator).toHaveScreenshot(name, {
    animations: 'disabled',
    caret: 'hide',
    scale: 'css',
  });
}

test('picking list matches the mobile visual baseline', async ({ page }) => {
  await mockPwaApi(page);
  await freezeClock(page);
  await page.goto('/');
  await loginPwa(page);
  await expect(page.getByRole('article', { name: 'LEGO Ente', exact: true })).toBeVisible();
  await expect(page.locator('#status-indicator')).toHaveText('Online');
  await expect(page.locator('#status-indicator')).toHaveClass(/online/);
  await disableMotion(page);
  await expectVisualSnapshot(page, page.locator('#app'), 'picking-list.png');
});

test('picking detail matches the mobile visual baseline', async ({ page }) => {
  await mockPwaApi(page);
  await freezeClock(page);
  await page.goto('/');
  await loginPwa(page);
  await page.getByRole('article', { name: 'LEGO Ente', exact: true }).click();
  await expect(page.locator('#main')).toContainText('Brick 2x2 orange');
  await disableMotion(page);
  await expectVisualSnapshot(page, page.locator('#app'), 'picking-detail.png', { clearHover: true });
});

test('quality alert matches the mobile visual baseline', async ({ page }) => {
  await mockPwaApi(page);
  await freezeClock(page);
  await page.goto('/');
  await loginPwa(page);
  await page.getByRole('article', { name: 'LEGO Ente', exact: true }).click();
  await page.locator('#btn-alert').click();
  await expect(page.getByRole('heading', { name: 'Problem melden' })).toBeVisible();
  await disableMotion(page);
  await expectVisualSnapshot(page, page.locator('#app'), 'quality-alert.png', { clearHover: true });
});
