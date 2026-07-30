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
            lambda env: env["picking.assistant.outbox"]
            .with_user(self.api_user_id)
            .api_requeue_dead(outbox.event_id, supervisor.id, "first"),
            lambda env: env["picking.assistant.outbox"]
            .with_user(self.api_user_id)
            .api_requeue_dead(outbox.event_id, supervisor.id, "second"),
        )

        succeeded = [r for r in results if isinstance(r, dict)]
        self.assertEqual(
            len(succeeded), 1, "exactly one requeue may win; the other must find no dead row"
        )
        # `run_concurrently` commits `self.cr` before starting the workers,
        # which (Odoo runs REPEATABLE READ, per Task 3) pins a snapshot on
        # this class-level cursor from BEFORE either worker wrote anything.
        # Nothing after that point touches `self.cr` again on this path, so
        # without this commit `tearDownClass`'s cleanup would be the first
        # statement on that stale snapshot -- and its DELETE of the row the
        # winning worker updated would itself read as a concurrent update and
        # fail with the very SerializationFailure this test proves the
        # application code no longer leaks to a caller.
        self.env.cr.commit()

    def test_requeue_clears_the_dispatcher_lease(self):
        outbox = self._dead_outbox_row(lease_owner="held-by-a-dispatcher")
        supervisor = self._active_supervisor()

        self.env["picking.assistant.outbox"].with_user(
            self.api_user_id
        ).api_requeue_dead(outbox.event_id, supervisor.id, "reason")
        self.env.cr.commit()

        outbox.invalidate_recordset()
        self.assertEqual(outbox.state, "pending")
        self.assertFalse(outbox.lease_owner)
        self.assertFalse(outbox.lease_expires_at)

    def test_archived_supervisor_is_refused(self):
        outbox = self._dead_outbox_row()
        supervisor = self._active_supervisor()
        supervisor.sudo().write({"active": False})
        self.env.cr.commit()

        with self.assertRaises(AccessError):
            self.env["picking.assistant.outbox"].with_user(
                self.api_user_id
            ).api_requeue_dead(outbox.event_id, supervisor.id, "reason")
        # A raised AccessError leaves this shared, class-level cursor mid
        # statement (nothing written, but nothing closed either). The next
        # test method reuses the SAME cursor -- an uncommitted read left open
        # here would pin its REPEATABLE READ snapshot behind this point, and
        # the outbox row the concurrency test locks later would then look
        # "concurrently updated" relative to a snapshot that is older than it
        # has any reason to be.
        self.env.cr.commit()

    def test_share_user_with_the_group_is_refused(self):
        outbox = self._dead_outbox_row()
        supervisor = self._active_supervisor()
        supervisor.sudo().write({"share": True})
        self.env.cr.commit()

        with self.assertRaises(AccessError):
            self.env["picking.assistant.outbox"].with_user(
                self.api_user_id
            ).api_requeue_dead(outbox.event_id, supervisor.id, "reason")
        # See the comment in test_archived_supervisor_is_refused.
        self.env.cr.commit()
