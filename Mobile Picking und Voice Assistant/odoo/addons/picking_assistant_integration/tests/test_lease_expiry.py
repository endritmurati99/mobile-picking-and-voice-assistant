"""An expired lease must be worthless everywhere, not only at acceptance.

Regression cover for whole-branch review finding #5.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .concurrency_common import CommittedConcurrencyCase


@tagged("post_install", "-at_install")
class TestLeaseExpiry(CommittedConcurrencyCase):
    def _job_with_expired_lease(self):
        """Commit a job whose receipt holds a lease that expired one second ago."""
        env = self.env
        job = self.track(
            env["picking.assistant.integration.job"].create(self._job_values())
        )
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
        job.write(
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
            self._apply_callback(callback)

        self.assertIn("lease", str(caught.exception).lower())

    def test_callback_with_a_live_lease_still_succeeds(self):
        job, receipt = self._job_with_expired_lease()
        receipt.write(
            {"processing_lease_expires_at": fields.Datetime.now() + timedelta(minutes=5)}
        )
        self.env.cr.commit()
        callback = self._callback_payload(job, receipt, token="stale-token")

        result = self._apply_callback(callback)

        self.assertTrue(result["callback_id"])
        self.assertEqual(result["status"], "applied")

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
