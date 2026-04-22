const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  // Login (falls nötig, wir probieren es direkt)
  await page.goto('http://localhost:5678/workflow/8eWVrUfTAUvOAbpdug8oP');
  await page.waitForTimeout(3000); // Warten auf Load
  
  // Mache einen Screenshot vom Workflow, um die Nodes zu sehen
  await page.screenshot({ path: 'n8n-workflow-debug.png' });
  
  // Suche nach Webhook-Pfad im HTML
  const content = await page.content();
  console.log('Seite geladen. Suche nach Pfaden...');
  if (content.includes('quality-alert-created')) {
      console.log('Pfad "quality-alert-created" im HTML gefunden.');
  }
  
  await browser.close();
})();
