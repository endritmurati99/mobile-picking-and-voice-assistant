import base64
import hashlib
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError

from .common import IntegrationCase

PDF_BYTES = b"%PDF-1.7\n%%EOF\n"
ZPL_BYTES = b"^XA^FO20,20^FDParcel 42^FS^XZ"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"payload"


def encoded(body):
    return base64.b64encode(body).decode()


def digest(body):
    return hashlib.sha256(body).hexdigest()


class ResourceCase(IntegrationCase):
    """Gemeinsames Setup: ein Job mit aktiver Processing-Lease.

    Die Lease ist kein Beiwerk -- `_require_current_generation` verlangt sie,
    weil ein Job ohne laufende Verarbeitung keine Artefakte entgegennehmen
    und keine Medien herausgeben darf.
    """

    def setUp(self):
        super().setUp()
        self.job, self.outbox = self.env[
            "picking.assistant.integration.job"
        ]._enqueue_job_event(
            job_type="shipping_label",
            aggregate_model="res.partner",
            aggregate_res_id=self.picker.partner_id.id,
            aggregate_revision=1,
            event_id="a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
            event_name="shipment.parcel.ready.v1",
            envelope_text='{"schema_version":"v2"}',
            payload_fingerprint="a" * 64,
            correlation_id="0b2f7909-4ad9-44c1-8527-e775fe6d4bec",
            job_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
        )
        self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        ).api_accept_event(
            self.outbox.event_id,
            self.job.job_id,
            "a" * 64,
            "b2n-test",
            "123e4567-e89b-42d3-a456-426614174060",
            1,
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174061",
        )
        self.jobs = self.env["picking.assistant.integration.job"].with_user(
            self.api_user
        )

    def store(self, **overrides):
        values = {
            "job_id": self.job.job_id,
            "source_event_id": self.outbox.event_id,
            "artifact_kind": "pdf",
            "generation": 1,
            "content_base64": encoded(PDF_BYTES),
            "sha256": digest(PDF_BYTES),
            "mimetype": "application/pdf",
            "filename": "label.pdf",
        }
        values.update(overrides)
        return self.jobs.api_store_job_artifact(
            values["job_id"],
            values["source_event_id"],
            values["artifact_kind"],
            values["generation"],
            values["content_base64"],
            values["sha256"],
            values["mimetype"],
            values["filename"],
        )

    def bind_media(self, media_ref="media-1", body=PNG_BYTES, job=None, **kwargs):
        job = job or self.job
        attachment = self.env["ir.attachment"].sudo().create(
            {
                "name": "upload.png",
                "type": "binary",
                "datas": encoded(body),
                "mimetype": "image/png",
                "res_model": job._name,
                "res_id": job.id,
            }
        )
        job.sudo()._bind_job_media(
            attachment,
            media_ref=media_ref,
            sha256=digest(body),
            **kwargs,
        )
        return attachment


