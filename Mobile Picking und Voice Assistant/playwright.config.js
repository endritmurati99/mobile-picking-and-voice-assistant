// @ts-check
const { defineConfig, devices } = require('@playwright/test');

const PORT = 4173;

module.exports = defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    // pwa/js/pwa.js registriert einen Service Worker, der beim ersten
    // "controllerchange" automatisch window.location.reload() ausloest
    // (pwa/js/app.js handleServiceWorkerControllerRefresh). In einem frischen
    // Browser-Context passiert genau das mitten im Testlauf und wirft jeden
    // Formular- oder Filterzustand weg (Login-Felder leer, zurueck auf den
    // Login-Schirm). Der SW ist fuer die Testfaelle hier irrelevant -- also
    // Registrierung auf Playwright-Ebene blockieren statt Produktcode
    // anzufassen.
    serviceWorkers: 'block',
  },
  webServer: {
    command: `node e2e/helpers/static-server.js`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    env: { PORT: String(PORT) },
  },
  projects: [
    {
      name: 'mobile-chromium',
      use: { ...devices['Pixel 5'] },
    },
    {
      name: 'desktop-chromium',
      use: { ...devices['Desktop Chrome'] },
      // Visual-Baselines existieren nur fuer mobile-chromium (siehe
      // e2e/visual.spec.js-snapshots) -- auf Desktop wuerden sie ohne
      // Referenzbild fehlschlagen.
      testIgnore: /visual\.spec\.js/,
    },
  ],
});
