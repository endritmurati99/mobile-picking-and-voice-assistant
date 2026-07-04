const { test, expect } = require('@playwright/test');
const { mockPwaApi, createPickingDetail, createPickingList } = require('./helpers/pwa-api');

test('voice next_order opens the next available picking from completion view', async ({ page }) => {
  const nextDetail = createPickingDetail();
  nextDetail.id = 1002;
  nextDetail.name = 'WH/INT/00008';
  nextDetail.reference_code = 'WH/INT/00008';
  nextDetail.kit_name = 'Folgeauftrag';
  nextDetail.primary_item_display = '2x Brick 1x4 blau';
  nextDetail.move_lines = [
    {
      id: 601,
      product_id: 12,
      product_name: 'Brick 1x4 blau',
      product_short_name: 'Brick 1x4 blau',
      product_sku: 'BR-14-BL',
      ui_display: 'Brick 1x4 blau',
      product_barcode: '1234567890123',
      quantity_demand: 2,
      location_src: 'WH/Stock/Lager Rechts/L-E2-P4',
      location_src_short: 'L-E2-P4',
      location_src_zone: 'Lager Rechts',
      voice_instruction_short: 'L-E2-P4. 2 Stueck. Brick 1x4 blau.',
    },
  ];

  const api = await mockPwaApi(page, { pickings: createPickingList().slice(0, 2) });

  await page.goto('/');
  await page.getByRole('button', { name: 'Lena Lager' }).click();
  await page.getByText('4x Brick 2x2 orange').click();

  await page.locator('.btn-confirm').click();
  await page.locator('.btn-confirm').click();
  await expect(page.locator('.completion-card')).toBeVisible();

  api.setDetail(nextDetail);
  await page.evaluate(() => window._app.handleVoiceIntent({
    intent: 'next_order',
    text: 'naechster auftrag',
    confidence: 0.95,
  }));

  await expect(page.locator('#main')).toContainText('WH/INT/00008');
  await expect(page.locator('#main')).toContainText('Brick 1x4 blau');
});
