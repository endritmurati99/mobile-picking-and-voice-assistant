const { chromium } = require('playwright');

(async () => {
  try {
    const browser = await chromium.connectOverCDP('http://localhost:9222');
    const context = browser.contexts()[0];
    const page = await context.newPage();
    
    console.log('Navigiere zu n8n Executions...');
    await page.goto('http://localhost:5678/executions', { waitUntil: 'networkidle' });
    
    // Screenshot der Executions
    await page.screenshot({ path: 'n8n-executions-live.png', fullPage: true });
    console.log('Screenshot von n8n Executions erstellt.');
    
    // Versuche den neuesten Alert-Status in n8n zu finden
    const executions = await page.$$eval('.execution-list-item', items => items.map(i => i.innerText));
    console.log('Live Executions:', executions);

    await browser.close();
  } catch (err) {
    console.error('Fehler bei der Playwright-Verbindung:', err);
  }
})();
