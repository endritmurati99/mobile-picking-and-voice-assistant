# PWA Review Gate Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the reviewed PWA gate pass again by fixing invalid assets, restoring 320px list usability, and stabilizing the detail visual snapshot without touching the Odoo or Voice business changes.

**Architecture:** Keep fixes scoped to PWA assets, CSS, and Playwright test stability. Add regression tests before changing production files. Do not alter FastAPI, Odoo routing, or voice intent semantics.

**Tech Stack:** Vanilla JS PWA, CSS, Web App Manifest, Node `node:test`, Playwright Test.

---

## Scope

In scope:

- Validate PWA CSS font URLs and manifest icon files.
- Replace invalid local PWA assets or route CSS to valid local assets.
- Make the 320px list screen show the first picking card inside the first viewport.
- Remove focus/hover instability from the visual detail snapshot.
- Re-run targeted and full UI verification.

Out of scope:

- Any backend/Odoo/Voice intent behavior change.
- Any baseline update before understanding the visual delta.
- Any commit, push, or broad staging action.

## File Structure

- Modify: `pwa/css/app.css`
  - Route the sans font to a valid bundled file.
  - Add compact mobile spacing for very narrow screens.
- Modify binary assets: `pwa/icons/icon-192.png`, `pwa/icons/icon-512.png`
  - Replace placeholder bytes with valid PNG icons matching manifest sizes.
- Create: `pwa/js/tests/pwa-assets.test.mjs`
  - Assert CSS font URLs point at valid WOFF2 files.
  - Assert manifest PNG icon files are valid PNGs with declared dimensions.
- Modify: `e2e/visual.spec.js`
  - Stabilize visual snapshot state by moving focus away from bottom-nav controls before screenshot.

---

### Task 1: PWA Asset Contract

**Files:**
- Create: `pwa/js/tests/pwa-assets.test.mjs`
- Modify: `pwa/css/app.css`
- Modify binary: `pwa/icons/icon-192.png`
- Modify binary: `pwa/icons/icon-512.png`

- [x] **Step 1: Write the failing asset test**

Create `pwa/js/tests/pwa-assets.test.mjs` with tests that:

- Read `pwa/css/app.css`.
- Extract `url("/fonts/...woff2")` references.
- Assert each referenced WOFF2 exists and starts with magic bytes `wOF2`.
- Read `pwa/manifest.json`.
- Assert every `image/png` icon exists, starts with PNG signature, and its IHDR width/height match the manifest `sizes`.

- [x] **Step 2: Run test to verify red**

Run: `node --test pwa/js/tests/pwa-assets.test.mjs`

Expected: FAIL because `pwa/fonts/plus-jakarta-sans-latin-variable.woff2` is HTML, and `pwa/icons/icon-192.png` / `icon-512.png` are invalid placeholder bytes.

- [x] **Step 3: Implement minimal asset fix**

Change `pwa/css/app.css` so the sans font uses existing valid `outfit-latin-variable.woff2`.

Generate valid PNG icons:

- `pwa/icons/icon-192.png` must be 192x192 PNG.
- `pwa/icons/icon-512.png` must be 512x512 PNG.

- [x] **Step 4: Run test to verify green**

Run: `node --test pwa/js/tests/pwa-assets.test.mjs`

Expected: PASS.

---

### Task 2: 320px List Usability

**Files:**
- Modify: `pwa/css/app.css`
- Test: `e2e/mobile-refresh.spec.js`

- [x] **Step 1: Verify current failing test**

Run: `npx playwright test e2e/mobile-refresh.spec.js --project=mobile-chromium -g "keeps list, detail, and quality alert usable at 320px width"`

Expected: FAIL at `firstCard.top` because the first card starts below the first viewport.

- [x] **Step 2: Implement compact narrow-screen CSS**

Add a `@media (max-width: 360px)` block in `pwa/css/app.css` that reduces top chrome density on the list view without horizontal overflow:

- smaller page padding,
- smaller header/search/filter spacing,
- smaller list workspace gap,
- compact queue overview spacing.

- [x] **Step 3: Run test to verify green**

Run: `npx playwright test e2e/mobile-refresh.spec.js --project=mobile-chromium -g "keeps list, detail, and quality alert usable at 320px width"`

Expected: PASS.

---

### Task 3: Detail Visual Snapshot Stability

**Files:**
- Modify: `e2e/visual.spec.js`

- [x] **Step 1: Verify current failing visual test**

Run: `npx playwright test e2e/visual.spec.js --project=mobile-chromium -g "picking detail matches the mobile visual baseline"`

Expected: FAIL with a small diff around `Scan Kamera` bottom-nav focus/hover state.

- [x] **Step 2: Stabilize focus state before screenshots**

Update the visual snapshot helper to move focus to a neutral app container before calling `toHaveScreenshot()`.

- [x] **Step 3: Run test to verify green**

Run: `npx playwright test e2e/visual.spec.js --project=mobile-chromium -g "picking detail matches the mobile visual baseline"`

Expected: PASS. If it still fails with a meaningful layout diff, stop and inspect before changing baselines.

---

### Task 4: Full Verification

**Files:**
- No new implementation files unless a prior task requires a small adjustment.

- [x] **Step 1: Run PWA unit tests**

Run: `npm run test:voice`

Expected: PASS.

- [x] **Step 2: Run full Playwright UI gate**

Run: `npm run test:ui`

Expected: PASS.

- [x] **Step 3: Run rendered PWA smoke**

Run a temporary Playwright smoke against `http://127.0.0.1:4173/`:

- app loads with title `Picking Assistant`,
- picker can be selected,
- a picking detail renders,
- completing the mocked picking reaches completion,
- `next_order` opens the next picking,
- collect console warnings/errors and screenshot evidence.

Expected: no relevant runtime errors; no invalid font/icon warnings.

## Self-Review

- Spec coverage: covers all review findings from the PWA gate: invalid assets, 320px layout, detail visual instability, and rendered smoke.
- Placeholder scan: no `TODO`, `TBD`, or unspecified test commands.
- Type consistency: all touched paths are existing PWA or E2E paths; new asset test uses Node `node:test` like existing PWA unit tests.
