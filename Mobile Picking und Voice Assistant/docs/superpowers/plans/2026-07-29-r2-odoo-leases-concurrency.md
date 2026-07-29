# R2 — Odoo Leases and Concurrency Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the lease, lock-ordering and throttle defects in the Odoo addon that a single-cursor test suite structurally cannot see, and build the multi-connection test harness that makes them visible.

**Architecture:** Task 1 builds the harness and one authoritative lease primitive that every caller must use. Tasks 2–4 apply it and fix the two remaining unlocked write paths. Task 5 makes login throttling count in-flight attempts. Tasks 6–7 close the retention orphan and the two minors. The lock order becomes one global order — `nonce -> job -> receipt -> outbox` — enforced everywhere.

**Tech Stack:** Odoo 19 addon (Python), PostgreSQL row locks, Odoo's `TransactionCase`, real second connections via `odoo.registry(...).cursor()`.

## Global Constraints

- The addon under change is `odoo/addons/picking_assistant_integration/`. Do **not** edit `odoo/addons18/picking_assistant_integration/` in this lane except where a task says so explicitly — that port is governed by decision §3.4 of `docs/superpowers/parallel/2026-07-23-program-status.md`.
- Test command. **`docker compose exec odoo` is WRONG** — that container is Odoo 18 and mounts `odoo/addons18`, which is not this addon. The service that mounts `odoo/addons` is behind the `odoo19-trial` profile. `compose exec` would also bypass the entrypoint that injects `db_password`, and the long-running container already owns port 8069. Use:
  ```bash
  docker compose --profile odoo19-trial run --rm --no-deps -T odoo19-trial \
    odoo --no-http --test-enable --stop-after-init \
    --workers=0 --max-cron-threads=0 \
    -d masterfischer_o19_foundation_test -u picking_assistant_integration
  ```
  **Every flag in that command is load-bearing.** `run --rm --no-deps` instead of `up` plus `exec`,
  and `--max-cron-threads=0`, because the test database lives on the shared Postgres: a
  concurrently running Odoo service with cron threads writes `ir_cron` during module load and the
  run dies with `SerializationFailure` before a single test executes. This cost one lane a green
  run already. **Do not leave a long-running `odoo19-trial` container up** — if you started one,
  stop it before running the suite.
- The throwaway test database is `masterfischer_o19_foundation_test`. Never run these against `masterfischer`.
- Baseline: **93 addon tests, 0 failures** on the merged tree. Run the suite twice — these models must be idempotent, and a test that only passes on a fresh database is a defect.
- `_require_api_service()` guards every public `api_*` method. New public methods must call it too.
- An underscore-prefixed method name is **not** an access boundary. `create`/`write` on any model remain public ORM entry points.
- Odoo's ORM cache is not invalidated by taking a row lock. Every `FOR UPDATE` must be followed by `invalidate_recordset()` before the record is read again, or the code reads pre-lock values.
- TDD is mandatory, and for concurrency work the RED step must genuinely reproduce the race, not merely assert the invariant.

---

### Task 1: Multi-connection harness and one authoritative lease check

Finding #5 (Important). `api_apply_callback` (`models/receipts.py:388`) validates the callback
against `receipt.state == "processing"`, the lease token and the generation — but never against
`processing_lease_expires_at`. Its sibling `api_accept_event` (`models/receipts.py:232`) does check
expiry via `lease_active`. An old worker can therefore report `running`, a terminal state or a
retry in the window between lease expiry and the watchdog.

The suite cannot see this today because `TransactionCase` runs one cursor: the tests jump from
expiry straight to the watchdog and never interleave. This task builds the harness first.

**Files:**
- Create: `odoo/addons/picking_assistant_integration/tests/concurrency_common.py`
- Modify: `odoo/addons/picking_assistant_integration/tests/__init__.py`
- Create: `odoo/addons/picking_assistant_integration/tests/test_lease_expiry.py`
- Modify: `odoo/addons/picking_assistant_integration/models/receipts.py`

**Interfaces:**
- Consumes: the existing models `picking.assistant.integration.job`, `picking.assistant.event.receipt`, `picking.assistant.event.outbox`, and the existing `api_accept_event` / `api_apply_callback` on `picking.assistant.event.receipt`.
- Produces: `CommittedConcurrencyCase` in `tests/concurrency_common.py`, exposing `self.independent_env()` (a context manager yielding an `Environment` on its own connection, committing on clean exit) and `self.run_concurrently(*callables)` (runs each callable on its own connection, returns the list of results or raised exceptions in order). Model side: `_assert_active_lease(self, job, receipt, generation, supplied_token, now)` on `picking.assistant.event.receipt`, raising `ValidationError`, callable only after the row locks are held.

- [ ] **Step 1: Write the harness**

Create `odoo/addons/picking_assistant_integration/tests/concurrency_common.py`:

```python
"""Test base for races that a single cursor structurally cannot reproduce.

`TransactionCase` runs everything on one connection and rolls back at the end,
so two "concurrent" operations in such a test are really sequential statements
inside one transaction: they never contend for a row lock and never see each
other's uncommitted rows. Every lease, lock-order and throttle race in this
addon lives exactly in that blind spot.

This base class therefore commits its fixtures and cleans them up explicitly.
It is deliberately heavier than `TransactionCase` -- use it only for tests that
genuinely need two transactions.
"""

import threading
from contextlib import contextmanager

import odoo
from odoo.tests.common import BaseCase, tagged


@tagged("post_install", "-at_install")
class CommittedConcurrencyCase(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = odoo.registry(odoo.tests.common.get_db_name())
        cls.cr = cls.registry.cursor()
        cls.env = odoo.api.Environment(cls.cr, odoo.SUPERUSER_ID, {})
        cls._cleanup = []

    @classmethod
    def tearDownClass(cls):
        # Fixtures were committed, so rollback will not remove them.
        for model_name, ids in reversed(cls._cleanup):
            cls.env[model_name].browse(ids).sudo().unlink()
        cls.cr.commit()
        cls.cr.close()
        super().tearDownClass()

    @classmethod
    def track(cls, records):
        """Register committed records for deletion in tearDownClass."""
        if records:
            cls._cleanup.append((records._name, records.ids))
        return records

    @contextmanager
    def independent_env(self):
        """An Environment on its own connection and its own transaction."""
        cr = self.registry.cursor()
        try:
            yield odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
            cr.commit()
        except Exception:
            cr.rollback()
            raise
        finally:
            cr.close()

    def run_concurrently(self, *callables, timeout=30):
        """Run each callable on its own connection, started together.

        Returns a list holding, per callable and in order, either its return
        value or the exception it raised. A barrier makes both threads reach
        their first statement at the same time, which is what makes a lock
        cycle actually cycle.
        """
        barrier = threading.Barrier(len(callables))
        results = [None] * len(callables)

        def runner(index, func):
            cr = self.registry.cursor()
            env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
            try:
                barrier.wait(timeout=timeout)
                results[index] = func(env)
                cr.commit()
            except Exception as exc:  # noqa: BLE001 - the exception IS the result
                cr.rollback()
                results[index] = exc
            finally:
                cr.close()

        threads = [
            threading.Thread(target=runner, args=(index, func))
            for index, func in enumerate(callables)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=timeout)
            self.assertFalse(thread.is_alive(), "a concurrent worker did not finish")
        return results
```

