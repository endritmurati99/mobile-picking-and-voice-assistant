const { test, expect } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;
const { mockPwaApi } = require('./helpers/pwa-api');

function createBuilder(page, includeSelector) {
  const builder = new AxeBuilder({ page }).withTags([
    'wcag2a',
    'wcag2aa',
    'wcag21a',
    'wcag21aa',
  ]);

  if (includeSelector) {
    builder.include(includeSelector);
  }

  return builder;
}

async function expectNoViolations(page, testInfo, includeSelector) {
  const results = await createBuilder(page, includeSelector).analyze();
  await testInfo.attach('axe-results', {
    body: JSON.stringify(results, null, 2),
    contentType: 'application/json',
  });
  expect(results.violations).toEqual([]);
}

test('picking list has no automatically detectable accessibility violations', async ({ page }, testInfo) => {
  await mockPwaApi(page);
  await page.goto('/');
  await expect(page.getByText('WH/INT/00007')).toBeVisible();
  await expectNoViolations(page, testInfo, '#app');
});

test('picking detail has no automatically detectable accessibility violations', async ({ page }, testInfo) => {
  await mockPwaApi(page);
  await page.goto('/');
  await page.getByText('WH/INT/00007').click();
  await expect(page.locator('#main')).toContainText('Brick 2x2 orange');
  await expectNoViolations(page, testInfo, '#main');
});

test('quality alert form has no automatically detectable accessibility violations', async ({ page }, testInfo) => {
  await mockPwaApi(page);
  await page.goto('/');
  await page.getByText('WH/INT/00007').click();
  await page.locator('#btn-alert').click();
  await expect(page.getByRole('heading', { name: 'Problem melden' })).toBeVisible();
  await expectNoViolations(page, testInfo, '#main');
});
