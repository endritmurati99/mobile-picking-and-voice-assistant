const { expect } = require('@playwright/test');

// Seit Foundation-Task 16 ist der Login ein Formular (#login-user /
// #login-password / #login-submit), keine Profil-Kachel mehr. Siehe
// pwa/js/app.js renderLoginScreen(). Der Mock POST /api/auth/picker-session
// in helpers/pwa-api.js beantwortet jeden Login immer als "Lena Lager",
// unabhaengig vom eingegebenen Benutzernamen.
const DEFAULT_USER = 'lena.lager';
const DEFAULT_PASSWORD = 'admin';

async function login(page, user = DEFAULT_USER, { password = DEFAULT_PASSWORD, goto = true } = {}) {
  if (goto) {
    await page.goto('/');
  }
  await expect(page.locator('#login-user')).toBeVisible();

  // Sicherheitsnetz: pwa/js/pwa.js registriert einen Service Worker, dessen
  // erster "controllerchange" ueber handleServiceWorkerControllerRefresh()
  // (pwa/js/app.js) window.location.reload() ausloest und mitten im Ausfuellen
  // die Form leert. `serviceWorkers: 'block'` in playwright.config.js
  // unterbindet das eigentlich; falls trotzdem einmal ein Reset durchrutscht,
  // hier robust erneut versuchen statt den Test hart scheitern zu lassen.
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await page.locator('#login-user').fill(user);
    await page.locator('#login-password').fill(password);
    await page.locator('#login-submit').click();
    try {
      // Nach erfolgreichem Login ersetzt setMainContent() die Login-Form.
      await expect(page.locator('#login-form')).toHaveCount(0, { timeout: attempt < 3 ? 2000 : 5000 });
      return;
    } catch (error) {
      if (attempt === 3) throw error;
      await expect(page.locator('#login-user')).toBeVisible();
    }
  }
}

module.exports = { login };