Add to `odoo/addons/picking_assistant_integration/tests/__init__.py`:

```python
from . import concurrency_common
from . import test_lease_expiry
```

- [ ] **Step 2: Write the failing test that reproduces the expired-lease callback**

Create `odoo/addons/picking_assistant_integration/tests/test_lease_expiry.py`:

```python
"""An expired lease must be worthless everywhere, not only at acceptance.

Regression cover for whole-branch review finding #5.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError

from .concurrency_common import CommittedConcurrencyCase


class TestLeaseExpiry(CommittedConcurrencyCase):
    def _job_with_expired_lease(self):
        """Commit a job whose receipt holds a lease that expired one second ago."""
        env = self.env
        job = self.track(env["picking.assistant.integration.job"].create(self._job_values()))
        receipt = self.track(
            env["picking.assistant.event.receipt"].create(
                self._receipt_values(job, state="processing")
            )
        )
        now = fields.Datetime.now()
        receipt.write(
            {
                "processing_lease_token": "stale-token",
                "processing_lease_expires_at": now - timedelta(seconds=1),
            }
        )
        env.cr.commit()
        return job, receipt

    def test_callback_with_an_expired_lease_is_refused(self):
        job, receipt = self._job_with_expired_lease()
        callback = self._callback_payload(job, receipt, token="stale-token")

        with self.assertRaises(ValidationError) as caught:
            self.env["picking.assistant.event.receipt"].api_apply_callback(callback)

        self.assertIn("lease", str(caught.exception).lower())

    def test_callback_with_a_live_lease_still_succeeds(self):
        job, receipt = self._job_with_expired_lease()
        receipt.write(
            {"processing_lease_expires_at": fields.Datetime.now() + timedelta(minutes=5)}
        )
        self.env.cr.commit()
        callback = self._callback_payload(job, receipt, token="stale-token")

        result = self.env["picking.assistant.event.receipt"].api_apply_callback(callback)

        self.assertTrue(result["callback_id"])

    def test_expired_lease_blocks_media_and_artifact_access_too(self):
        """The lease check must be one primitive, not a per-call-site opinion."""
        job, receipt = self._job_with_expired_lease()
        with self.assertRaises(ValidationError):
            self.env["picking.assistant.event.receipt"]._assert_active_lease(
                job,
                receipt,
                generation=job.delivery_generation,
                supplied_token="stale-token",
                now=fields.Datetime.now(),
            )
```

`_job_values`, `_receipt_values` and `_callback_payload` already exist as helpers in
`tests/test_receipts_callbacks.py`. Move them into `concurrency_common.py` as methods of
`CommittedConcurrencyCase` and import them from there in both modules — do not duplicate them.

- [ ] **Step 3: Run the test to verify it fails for the right reason**

Run: `docker compose exec odoo odoo --no-http --test-enable --stop-after-init -d masterfischer_o19_foundation_test -u picking_assistant_integration`
Expected: `test_callback_with_an_expired_lease_is_refused` FAILS because `api_apply_callback`
returns a callback id instead of raising, and `test_expired_lease_blocks_media_and_artifact_access_too`
fails with `AttributeError: _assert_active_lease`. **If the first test passes, stop** — the race was
not reproduced and the rest of this task is unverified.

- [ ] **Step 4: Extract the one authoritative lease check**

In `odoo/addons/picking_assistant_integration/models/receipts.py`, add:

```python
    def _assert_active_lease(self, job, receipt, generation, supplied_token, now):
        """Die einzige Stelle, die eine Processing-Lease fuer gueltig erklaert.

        MUSS unter gehaltenen Row-Locks und nach `invalidate_recordset()`
        aufgerufen werden -- ohne Lock liest sie einen Wert, der beim
        Zurueckkehren schon falsch sein kann.

        Geprueft wird ALLES, nicht eine Teilmenge: Zugehoerigkeit, Generation,
        Zustand, Token und Ablauf. Frueher pruefte `api_accept_event` den
        Ablauf und `api_apply_callback` nicht -- genau das Muster, das dieser
        Review-Durchgang wiederholt gefunden hat.
        """
        if receipt.job_record_id.id != job.id:
            raise ValidationError("Receipt does not belong to this job.")
        if generation != job.delivery_generation:
            raise ValidationError("Delivery generation mismatch.")
        if receipt.state != "processing":
            raise ValidationError("Processing lease mismatch.")
        if not receipt.processing_lease_token or not supplied_token:
            raise ValidationError("Processing lease mismatch.")
        if not secrets.compare_digest(receipt.processing_lease_token, supplied_token):
            raise ValidationError("Processing lease mismatch.")
        if (
            not receipt.processing_lease_expires_at
            or receipt.processing_lease_expires_at <= now
        ):
            raise ValidationError("Processing lease has expired.")
```

Note the deliberately identical message for every ownership failure except expiry: a caller must
not learn from the error text whether it guessed the token or merely arrived late.

- [ ] **Step 5: Route every caller through it**

Replace the inline block in `api_apply_callback` (`receipts.py:387-398`) with:

```python
        self._assert_active_lease(
            job,
            receipt,
            generation=generation,
            supplied_token=callback.get("processing_lease_token") or "",
            now=fields.Datetime.now(),
        )
```

Then find every other place that forms its own opinion about lease validity:

Run: `grep -rn "processing_lease_token\|processing_lease_expires_at" odoo/addons/picking_assistant_integration/models/`

Every hit outside `_assert_active_lease` and the two places that *issue* or *clear* a lease must
be replaced by a call to the primitive. The resource and media paths in `models/resources.py` are
explicitly in scope: finding #5's second half is that they bind to the generation plus "some
active lease" rather than to the token.

- [ ] **Step 6: Run the tests to verify they pass**

Run the addon suite. Expected: the three new tests pass, all 93 existing tests still pass.

- [ ] **Step 7: Run the suite a second time**

Expected: identical result. These models must be idempotent.

- [ ] **Step 8: Commit**