class TestArtifactStorage(ResourceCase):
    def test_store_artifact_binds_job_event_and_kind(self):
        result = self.store()
        self.assertFalse(result["replayed"])
        attachment = self.env["ir.attachment"].sudo().search(
            [("pwr_artifact_ref", "=", result["artifact_ref"])]
        )
        self.assertEqual(len(attachment), 1)
        self.assertEqual(attachment.pwr_job_record_id, self.job)
        self.assertEqual(attachment.pwr_source_event_id, self.outbox.event_id)
        self.assertEqual(attachment.pwr_artifact_kind, "pdf")
        self.assertEqual(attachment.pwr_sha256, digest(PDF_BYTES))
        self.assertEqual(base64.b64decode(attachment.datas), PDF_BYTES)

    def test_identical_replay_returns_the_same_reference_without_a_second_row(self):
        first = self.store()
        second = self.store()
        self.assertEqual(second["artifact_ref"], first["artifact_ref"])
        self.assertTrue(second["replayed"])
        self.assertEqual(
            self.env["ir.attachment"].sudo().search_count(
                [("pwr_job_record_id", "=", self.job.id)]
            ),
            1,
        )

    def test_replay_with_different_bytes_is_a_conflict(self):
        self.store()
        other = b"%PDF-1.7\n% different\n%%EOF\n"
        with self.assertRaises(ValidationError):
            self.store(content_base64=encoded(other), sha256=digest(other))
        self.assertEqual(
            self.env["ir.attachment"].sudo().search_count(
                [("pwr_job_record_id", "=", self.job.id)]
            ),
            1,
        )

    def test_hash_mismatch_stores_nothing(self):
        with self.assertRaises(ValidationError):
            self.store(sha256="f" * 64)
        self.assertFalse(
            self.env["ir.attachment"].sudo().search_count(
                [("pwr_job_record_id", "=", self.job.id)]
            )
        )

    def test_stale_generation_cannot_attach(self):
        """Der Watchdog erhoeht die Generation. Ein Worker, der noch mit der
        alten Generation unterwegs ist, darf nichts mehr anhaengen."""
        self.job.sudo().write({"delivery_generation": 2})
        with self.assertRaises(ValidationError):
            self.store(generation=1)
        self.assertFalse(
            self.env["ir.attachment"].sudo().search_count(
                [("pwr_job_record_id", "=", self.job.id)]
            )
        )

    def test_unknown_job_and_foreign_source_event_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.store(job_id="00000000-0000-4000-8000-000000000099")
        with self.assertRaises(ValidationError):
            self.store(source_event_id="00000000-0000-4000-8000-000000000098")
        self.assertFalse(self.env["ir.attachment"].sudo().search_count(
            [("pwr_artifact_ref", "!=", False)]
        ))

    def test_artifact_kind_and_mimetype_are_allowlisted(self):
        for overrides in (
            {"artifact_kind": "png"},
            {"artifact_kind": "PDF"},
            {"artifact_kind": ""},
            {"mimetype": "application/zpl"},
            {"mimetype": "text/html"},
        ):
            with self.assertRaises(ValidationError):
                self.store(**overrides)
        self.assertFalse(self.env["ir.attachment"].sudo().search_count(
            [("pwr_artifact_ref", "!=", False)]
        ))

    def test_zpl_artifact_is_stored_under_its_own_kind(self):
        self.store(
            artifact_kind="zpl",
            content_base64=encoded(ZPL_BYTES),
            sha256=digest(ZPL_BYTES),
            mimetype="application/zpl",
            filename="label.zpl",
        )
        self.store()
        self.assertEqual(
            self.env["ir.attachment"].sudo().search_count(
                [("pwr_job_record_id", "=", self.job.id)]
            ),
            2,
        )

    def test_malformed_base64_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.store(content_base64="!!!not base64!!!")

    def test_expired_processing_lease_cannot_attach(self):
        receipt = self.env["picking.assistant.event.receipt"].sudo().search(
            [("event_id", "=", self.outbox.event_id)]
        )
        receipt.write(
            {"processing_lease_expires_at": fields.Datetime.now() - timedelta(seconds=1)}
        )
        with self.assertRaises(ValidationError):
            self.store()

    def test_api_service_group_is_required(self):
        with self.assertRaises(AccessError):
            self.env["picking.assistant.integration.job"].with_user(
                self.picker
            ).api_store_job_artifact(
                self.job.job_id,
                self.outbox.event_id,
                "pdf",
                1,
                encoded(PDF_BYTES),
                digest(PDF_BYTES),
                "application/pdf",
                "label.pdf",
            )


class TestMediaAccess(ResourceCase):
    def test_media_is_returned_only_for_its_own_job(self):
        self.bind_media()
        payload = self.jobs.api_get_job_media(self.job.job_id, "media-1", 1)
        self.assertEqual(base64.b64decode(payload["content_base64"]), PNG_BYTES)
        self.assertEqual(payload["sha256"], digest(PNG_BYTES))
        self.assertEqual(payload["mimetype"], "image/png")

        other_job, _outbox = self.env[
            "picking.assistant.integration.job"
        ]._enqueue_job_event(
            job_type="quality_assessment",
            aggregate_model="res.partner",
            aggregate_res_id=self.picker.partner_id.id,
            aggregate_revision=1,
            event_id="a4ff5ca2-4546-4ea4-8e6c-b75bc003ca39",
            event_name="quality.assessment.requested.v1",
            envelope_text='{"schema_version":"v2"}',
            payload_fingerprint="a" * 64,
            correlation_id="0b2f7909-4ad9-44c1-8527-e775fe6d4be9",
        )
        # Dieselbe Referenz unter einem anderen Job ist NICHT dieselbe Datei.
        with self.assertRaises(ValidationError):
            self.jobs.api_get_job_media(other_job.job_id, "media-1", 1)

    def test_stale_generation_cannot_read_media(self):
        self.bind_media()
        self.job.sudo().write({"delivery_generation": 2})
        with self.assertRaises(ValidationError):
            self.jobs.api_get_job_media(self.job.job_id, "media-1", 1)

    def test_unknown_media_reference_is_rejected(self):
        self.bind_media()
        with self.assertRaises(ValidationError):
            self.jobs.api_get_job_media(self.job.job_id, "media-9", 1)

    def test_media_reference_is_unique_per_job(self):
        self.bind_media()
        with self.assertRaises(Exception):
            self.bind_media(media_ref="media-1")

    def test_api_service_group_is_required_for_media(self):
        self.bind_media()
        with self.assertRaises(AccessError):
            self.env["picking.assistant.integration.job"].with_user(
                self.picker
            ).api_get_job_media(self.job.job_id, "media-1", 1)

    def test_non_api_user_cannot_bind_an_attachment_to_a_job(self):
        """Die pwr_*-Felder sind die Job-Bindung. Waeren sie fuer jeden
        schreibbar, koennte ein Picker fremde Anhaenge an seinen Job haengen
        und sie ueber die signierte Route auslesen."""
        attachment = self.env["ir.attachment"].with_user(self.picker).create(
            {"name": "own.png", "type": "binary", "datas": encoded(PNG_BYTES)}
        )
        with self.assertRaises(AccessError):
            attachment.write({"pwr_job_record_id": self.job.id, "pwr_media_ref": "x"})


