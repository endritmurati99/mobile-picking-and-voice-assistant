# Task 3 Frontend Report — Cluster-/Batch-Picking Review Fixes

**Date:** 2026-06-24
**Branch:** feat/cluster-picking
**Commit:** 504186d
**Scope:** pwa/js/app.js (validateClusterBatch, handleClusterConfirm, enterClusterMode) + e2e/cluster.spec.js

---

## Finding #8 (Important) — validateClusterBatch: Wizard/pending_action UX dead-end

### Backend contract

Read from `backend/app/services/cluster_service.py` (`validate_batch`) and `backend/app/routers/cluster.py` (`validate_cluster_batch`):

When Odoo's `action_done` returns a wizard action dict (e.g. a backorder confirmation dialog), the service returns:

```json
{
  "success": false,
  "batch_complete": false,
  "pending_action": "stock.backorder.confirmation",
  "message": "Batch-Abschluss erfordert eine manuelle Bestätigung in Odoo (stock.backorder.confirmation)."
}
```

The field name is **`pending_action`** (set to `result.get("res_model")` from the Odoo action dict). This is the discriminating field used in the PWA fix.

### Change applied

**File:** `pwa/js/app.js` — `validateClusterBatch` function (approx. line 3423–3459 after edit)

Before: the `!result?.batch_complete` branch showed a generic yellow `'warning'` toast with no escalation guidance.

After: the branch first checks `result?.pending_action`. If truthy:
- Calls `feedbackError()` (haptic/audio error feedback)
- Shows an `'error'`-level toast: "Batch konnte nicht automatisch abgeschlossen werden. Bitte Vorgesetzte:n informieren (Odoo-Aktion erforderlich)."
- Re-enables the validate button so the picker is not stuck

The normal (non-wizard) failure path also now uses `feedbackError()` and `'error'`-level toast (was previously missing feedbackError and used `'warning'`).

### E2E test added

**File:** `e2e/cluster.spec.js`

Added test: `'Cluster-Validate: pending_action wizard zeigt Fehler-Toast und entsperrt Button'`

The test overrides the `/api/cluster/batches/9001/validate` route (after the shared mock is installed, so the specific override wins) to return the wizard shape. It navigates the full cluster entry flow, completes both lines (including the serial confirmation for line 5002), clicks validate, then asserts:
1. The text "Bitte Vorgesetzte:n informieren" is visible in the toast.
2. The `[data-cluster-validate]` button is re-enabled after the error.

---

## Finding #11 (Minor) — handleClusterConfirm: stale btn reference after loadBatch re-render

### Change applied

**File:** `pwa/js/app.js` — `handleClusterConfirm` function (approx. line 3374–3421 after edit)

Introduced a `reenableBtn()` inner function that guards the re-enable via `btn.isConnected`:

```js
function reenableBtn() {
    if (btn && btn.isConnected) btn.disabled = false;
}
```

All error paths (both the `!result?.success` early-return and the `catch` block) use `reenableBtn()` instead of `btn.disabled = false`. The success path never calls `reenableBtn()` — after `loadBatch()` re-renders the DOM, `btn` is detached and re-enabling it is both unnecessary and a reference to a dead node.

No new e2e test added; the existing flow test covers the success path (where `btn` must not be re-enabled), and the guard is a defensive correctness fix for the error paths that do not change observable behaviour in the success flow.

---

## Finding #13 (Minor) — enterClusterMode: Promise.all short-circuits on suggestions failure

### Change applied

**File:** `pwa/js/app.js` — `enterClusterMode` function (approx. line 3111–3139 after edit)

Replaced `Promise.all` with `Promise.allSettled`. The two settled results are destructured as `[suggestionsResult, pickingsResult]`:

- If `pickingsResult.status === 'rejected'`: hard-fail (abort errors return early, others render the error panel). This preserves the existing behaviour when the essential data fails.
- If `suggestionsResult.status === 'rejected'`: suggestions degrade silently to `[]`. The picker can still enter the mode and select pickings manually.
- The outer `try/catch` was removed; error handling is now done inline on the settled results.

No new e2e test added; the existing passing test exercises the happy path. The `Promise.all` → `Promise.allSettled` change has no observable effect on the success path.

---

## E2E Test Results

```
Running 2 tests using 2 workers

  ✓  [mobile-chromium] cluster.spec.js:94  Cluster-Validate: pending_action wizard zeigt Fehler-Toast und entsperrt Button (7.8s)
  ✓  [mobile-chromium] cluster.spec.js:133 Cluster-Flow: Auswahl -> Rundgang -> Serial -> Abschluss (8.0s)

  2 passed (12.9s)
```

Baseline remains green. No regressions.

---

## Commit

| Hash | Description |
|------|-------------|
| `504186d` | fix(cluster/pwa): address review findings #8, #11, #13 |

Commit range relative to previous: `97a8ba2..504186d`