```bash
git add odoo/addons/picking_assistant_integration/tests/concurrency_common.py odoo/addons/picking_assistant_integration/tests/__init__.py odoo/addons/picking_assistant_integration/tests/test_lease_expiry.py odoo/addons/picking_assistant_integration/models/receipts.py
git commit -m "fix(odoo): one authoritative lease check, and a harness that can see races"
```

---

### Task 2: No lease re-issue inside the same generation

Finding #5, second half. When `api_accept_event` finds an expired lease it hands out a fresh token
under the *same* generation (`receipts.py:246`). The old worker's token stops matching, but the
window before re-issue is real and any consumer binding to "generation plus an active lease"
rather than to the token is fooled after it. Recovery must be the only way out of an expired
lease, and recovery increments the generation.

**Files:**
- Modify: `odoo/addons/picking_assistant_integration/models/receipts.py` (the `lease_active` branch)
- Modify: `odoo/addons/picking_assistant_integration/models/integration_job.py` (recovery helper)
- Test: `odoo/addons/picking_assistant_integration/tests/test_lease_expiry.py` (extend)

**Interfaces:**
- Consumes: `_assert_active_lease` from Task 1; the existing watchdog on `picking.assistant.integration.job`.
- Produces: `_recover_expired_lease(self, job, receipt, now) -> None` on `picking.assistant.integration.job`, which atomically increments `delivery_generation`, clears the lease fields, sets the job to `retry_scheduled` and requeues the outbox row. `api_accept_event` gains the response code `processing_lease_expired` (HTTP 409 at the backend edge).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lease_expiry.py`:

```python
    def test_acceptance_does_not_reissue_a_token_in_the_same_generation(self):
        job, receipt = self._job_with_expired_lease()
        generation_before = job.delivery_generation

        with self.assertRaises(ValidationError) as caught:
            self.env["picking.assistant.event.receipt"].api_accept_event(
                *self._acceptance_args(job, receipt)
            )

        self.assertIn("processing_lease_expired", str(caught.exception))
        job.invalidate_recordset()
        self.assertEqual(job.delivery_generation, generation_before)

    def test_recovery_increments_the_generation_and_clears_the_lease(self):
        job, receipt = self._job_with_expired_lease()
        generation_before = job.delivery_generation

        self.env["picking.assistant.integration.job"]._recover_expired_lease(
            job, receipt, fields.Datetime.now()
        )

        job.invalidate_recordset()
        receipt.invalidate_recordset()
        self.assertEqual(job.delivery_generation, generation_before + 1)
        self.assertFalse(receipt.processing_lease_token)
        self.assertFalse(receipt.processing_lease_expires_at)
        self.assertEqual(job.state, "retry_scheduled")
        outbox = self.env["picking.assistant.event.outbox"].search(
            [("job_record_id", "=", job.id)], limit=1
        )
        self.assertEqual(outbox.state, "pending")

    def test_the_old_worker_is_useless_after_recovery(self):
        job, receipt = self._job_with_expired_lease()
        self.env["picking.assistant.integration.job"]._recover_expired_lease(
            job, receipt, fields.Datetime.now()
        )
        self.env.cr.commit()

        callback = self._callback_payload(job, receipt, token="stale-token")
        with self.assertRaises(ValidationError):
            self.env["picking.assistant.event.receipt"].api_apply_callback(callback)
```

`_acceptance_args` is the helper `test_receipts_callbacks.py` already uses to call
`api_accept_event` with its eight positional arguments in `receipts.py:134-144` order; move it to
`concurrency_common.py` alongside the others.

- [ ] **Step 2: Run to verify the tests fail**

Expected: `test_acceptance_does_not_reissue_a_token_in_the_same_generation` fails because
acceptance succeeds and issues a token; the other two fail with
`AttributeError: _recover_expired_lease`.

- [ ] **Step 3: Add the atomic recovery helper**

In `odoo/addons/picking_assistant_integration/models/integration_job.py`:

```python
    def _recover_expired_lease(self, job, receipt, now):
        """Die EINZIGE erlaubte Art, aus einer abgelaufenen Lease herauszukommen.

        Generation erhoehen, Lease loeschen, Job auf `retry_scheduled` setzen
        und die Outbox-Zeile requeuen -- alles zusammen, unter den bereits
        gehaltenen Locks in der globalen Reihenfolge nonce -> job -> receipt ->
        outbox. Ein alter Worker wird dadurch automatisch wertlos: seine
        Generation stimmt danach nicht mehr.

        Eine Neuvergabe des Tokens innerhalb derselben Generation ist verboten.
        Sie liess Consumer weiterlaufen, die an "Generation plus irgendeine
        aktive Lease" gebunden waren statt an das Token.
        """
```

Implement it to write all four effects in one transaction. This is also the sanctioned home of
the `queued -> retry_scheduled` edge — see decision §3.3 of the program status file. The bare edge
must be removed from the general `_transition()` in the same commit, so that recovery is the only
producer of it.

- [ ] **Step 4: Make acceptance refuse instead of re-issuing**

In `api_accept_event`, replace the `lease_active` computation and the re-issue branch so that:

- a **live** lease still returns the existing `{"accepted": True, ..., "process": False}` response,
- a **completed** receipt still returns the same,
- an **expired** lease raises `ValidationError("processing_lease_expired")`.

The backend maps that to 409 on both v2 routes; verify the existing mapping covers it and extend
the route test if it does not.

- [ ] **Step 5: Run the tests to verify they pass**

Run the addon suite twice. Expected: green both times.

- [ ] **Step 6: Commit**

```bash
git add odoo/addons/picking_assistant_integration/models/receipts.py odoo/addons/picking_assistant_integration/models/integration_job.py odoo/addons/picking_assistant_integration/tests/test_lease_expiry.py
git commit -m "fix(odoo): recover expired leases by generation, never by re-issuing a token"
```

---

### Task 3: One global lock order including the nonce

Finding #6 (Important). `api_accept_event` locks the job (`receipts.py:167`) and then reserves the
nonce; `api_apply_callback` reserves the nonce (`receipts.py:348`) and then locks the job. Two
requests carrying the same nonce can each hold one half of the cycle. PostgreSQL detects it and
aborts one transaction with `40P01`, so the damage is a 500 rather than corruption — but it is a
self-inflicted outage under exactly the contention the design expects.

The order becomes **`nonce -> job -> receipt -> outbox`** everywhere. The nonce goes first
deliberately: a later validation failure rolls back the whole RPC transaction including the nonce
reservation, so nothing is burned.

**Files:**
- Modify: `odoo/addons/picking_assistant_integration/models/receipts.py` (`api_accept_event`)
- Create: `odoo/addons/picking_assistant_integration/tests/test_lock_order.py`

**Interfaces:**
- Consumes: `picking.assistant.webhook.nonce._reserve(direction, key_id, nonce, event_id=None)`, `CommittedConcurrencyCase` from Task 1.
- Produces: no new API. The invariant is documented as a module docstring constant `LOCK_ORDER = ("nonce", "job", "receipt", "outbox")` in `receipts.py`, referenced by the test.

- [ ] **Step 1: Write the failing test**

Create `odoo/addons/picking_assistant_integration/tests/test_lock_order.py`:

```python
"""Two transactions must never be able to form a lock cycle.

Regression cover for whole-branch review finding #6. This needs two real
connections: on one cursor the two calls are sequential statements in one
transaction and can never contend.
"""

