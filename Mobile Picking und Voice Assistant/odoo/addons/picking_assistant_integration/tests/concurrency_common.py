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
from datetime import timedelta
from uuid import uuid4

from odoo import SUPERUSER_ID, fields
from odoo.api import Environment
from odoo.modules.registry import Registry
from odoo.tests.common import BaseCase, get_db_name, new_test_user, tagged

API_SERVICE_GROUP = "picking_assistant_integration.group_api_service"


@tagged("post_install", "-at_install")
class CommittedConcurrencyCase(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = Registry(get_db_name())
        cls.cr = cls.registry.cursor()
        cls.env = Environment(cls.cr, SUPERUSER_ID, {})
        cls._cleanup = []
        # A committed API-service user: `_require_api_service` is a real group
        # check and SUPERUSER is NOT a member of the addon's service group.
        # The login carries a uuid so a run that dies before tearDownClass
        # cannot make the next run collide on `res.users.login`.
        cls.api_user = cls.track(
            new_test_user(
                cls.env,
                login="pwr_concurrency_%s" % uuid4().hex,
                groups="base.group_user,%s" % API_SERVICE_GROUP,
            )
        )
        cls.api_user_id = cls.api_user.id
        cls.cr.commit()

    @classmethod
    def tearDownClass(cls):
        # Fixtures were committed, so rollback will not remove them.
        for model_name, ids in reversed(cls._cleanup):
            records = cls.env[model_name].browse(ids).sudo().exists()
            if records:
                records.unlink()
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
            yield Environment(cr, SUPERUSER_ID, {})
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
            env = Environment(cr, SUPERUSER_ID, {})
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

    # ------------------------------------------------------------------
    # Fixture value helpers.
    #
    # They live HERE and only here. Two copies of a fixture builder is how a
    # test suite starts describing two different systems; this programme has
    # already been bitten by exactly that.
    # ------------------------------------------------------------------

    def _job_values(self, **overrides):
        """A running job, one delivery generation, no callback seen yet."""
        values = {
            "job_id": str(uuid4()),
            "job_type": "quality_assessment",
            "aggregate_model": "res.partner",
            "aggregate_res_id": 1,
            "aggregate_revision": 1,
            "state": "running",
            "sequence": 0,
            "attempt": 1,
            "delivery_generation": 1,
            "correlation_id": str(uuid4()),
        }
        values.update(overrides)
        return values

    def _receipt_values(self, job, state="processing", **overrides):
        values = {
            "event_id": str(uuid4()),
            "job_record_id": job.id,
            "payload_fingerprint": "a" * 64,
            "delivery_generation": job.delivery_generation,
            "state": state,
        }
        values.update(overrides)
        return values

    def _outbox_values(self, job, receipt, **overrides):
        """The outbox row that belongs to a receipt's event.

        `api_accept_event` resolves the job FROM the outbox row, and recovery
        requeues exactly that row -- a fixture without it can neither reach
        acceptance nor observe a requeue.
        """
        values = {
            "event_id": receipt.event_id,
            "job_record_id": job.id,
            "event_name": "quality.assessment.requested.v1",
            "envelope_text": '{"schema_version":"v2"}',
            "payload_fingerprint": receipt.payload_fingerprint,
            "state": "leased",
            "attempt_count": 1,
            "next_attempt_at": fields.Datetime.now(),
            "lease_owner": "worker-1",
            "lease_expires_at": fields.Datetime.now() + timedelta(seconds=60),
        }
        values.update(overrides)
        return values

    def _acceptance_args(self, job, receipt):
        """The eight positional arguments of `api_accept_event`, in the order
        declared in `receipts.py`.

        Both nonces are fresh per call because every reuse is rejected by
        design, and both are registered for cleanup: `_reserve` writes inside
        its own savepoint, so the rows survive an acceptance that goes on to
        raise -- and this base class commits.
        """
        ingress_nonce = str(uuid4())
        acceptance_nonce = str(uuid4())
        self.addCleanup(self._track_nonces, ingress_nonce, acceptance_nonce)
        return (
            receipt.event_id,
            job.job_id,
            receipt.payload_fingerprint,
            "b2n-test",
            ingress_nonce,
            job.delivery_generation,
            "n2b-test",
            acceptance_nonce,
        )

    def _track_nonces(self, *nonces):
        self.track(
            self.env["picking.assistant.webhook.nonce"]
            .sudo()
            .search([("nonce", "in", list(nonces))])
        )

    def _accept_event(self, job, receipt, env=None):
        """Call `api_accept_event` as the committed API-service user."""
        env = env or self.env
        return (
            env["picking.assistant.event.receipt"]
            .with_user(self.api_user_id)
            .api_accept_event(*self._acceptance_args(job, receipt))
        )

    def _callback_payload(self, job, receipt, token, **overrides):
        payload = {
            "callback_id": str(uuid4()),
            "source_event_id": receipt.event_id,
            "job_id": job.job_id,
            "sequence": job.sequence + 1,
            "attempt": 1,
            "delivery_generation": job.delivery_generation,
            "processing_lease_token": token,
            "status": "running",
            "result": {},
            "error": False,
            "metrics": {},
        }
        payload.update(overrides)
        return payload

    def _apply_callback(self, callback, env=None, fingerprint=None):
        """Call the real transport-level signature of `api_apply_callback`.

        The method lives on `picking.assistant.callback.receipt` and takes
        (callback, callback_fingerprint, key_id, nonce); the nonce is fresh per
        call because every reuse is rejected by design.
        """
        env = env or self.env
        nonce = str(uuid4())
        try:
            return (
                env["picking.assistant.callback.receipt"]
                .with_user(self.api_user_id)
                .api_apply_callback(
                    callback,
                    fingerprint or ("b" * 64),
                    "n2b-test",
                    nonce,
                )
            )
        finally:
            # The nonce is reserved inside its own savepoint and therefore
            # survives a rejected callback. Committed fixtures must leave the
            # database exactly as they found it, or the next run's
            # `search_count([])` assertions in the single-cursor tests count
            # this run's rows.
            self.track(
                env["picking.assistant.webhook.nonce"]
                .sudo()
                .search([("key_id", "=", "n2b-test"), ("nonce", "=", nonce)])
            )