class TestResourceRetentionCron(ResourceCase):
    def _expired(self, job, media_ref):
        attachment = self.bind_media(media_ref=media_ref, job=job)
        attachment.sudo().write(
            {"pwr_retention_until": fields.Datetime.now() - timedelta(days=1)}
        )
        return attachment

    def test_cleanup_removes_expired_but_never_legal_held_resources(self):
        held_job, _outbox = self.env[
            "picking.assistant.integration.job"
        ]._enqueue_job_event(
            job_type="quality_assessment",
            aggregate_model="res.partner",
            aggregate_res_id=self.picker.partner_id.id,
            aggregate_revision=1,
            event_id="a4ff5ca2-4546-4ea4-8e6c-b75bc003ca40",
            event_name="quality.assessment.requested.v1",
            envelope_text='{"schema_version":"v2"}',
            payload_fingerprint="a" * 64,
            correlation_id="0b2f7909-4ad9-44c1-8527-e775fe6d4bf0",
        )
        held_job.write({"legal_hold": True})
        free = self._expired(self.job, "media-free")
        held = self._expired(held_job, "media-held")

        processed = self.env[
            "picking.assistant.integration.job"
        ]._cron_cleanup_job_resources(limit=1000)

        self.assertFalse(free.exists())
        self.assertTrue(held.exists())
        self.assertEqual(processed, 1)

    def test_attachment_without_a_retention_deadline_is_never_selected(self):
        """Die Foundation erfindet keine Frist. Solange kein Add-on eine
        explizite `pwr_retention_until` setzt, bleibt der Anhang ausserhalb
        der Cron-Domain -- auch wenn er beliebig alt ist."""
        undated = self.bind_media(media_ref="media-undated")
        self.assertFalse(undated.pwr_retention_until)
        processed = self.env[
            "picking.assistant.integration.job"
        ]._cron_cleanup_job_resources(limit=1000)
        self.assertTrue(undated.exists())
        self.assertEqual(processed, 0)

    def test_future_deadline_is_not_selected(self):
        attachment = self.bind_media(
            media_ref="media-future",
            retention_until=fields.Datetime.now() + timedelta(days=1),
        )
        self.env["picking.assistant.integration.job"]._cron_cleanup_job_resources(
            limit=1000
        )
        self.assertTrue(attachment.exists())

    def test_cleanup_ignores_attachments_that_belong_to_no_job(self):
        foreign = self.env["ir.attachment"].sudo().create(
            {"name": "unrelated.png", "type": "binary", "datas": encoded(PNG_BYTES)}
        )
        self.env["picking.assistant.integration.job"]._cron_cleanup_job_resources(
            limit=1000
        )
        self.assertTrue(foreign.exists())


class TestGuardedNonceReservation(ResourceCase):
    def test_nonce_reservation_is_bound_to_job_and_generation(self):
        nonces = self.env["picking.assistant.webhook.nonce"].with_user(self.api_user)
        result = nonces.api_reserve_request_nonce(
            "n8n_to_backend",
            "n2b-test",
            "123e4567-e89b-42d3-a456-426614174070",
            False,
            self.job.job_id,
            1,
        )
        self.assertTrue(result["reserved"])
        # Replay derselben Nonce bleibt abgewiesen ...
        with self.assertRaises(ValidationError):
            nonces.api_reserve_request_nonce(
                "n8n_to_backend",
                "n2b-test",
                "123e4567-e89b-42d3-a456-426614174070",
                False,
                self.job.job_id,
                1,
            )
        # ... und eine veraltete Generation kommt gar nicht erst zum Zug.
        with self.assertRaises(ValidationError):
            nonces.api_reserve_request_nonce(
                "n8n_to_backend",
                "n2b-test",
                "123e4567-e89b-42d3-a456-426614174071",
                False,
                self.job.job_id,
                99,
            )
        with self.assertRaises(ValidationError):
            nonces.api_reserve_request_nonce(
                "n8n_to_backend",
                "n2b-test",
                "123e4567-e89b-42d3-a456-426614174072",
                False,
                "00000000-0000-4000-8000-000000000099",
                1,
            )

    def test_reservation_without_a_job_keeps_the_task_8_behaviour(self):
        """Task 8/10 rufen ohne Job-Bindung auf; diese Aufrufe duerfen sich
        nicht aendern, sonst braeche die Acceptance-Route."""
        nonces = self.env["picking.assistant.webhook.nonce"].with_user(self.api_user)
        result = nonces.api_reserve_request_nonce(
            "n8n_to_backend", "n2b-test", "123e4567-e89b-42d3-a456-426614174073"
        )
        self.assertTrue(result["reserved"])