import psycopg2

from odoo import fields

from .concurrency_common import CommittedConcurrencyCase


class TestLockOrder(CommittedConcurrencyCase):
    def test_acceptance_and_callback_with_the_same_nonce_do_not_deadlock(self):
        job, receipt = self._job_with_live_lease()
        shared_nonce = "n" * 32
        acceptance = self._acceptance_args(job, receipt, nonce=shared_nonce)
        callback = self._callback_payload(job, receipt, nonce=shared_nonce)

        results = self.run_concurrently(
            lambda env: env["picking.assistant.event.receipt"].api_accept_event(*acceptance),
            lambda env: env["picking.assistant.event.receipt"].api_apply_callback(callback),
        )

        deadlocks = [
            outcome
            for outcome in results
            if isinstance(outcome, psycopg2.errors.DeadlockDetected)
        ]
        self.assertEqual(deadlocks, [], "the two paths still take locks in opposite orders")

    def test_two_acceptances_of_the_same_event_do_not_deadlock(self):
        job, receipt = self._job_with_live_lease()
        args = self._acceptance_args(job, receipt)

        results = self.run_concurrently(
            lambda env: env["picking.assistant.event.receipt"].api_accept_event(*args),
            lambda env: env["picking.assistant.event.receipt"].api_accept_event(*args),
        )

        self.assertEqual(
            [r for r in results if isinstance(r, psycopg2.errors.DeadlockDetected)], []
        )

    def test_acceptance_against_a_resource_reservation_does_not_deadlock(self):
        job, receipt = self._job_with_live_lease()
        args = self._acceptance_args(job, receipt)

        results = self.run_concurrently(
            lambda env: env["picking.assistant.event.receipt"].api_accept_event(*args),
            lambda env: env["picking.assistant.resource"]._reserve_for_job(
                job.id, job.delivery_generation, receipt.processing_lease_token
            ),
        )

        self.assertEqual(
            [r for r in results if isinstance(r, psycopg2.errors.DeadlockDetected)], []
        )

    def test_lock_order_constant_is_the_documented_one(self):
        from odoo.addons.picking_assistant_integration.models.receipts import LOCK_ORDER

        self.assertEqual(LOCK_ORDER, ("nonce", "job", "receipt", "outbox"))
```

`_job_with_live_lease` mirrors `_job_with_expired_lease` from Task 1 with a future expiry; add it
to `concurrency_common.py`. The exact signature of `_reserve_for_job` must be taken from the real
model in `models/resources.py` — read it, do not guess.

- [ ] **Step 2: Run the test to verify it fails**

Expected: `test_acceptance_and_callback_with_the_same_nonce_do_not_deadlock` FAILS with a
`DeadlockDetected` in the results list, and the constant test fails with `ImportError`. **If no
deadlock appears, stop and widen the contention** (more iterations, or a small `pg_sleep` between
the two lock acquisitions inside a debug build) until the race is genuinely reproduced. An
un-reproduced race is an un-fixed race.

- [ ] **Step 3: Move the nonce reservation to the front in acceptance**

In `api_accept_event`, move the `picking.assistant.webhook.nonce._reserve(...)` call so it runs
**before** the `SELECT ... FOR UPDATE` on the job, matching `api_apply_callback`. Add above the
class:

```python
# Eine globale Sperr-Reihenfolge, ausnahmslos, in jedem Pfad. Zwei Pfade mit
# entgegengesetzter Reihenfolge sind ein Deadlock-Zyklus, und Postgres loest
# den mit 40P01 auf -- also mit einem 500er unter genau der Last, fuer die das
# System gebaut wurde.
#
# Die Nonce steht bewusst VORNE: schlaegt eine spaetere Validierung fehl, rollt
# die gesamte RPC-Transaktion inklusive Nonce-Reservierung zurueck, es wird
# also keine Nonce verbrannt.
LOCK_ORDER = ("nonce", "job", "receipt", "outbox")
```

- [ ] **Step 4: Audit every other lock site**

Run: `grep -rn "FOR UPDATE\|_reserve(" odoo/addons/picking_assistant_integration/models/`

For each hit, write down the order it takes and confirm it is a prefix of `LOCK_ORDER`. Fix any
that are not. Record the audit result in the commit message — the previous review round found the
order was inconsistent across four paths when only two had been examined.

- [ ] **Step 5: Run the tests to verify they pass**

Run the addon suite twice. Expected: green both times, no `DeadlockDetected`.

- [ ] **Step 6: Commit**

```bash
git add odoo/addons/picking_assistant_integration/models/receipts.py odoo/addons/picking_assistant_integration/tests/test_lock_order.py odoo/addons/picking_assistant_integration/tests/concurrency_common.py
git commit -m "fix(odoo): put the nonce first in one global lock order"
```

---

### Task 4: Harden the dead-letter requeue

Finding #7 (Important). `api_requeue_dead` (`models/outbox.py:172`) searches for the dead row and
writes it without `FOR UPDATE` and without re-reading after a lock, so two requeues with a
dispatcher in between can put an already-leased row back to `pending` and deliver it twice. The
supervisor check uses `.exists()` and `has_group`, neither of which excludes an archived or share
user.

**Files:**
- Modify: `odoo/addons/picking_assistant_integration/models/outbox.py:172-200`
- Test: `odoo/addons/picking_assistant_integration/tests/test_job_outbox_transaction.py` (extend)
- Create: `odoo/addons/picking_assistant_integration/tests/test_requeue_concurrency.py`

**Interfaces:**
- Consumes: `LOCK_ORDER` from Task 3, `CommittedConcurrencyCase` from Task 1.
- Produces: no new public API. `api_requeue_dead` keeps its `(event_id, supervisor_user_id, reason)` signature and its return shape.

- [ ] **Step 1: Write the failing tests**

Create `odoo/addons/picking_assistant_integration/tests/test_requeue_concurrency.py`:

```python
"""A dead-letter requeue must never resurrect a leased row.

Regression cover for whole-branch review finding #7.
"""

from odoo.exceptions import AccessError

from .concurrency_common import CommittedConcurrencyCase


class TestRequeueConcurrency(CommittedConcurrencyCase):
    def test_two_requeues_do_not_both_reset_the_row(self):
        outbox = self._dead_outbox_row()
        supervisor = self._active_supervisor()

        results = self.run_concurrently(
            lambda env: env["picking.assistant.event.outbox"].api_requeue_dead(
                outbox.event_id, supervisor.id, "first"
            ),
            lambda env: env["picking.assistant.event.outbox"].api_requeue_dead(
                outbox.event_id, supervisor.id, "second"
            ),
        )

        succeeded = [r for r in results if isinstance(r, dict)]
        self.assertEqual(
            len(succeeded), 1, "exactly one requeue may win; the other must find no dead row"
        )

    def test_requeue_clears_the_dispatcher_lease(self):
        outbox = self._dead_outbox_row(lease_token="held-by-a-dispatcher")
        supervisor = self._active_supervisor()

        self.env["picking.assistant.event.outbox"].api_requeue_dead(
            outbox.event_id, supervisor.id, "reason"
        )

        outbox.invalidate_recordset()
        self.assertEqual(outbox.state, "pending")
        self.assertFalse(outbox.lease_token)
        self.assertFalse(outbox.lease_expires_at)

    def test_archived_supervisor_is_refused(self):
        outbox = self._dead_outbox_row()
        supervisor = self._active_supervisor()
        supervisor.sudo().write({"active": False})
        self.env.cr.commit()

        with self.assertRaises(AccessError):
            self.env["picking.assistant.event.outbox"].api_requeue_dead(
                outbox.event_id, supervisor.id, "reason"
            )

    def test_share_user_with_the_group_is_refused(self):
        outbox = self._dead_outbox_row()
        supervisor = self._active_supervisor()
        supervisor.sudo().write({"share": True})
        self.env.cr.commit()

        with self.assertRaises(AccessError):
            self.env["picking.assistant.event.outbox"].api_requeue_dead(
                outbox.event_id, supervisor.id, "reason"
            )
```

`_dead_outbox_row` and `_active_supervisor` go into `concurrency_common.py`. The lease field names
must be taken from the real model — read `models/outbox.py` and use its actual names.

- [ ] **Step 2: Run to verify the tests fail**

Expected: `test_two_requeues_do_not_both_reset_the_row` reports two successes;
`test_archived_supervisor_is_refused` and `test_share_user_with_the_group_is_refused` do not raise.

- [ ] **Step 3: Lock, revalidate, clear, and tighten the actor check**

Rewrite the body of `api_requeue_dead` so that it:

1. resolves and validates the supervisor **before** taking any lock, requiring
   `supervisor.active and not supervisor.share and supervisor.has_group(...)`;
2. selects the dead row's id, then takes `SELECT ... FOR UPDATE` on it;
3. calls `invalidate_recordset()` and re-reads `state`, raising if it is no longer `dead`;
4. writes `state = "pending"` and clears the lease token and lease expiry in the same write;
5. keeps the job lock ahead of the outbox lock, per `LOCK_ORDER`.

```python
        supervisor = self.env["res.users"].sudo().browse(int(supervisor_user_id)).exists()
        if (
            not supervisor
            or not supervisor.active
            or supervisor.share
            or not supervisor.has_group(
                "picking_assistant_integration.group_supervisor"
            )
        ):
            raise AccessError("Supervisor role required.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run the addon suite twice. Expected: green both times.

- [ ] **Step 5: Commit**

```bash
git add odoo/addons/picking_assistant_integration/models/outbox.py odoo/addons/picking_assistant_integration/tests/test_requeue_concurrency.py odoo/addons/picking_assistant_integration/tests/concurrency_common.py
git commit -m "fix(odoo): lock, revalidate and clear the lease on dead-letter requeue"
```

---

### Task 5: Make login throttling count in-flight attempts

Finding #10 (Important). `SessionService.login` (`backend/app/services/auth_sessions.py:146`)
calls `api_check_login`, then performs the expensive `authenticate_credentials`, and only then
calls `api_record_login_result`. Each of those is its own RPC transaction, so N parallel requests
all pass the check before the first failure is booked. The limit bounds rounds, not attempts.

**This task crosses into `backend/`.** R1 also edits backend files — coordinate: this task touches
`auth_sessions.py` only, R1 touches `config.py`, `main.py`, `dependencies.py`, `n8n_internal.py`,
`binary_validation.py`. No overlap. Keep the edit strictly local to the `login` method.

**Files:**
- Modify: `odoo/addons/picking_assistant_integration/models/auth_throttle.py`
- Modify: `backend/app/services/auth_sessions.py:135-175`
- Test: `odoo/addons/picking_assistant_integration/tests/test_session_throttle.py` (extend)
- Test: `backend/tests/test_auth_sessions.py` (extend)
- Modify (decision §3.4 permitting): `odoo/addons18/picking_assistant_integration/models/auth_throttle.py` — the v18 port carries the same defect

**Interfaces:**
- Consumes: existing fields on `picking.assistant.auth.throttle` — `login_key`, `source_ip_hmac`, `failure_count`, `window_started_at`, `locked_until`, `last_attempt_at`, `expires_at`; existing `_lock_or_create(login_key, source_ip_hmac, now)`, `FAILURE_WINDOW = timedelta(minutes=15)`, `FAILURE_THRESHOLD = 5`, `ROW_TTL = timedelta(hours=24)`.
- Produces: new field `in_flight_count: Integer`, new constant `IN_FLIGHT_TTL = timedelta(seconds=30)`, and two new public methods on `picking.assistant.auth.throttle`:
  - `api_begin_login_attempt(login_key, source_ip_hmac) -> dict` with keys `allowed: bool` and `attempt_token: str` (empty when not allowed)
  - `api_finish_login_attempt(login_key, source_ip_hmac, attempt_token, succeeded) -> dict` returning the same `_state_payload` shape as `api_record_login_result`
  `api_check_login` and `api_record_login_result` stay for backwards compatibility but are no longer called by the backend.

- [ ] **Step 1: Write the failing tests**

Append to `odoo/addons/picking_assistant_integration/tests/test_session_throttle.py`, converting
the module to use `CommittedConcurrencyCase` for the new tests only:

```python
    def test_parallel_attempts_cannot_all_pass_the_check(self):
        """Five in-flight attempts consume the budget even before any of them
        has failed. Regression cover for finding #10."""
        login_key, ip_key = "picker@example.com", "hmac-value"

        results = self.run_concurrently(
            *[
                (lambda env: env["picking.assistant.auth.throttle"].api_begin_login_attempt(
                    login_key, ip_key
                ))
                for _ in range(8)
            ]
        )

        allowed = [r for r in results if isinstance(r, dict) and r["allowed"]]
        self.assertLessEqual(len(allowed), 5, "in-flight attempts must count against the limit")

    def test_a_finished_successful_attempt_frees_its_slot(self):
        login_key, ip_key = "picker2@example.com", "hmac-value"
        model = self.env["picking.assistant.auth.throttle"]
        started = model.api_begin_login_attempt(login_key, ip_key)
        self.assertTrue(started["allowed"])

        model.api_finish_login_attempt(login_key, ip_key, started["attempt_token"], True)

        record = model.search(
            [("login_key", "=", login_key), ("source_ip_hmac", "=", ip_key)], limit=1
        )
        self.assertEqual(record.in_flight_count, 0)
        self.assertEqual(record.failure_count, 0)

    def test_a_finished_failed_attempt_becomes_a_recorded_failure(self):
        login_key, ip_key = "picker3@example.com", "hmac-value"
        model = self.env["picking.assistant.auth.throttle"]
        started = model.api_begin_login_attempt(login_key, ip_key)

        model.api_finish_login_attempt(login_key, ip_key, started["attempt_token"], False)

        record = model.search(
            [("login_key", "=", login_key), ("source_ip_hmac", "=", ip_key)], limit=1
        )
        self.assertEqual(record.in_flight_count, 0)
        self.assertEqual(record.failure_count, 1)

    def test_an_abandoned_attempt_stops_counting_after_the_ttl(self):
        """A crashed backend must not lock an account out forever."""
        from datetime import timedelta

        from odoo import fields

        login_key, ip_key = "picker4@example.com", "hmac-value"
        model = self.env["picking.assistant.auth.throttle"]
        for _ in range(5):
            model.api_begin_login_attempt(login_key, ip_key)
        self.assertFalse(model.api_begin_login_attempt(login_key, ip_key)["allowed"])

        record = model.search(
            [("login_key", "=", login_key), ("source_ip_hmac", "=", ip_key)], limit=1
        )
        record.write({"last_attempt_at": fields.Datetime.now() - timedelta(seconds=31)})

        self.assertTrue(model.api_begin_login_attempt(login_key, ip_key)["allowed"])
```

Append to `backend/tests/test_auth_sessions.py`:

```python
@pytest.mark.asyncio
async def test_login_reserves_before_authenticating(monkeypatch):
    """The expensive authentication must never run before the attempt is
    booked. Regression cover for finding #10."""
    calls: list[str] = []

    class RecordingOdoo(FakeOdoo):
        async def execute_kw(self, model, method, args):
            if method in {"api_begin_login_attempt", "api_finish_login_attempt"}:
                calls.append(method)
            return await super().execute_kw(model, method, args)

        async def authenticate_credentials(self, login, password):
            calls.append("authenticate")
            return 0

    service = _service(RecordingOdoo())
    with pytest.raises(AuthenticationFailed):
        await service.login(_login_body(), source_ip="10.0.0.1", origin="https://localhost")

    assert calls == ["api_begin_login_attempt", "authenticate", "api_finish_login_attempt"]
    assert "api_check_login" not in calls
```

`FakeOdoo`, `_service` and `_login_body` are the fixtures that module already uses; reuse them
rather than adding new ones.

- [ ] **Step 2: Run to verify the tests fail**

Expected: Odoo side — `AttributeError: api_begin_login_attempt`. Backend side —
`assert calls == [...]` fails, showing `api_check_login` and the record-after-authenticate order.

- [ ] **Step 3: Add the in-flight reservation to the Odoo model**

In `models/auth_throttle.py`:

```python
IN_FLIGHT_TTL = timedelta(seconds=30)
```

```python
    in_flight_count = fields.Integer(required=True, default=0)
```

```python
    @api.model
    def api_begin_login_attempt(self, login_key, source_ip_hmac):
        """Reserviert einen Login-Versuch, BEVOR das teure Authentifizieren laeuft.

        Frueher pruefte der Backend-Login erst das Limit, authentifizierte dann
        und verbuchte den Fehlschlag zuletzt -- drei getrennte Transaktionen.
        Beliebig viele parallele Requests kamen deshalb alle durch, bevor der
        erste Fehlschlag ueberhaupt gebucht war: das Limit begrenzte Runden,
        nicht Versuche.

        In-flight-Reservierungen zaehlen gegen dasselbe Limit wie gebuchte
        Fehlschlaege. Eine Reservierung, die laenger als IN_FLIGHT_TTL keine
        Antwort bekommen hat, verfaellt -- sonst wuerde ein abgestuerztes
        Backend einen Account dauerhaft aussperren.
        """
        self.env["picking.assistant.api.mixin"]._require_api_service()
        now = fields.Datetime.now()
        record = self._lock_or_create(login_key, source_ip_hmac, now)
        self._expire_stale_in_flight(record, now)
        if record.failure_count + record.in_flight_count >= FAILURE_THRESHOLD:
            return {"allowed": False, "attempt_token": ""}
        if record.locked_until and record.locked_until > now:
            return {"allowed": False, "attempt_token": ""}
        token = secrets.token_urlsafe(24)
        record.write(
            {
                "in_flight_count": record.in_flight_count + 1,
                "last_attempt_at": now,
            }
        )
        return {"allowed": True, "attempt_token": token}

    @api.model
    def api_finish_login_attempt(self, login_key, source_ip_hmac, attempt_token, succeeded):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        now = fields.Datetime.now()
        record = self._lock_or_create(login_key, source_ip_hmac, now)
        values = {"in_flight_count": max(0, record.in_flight_count - 1)}
        if not succeeded:
            values.update(self._failure_values(record, now))
        else:
            values.update({"failure_count": 0, "locked_until": False})
        record.write(values)
        return self._state_payload(record, now)
```

`_failure_values(record, now)` is the failure bookkeeping currently inlined in
`api_record_login_result`; extract it so both methods share one implementation rather than
maintaining two. `_expire_stale_in_flight(record, now)` zeroes `in_flight_count` when
`record.last_attempt_at` is older than `IN_FLIGHT_TTL`. Add `import secrets` if absent.

The `attempt_token` is returned for tracing and for the backend to prove it is finishing its own
attempt; because the counter is per (login, ip) row rather than per token, the token is not load-
bearing for correctness. Do not let a later change make it load-bearing without persisting it.

- [ ] **Step 4: Rewire the backend login**

In `backend/app/services/auth_sessions.py`, in `login`, replace the `api_check_login` call with
`api_begin_login_attempt`, and replace **both** `api_record_login_result` calls with
`api_finish_login_attempt` carrying the returned `attempt_token`. The reservation must be released
on **every** exit path from that point on, including exceptions — wrap the authentication and
identity lookup in `try`/`except`/`finally` so an exception cannot leak a reservation. A leaked
reservation that never expires is a protection that becomes an outage; `IN_FLIGHT_TTL` is the
backstop, not the plan.

- [ ] **Step 5: Port the same fix to the v18 addon**

Only if decision §3.4 kept the v18 port. `odoo/addons18/picking_assistant_integration/` carries
the identical throttle model and therefore the identical defect. Apply the same change, adapting
`models.Constraint` to `_sql_constraints` as that port already does, and add the two model-level
tests (not the concurrency ones) to its test module.

- [ ] **Step 6: Run both suites to verify they pass**

Run the addon suite twice and
`cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`.
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add odoo/addons/picking_assistant_integration/models/auth_throttle.py odoo/addons/picking_assistant_integration/tests/test_session_throttle.py backend/app/services/auth_sessions.py backend/tests/test_auth_sessions.py
git commit -m "fix(auth): count in-flight login attempts against the throttle limit"
```

---

### Task 6: Stop retention from orphaning a non-terminal job

Finding #11 (Important). `integration_job.py:379` deletes old `delivered`/`dead` outbox rows
regardless of the job's state. The watchdog then moves the job and receipt to retry but tolerates a
missing outbox row, so after a long outage a job can sit in `retry_scheduled` forever with nothing
to deliver.

**Files:**
- Modify: `odoo/addons/picking_assistant_integration/models/integration_job.py:370-400`
- Test: `odoo/addons/picking_assistant_integration/tests/test_crons_retention.py` (extend)

**Interfaces:**
- Consumes: the existing retention cron and watchdog on `picking.assistant.integration.job`.
- Produces: no new API. The retention domain gains a job-state condition; the watchdog gains a fail-closed branch.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_crons_retention.py`:

```python
    def test_retention_keeps_the_outbox_of_a_non_terminal_job(self):
        """Deleting the only deliverable of a live job strands it forever.
        Regression cover for finding #11."""
        job = self._job(state="retry_scheduled")
        outbox = self._outbox(job, state="delivered", created_days_ago=90)

        self.env["picking.assistant.integration.job"]._gc_retention()

        self.assertTrue(outbox.exists(), "a non-terminal job must keep its outbox row")

    def test_retention_still_deletes_the_outbox_of_a_terminal_job(self):
        job = self._job(state="succeeded")
        outbox = self._outbox(job, state="delivered", created_days_ago=90)

        self.env["picking.assistant.integration.job"]._gc_retention()

        self.assertFalse(outbox.exists())

    def test_watchdog_refuses_to_retry_a_job_without_an_outbox_row(self):
        job = self._job(state="processing")
        self._outbox(job, state="delivered").unlink()

        self.env["picking.assistant.integration.job"]._watchdog()

        job.invalidate_recordset()
        self.assertNotEqual(
            job.state,
            "retry_scheduled",
            "a job with nothing to deliver must not be scheduled for delivery",
        )
        self.assertEqual(job.state, "review_required")
```

`_job`, `_outbox`, `_gc_retention` and `_watchdog` must use the names the module and model already
use — read them before writing. If there is no `review_required` state, add it to the state
selection and to the frozen TRANSITIONS table in the same commit, and record that as a plan
amendment in the program status file.

- [ ] **Step 2: Run to verify the tests fail**

Expected: the outbox row of the non-terminal job is deleted, and the watchdog sets
`retry_scheduled` on a job with no outbox row.

- [ ] **Step 3: Add the job-state condition to retention**

Restrict the retention domain so that an outbox row is deletable only when its job is in a
terminal state. Add the reasoning as a comment:

```python
        # Eine Outbox-Zeile ist die einzige Lieferanweisung eines Jobs. Sie zu
        # loeschen, waehrend der Job noch nicht terminal ist, laesst einen Job
        # zurueck, den der Watchdog zwar auf retry setzt, fuer den es aber
        # nichts mehr zu liefern gibt.
```

- [ ] **Step 4: Make the watchdog fail closed**

Where the watchdog moves a job to `retry_scheduled`, require the outbox row to exist. When it does
not, move the job to `review_required` and log it at warning level with the job id only — never the
payload.

- [ ] **Step 5: Run the tests to verify they pass**

Run the addon suite twice. Expected: green both times.

- [ ] **Step 6: Commit**

```bash
git add odoo/addons/picking_assistant_integration/models/integration_job.py odoo/addons/picking_assistant_integration/tests/test_crons_retention.py
git commit -m "fix(odoo): never delete the outbox of a job that still has work"
```

---

### Task 7: Close the two minors

Findings M1 and M2. `models/session.py:111` can hand back a session that was revoked or expired
concurrently, because role marking re-reads without a lock. The nonce GC deletes at most 1000 rows
per ten-minute run and reports no remainder, so from roughly 1.67 expired nonces per second the
backlog grows without any signal.

**Files:**
- Modify: `odoo/addons/picking_assistant_integration/models/session.py:100-120`
- Modify: `odoo/addons/picking_assistant_integration/models/receipts.py` (nonce GC)
- Test: `odoo/addons/picking_assistant_integration/tests/test_session_throttle.py` (extend)
- Test: `odoo/addons/picking_assistant_integration/tests/test_crons_retention.py` (extend)

**Interfaces:**
- Consumes: the existing session model and the existing nonce GC cron.
- Produces: the nonce GC returns `{"deleted": int, "remaining": int}` instead of `None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session_throttle.py`:

```python
    def test_role_marking_rechecks_revocation_under_lock(self):
        """A session revoked between resolution and role marking must not be
        handed back for the rest of the request. Cover for minor M1."""
        session = self._active_session()

        def revoke(env):
            env["picking.assistant.session"].browse(session.id).write({"revoked": True})

        def mark(env):
            return env["picking.assistant.session"]._mark_roles(session.id)

        results = self.run_concurrently(revoke, mark)
        marked = results[1]
        if not isinstance(marked, Exception):
            self.assertFalse(marked, "a revoked session must not survive role marking")
```

Append to `tests/test_crons_retention.py`:

```python
    def test_nonce_gc_reports_what_it_could_not_delete(self):
        """Silent truncation reads as 'cleaned up' when it is not. Cover for M2."""
        self._expired_nonces(count=1200)

        result = self.env["picking.assistant.webhook.nonce"]._gc_expired(batch_size=500)

        self.assertEqual(result["deleted"], 500)
        self.assertGreater(result["remaining"], 0)

    def test_nonce_gc_drains_a_backlog_across_batches(self):
        self._expired_nonces(count=1200)
        model = self.env["picking.assistant.webhook.nonce"]

        remaining = None
        for _ in range(10):
            result = model._gc_expired(batch_size=500)
            remaining = result["remaining"]
            if not remaining:
                break

        self.assertEqual(remaining, 0)
```

- [ ] **Step 2: Run to verify the tests fail**

Expected: the GC returns `None`, so subscripting raises `TypeError`; the session test shows a
revoked session still being marked.

- [ ] **Step 3: Re-check the session under lock**

In `models/session.py`, take `FOR UPDATE` on the session row, call `invalidate_recordset()`, then
re-check `revoked` and `expires_at` before marking roles. Return falsy when either fails.

- [ ] **Step 4: Make the nonce GC loop and report**

Change `_gc_expired` to return `{"deleted": deleted, "remaining": remaining}`, where `remaining` is
a `search_count` of still-expired rows after the batch. Have the cron keep calling it while
`remaining` is non-zero and the elapsed time is under a bound, and log a warning when it exits with
`remaining > 0`. Do not silently cap.

- [ ] **Step 5: Run the tests to verify they pass**

Run the addon suite twice. Expected: green both times.

- [ ] **Step 6: Commit**

```bash
git add odoo/addons/picking_assistant_integration/models/session.py odoo/addons/picking_assistant_integration/models/receipts.py odoo/addons/picking_assistant_integration/tests/test_session_throttle.py odoo/addons/picking_assistant_integration/tests/test_crons_retention.py
git commit -m "fix(odoo): recheck sessions under lock and drain the nonce GC backlog"
```

---

### Task 8: Carry the lease token into the resource contract

Added 2026-07-29, raised by Task 1's implementer. Task 1 routed
`resources.py::_require_current_generation` through `_assert_active_lease`, but the resource
JSON-RPC contract carries no lease token, so those calls pass `require_token=False`. They accept
"the generation matches and *some* lease is active" instead of "this caller holds *the* lease" —
the same defence-weaker-in-the-sibling shape this whole lane exists to remove. It could not be
closed inside Task 1 because it needs a contract change on both sides of the wire.

Run this task **last** in the lane: it changes a wire format, and every earlier task should be
settled before the contract moves.

**Files:**
- Modify: `odoo/addons/picking_assistant_integration/models/resources.py`
- Modify: `backend/app/routers/n8n_v2.py` (the media and artifact routes)
- Modify: `backend/app/models/` (the v2 request schemas for media and artifact)
- Modify: the n8n v2 workflow nodes that call the media and artifact routes
- Test: `odoo/addons/picking_assistant_integration/tests/test_resources.py`
- Test: `backend/tests/test_n8n_v2_binary_routes.py`

**Interfaces:**
- Consumes: `_assert_active_lease(job, receipt, generation, supplied_token, now)` from Task 1, including its `require_token` parameter.
- Produces: `processing_lease_token` becomes a required, signed field on every media and artifact request envelope. `require_token=False` is **deleted** — the parameter must not survive as an opt-out that a future caller can reach for.

- [ ] **Step 1: Write the failing tests**

The Odoo test must prove that a request carrying a *stale but still-active-lease-era* token is
refused, which today's `require_token=False` path accepts:

```python
    def test_resource_access_requires_the_callers_own_lease_token(self):
        """generation + 'some active lease' is not ownership. Cover for #5b."""
        job, receipt = self._job_with_live_lease()
        with self.assertRaises(ValidationError):
            self.env["picking.assistant.resource"]._require_current_generation(
                job.id, job.delivery_generation, supplied_token="not-the-held-token"
            )

    def test_require_token_opt_out_no_longer_exists(self):
        import inspect

        from odoo.addons.picking_assistant_integration.models.receipts import (
            EventReceipt,
        )

        signature = inspect.signature(EventReceipt._assert_active_lease)
        self.assertNotIn("require_token", signature.parameters)
```

The backend test must prove the field is required and signed — an unsigned token is a token an
attacker supplies:

```python
def test_media_request_without_a_lease_token_is_rejected():
    body = _valid_media_body()
    del body["processing_lease_token"]
    response = _post_signed("/api/n8n/v2/jobs/media", body)
    assert response.status_code == 422


def test_lease_token_is_part_of_the_signed_bytes():
    body = _valid_media_body()
    signed = _sign(body)
    body["processing_lease_token"] = "swapped-after-signing"
    response = _post_raw("/api/n8n/v2/jobs/media", body, signature=signed)
    assert response.status_code == 401
```

Use the helper names `backend/tests/test_n8n_v2_binary_routes.py` already defines; read it first.

- [ ] **Step 2: Run to verify the tests fail**

Expected: the Odoo call succeeds with a wrong token, `require_token` is still in the signature,
and the backend accepts a body with no token.

- [ ] **Step 3: Add the field to the envelopes and thread it through**

Add `processing_lease_token` as a required field on the media and artifact v2 request schemas.
It is part of the signed body, so it inherits replay and tamper protection from the existing
signature — do not add a second mechanism.

- [ ] **Step 4: Delete the opt-out**

Remove the `require_token` parameter from `_assert_active_lease` entirely and update every caller.
A named opt-out on a security primitive becomes the default for whoever is in a hurry next.

- [ ] **Step 5: Update the n8n workflow nodes**

The v2 workflow must pass the token it received from the acceptance response into every subsequent
media and artifact call. Re-run the verifier from lane R3 against the changed workflow.

- [ ] **Step 6: Run both suites twice**

Expected: green, both runs identical.

- [ ] **Step 7: Commit**

```bash
git add odoo/addons/picking_assistant_integration/models/resources.py odoo/addons/picking_assistant_integration/models/receipts.py odoo/addons/picking_assistant_integration/tests/test_resources.py backend/app/routers/n8n_v2.py backend/tests/test_n8n_v2_binary_routes.py
git commit -m "fix(odoo): bind resource access to the caller's own lease token"
```

---

## Lane exit gate

- [ ] The addon suite runs twice with identical, green results
- [ ] `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q` is green (Task 5 touches it)
- [ ] Every concurrency test genuinely failed before its fix — a test that never went red proves nothing
- [ ] The lock-order audit from Task 3 Step 4 is written into the commit message
- [ ] Adversarial review: `codex exec --sandbox read-only "<diff brief>"`, focused on: does any code path still form its own opinion about lease validity; is `LOCK_ORDER` respected in every path including resources and media; can a reservation leak in the throttle; can retention still strand a job
- [ ] Update the debt register in `docs/superpowers/parallel/2026-07-23-program-status.md` — mark #5, #6, #7, #10, #11, M1, M2 closed with their commit hashes
