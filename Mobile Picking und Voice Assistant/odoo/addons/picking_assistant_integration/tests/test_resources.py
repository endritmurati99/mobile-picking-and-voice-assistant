import base64
import hashlib
import inspect
from datetime import timedelta

import psycopg2

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
        result = self.env["picking.assistant.event.receipt"].with_user(
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
        # Das Token, das DIESER Job/DIESES Event von der Lease-Vergabe erhalten
        # hat -- ab Task 8 der einzige Weg, Medien zu lesen oder Artefakte
        # anzuhaengen (#5b).
        self.token = result["processing_lease_token"]
        self.tokens = {self.job.id: self.token}
        self.jobs = self.env["picking.assistant.integration.job"].with_user(
            self.api_user
        )

    def lease(self, job, outbox, suffix):
        """Gibt einem weiteren Job eine laufende Processing-Lease und merkt
        sich ihr Token unter `self.tokens[job.id]`.

        Noetig, seit `_bind_job_media` Generation UND Lease prueft: ein Job
        ohne laufende Verarbeitung nimmt zu Recht keine Medien mehr an.
        """
        result = self.env["picking.assistant.event.receipt"].with_user(
            self.api_user
        ).api_accept_event(
            outbox.event_id,
            job.job_id,
            "a" * 64,
            "b2n-test",
            f"123e4567-e89b-42d3-a456-4266141740{suffix}",
            job.delivery_generation,
            "n2b-test",
            f"123e4567-e89b-42d3-a456-4266141741{suffix}",
        )
        self.tokens[job.id] = result["processing_lease_token"]
        return job

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
            "processing_lease_token": self.token,
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
            values["processing_lease_token"],
        )

    def bind_media(self, media_ref="media-1", body=PNG_BYTES, job=None,
                   generation=1, supplied_token=None, **kwargs):
        job = job or self.job
        if supplied_token is None:
            supplied_token = self.tokens.get(job.id, self.token)
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
            generation=generation,
            media_ref=media_ref,
            supplied_token=supplied_token,
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

    def test_artifact_binds_to_its_own_event_not_to_any_live_lease(self):
        """Fix-Runde 1, Befund 2: die zweite Haelfte von Review-Befund #5,
        soweit sie ohne Vertragsaenderung schliessbar ist.

        Das Gate suchte sich mit `ORDER BY id LIMIT 1` IRGENDEINE laufende
        Lease des Jobs. Job J hat Receipts fuer Event A und B; Worker W1 haelt
        eine abgelaufene Lease auf A, Worker W2 eine laufende auf B. W1 rief
        `api_store_job_artifact(source_event_id=A)` -- das Gate fand B und
        liess ihn durch. `api_store_job_artifact` bekommt `source_event_id`
        aber bereits mitgeliefert, also wird die Lease jetzt an genau DIESES
        Event gebunden.
        """
        now = fields.Datetime.now()
        own_receipt = self.env["picking.assistant.event.receipt"].sudo().search(
            [("event_id", "=", self.outbox.event_id)]
        )
        own_receipt.write(
            {"processing_lease_expires_at": now - timedelta(seconds=1)}
        )
        # Fremdes, aber lebendes Receipt am selben Job.
        self.env["picking.assistant.event.receipt"].sudo().create(
            {
                "event_id": "6f1c0f0e-6a3c-4f2a-9d2b-2f4a4a6f0b11",
                "job_record_id": self.job.id,
                "payload_fingerprint": "a" * 64,
                "delivery_generation": self.job.delivery_generation,
                "state": "processing",
                "processing_lease_token": "someone-elses-live-token",
                "processing_lease_expires_at": now + timedelta(minutes=5),
            }
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
                self.token,
            )


class TestMediaAccess(ResourceCase):
    def test_media_is_returned_only_for_its_own_job(self):
        self.bind_media()
        payload = self.jobs.api_get_job_media(self.job.job_id, "media-1", 1, self.token)
        self.assertEqual(base64.b64decode(payload["content_base64"]), PNG_BYTES)
        self.assertEqual(payload["sha256"], digest(PNG_BYTES))
        self.assertEqual(payload["mimetype"], "image/png")

        other_job, other_outbox = self.env[
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
        # M2: `other_job` used to be handed straight to `api_get_job_media`
        # with no event receipt at all, so `_locate_active_receipt` refused it
        # with LEASE_REFUSED_MESSAGE and the attachment search this test is
        # NAMED for was never reached -- deleting the `pwr_job_record_id`
        # clause from that search left the test green. Give `other_job` a live
        # lease and its own token so the call gets all the way to the search,
        # and pin the refusal to the search's own message.
        self.lease(other_job, other_outbox, "80")
        # Dieselbe Referenz unter einem anderen Job ist NICHT dieselbe Datei.
        with self.assertRaisesRegex(ValidationError, "Media not found"):
            self.jobs.api_get_job_media(
                other_job.job_id,
                "media-1",
                other_job.delivery_generation,
                self.tokens[other_job.id],
            )

    def test_stale_generation_cannot_read_media(self):
        self.bind_media()
        self.job.sudo().write({"delivery_generation": 2})
        with self.assertRaises(ValidationError):
            self.jobs.api_get_job_media(self.job.job_id, "media-1", 1, self.token)

    def test_expired_processing_lease_cannot_read_media(self):
        """Fix-Runde 1, Befund 3: die Ressourcenroute laeuft seit dieser Task
        durch `_assert_active_lease`. Ohne diesen Test waere der Umbau des
        Gates von KEINEM Test durch den echten RPC-Eingang beruehrt."""
        self.bind_media()
        receipt = self.env["picking.assistant.event.receipt"].sudo().search(
            [("event_id", "=", self.outbox.event_id)]
        )
        receipt.write(
            {"processing_lease_expires_at": fields.Datetime.now() - timedelta(seconds=1)}
        )
        with self.assertRaises(ValidationError):
            self.jobs.api_get_job_media(self.job.job_id, "media-1", 1, self.token)

    def test_unknown_media_reference_is_rejected(self):
        self.bind_media()
        with self.assertRaises(ValidationError):
            self.jobs.api_get_job_media(self.job.job_id, "media-9", 1, self.token)

    def test_media_reference_is_unique_per_job(self):
        """M3: `assertRaises(Exception)` admitted the lease gate, a hash
        mismatch, an `AttributeError` from a rename and even `AssertionError`
        -- i.e. it could not tell the uniqueness constraint from the test
        breaking. Pin it to the constraint that actually enforces the
        invariant."""
        self.bind_media()
        with self.assertRaises(psycopg2.errors.UniqueViolation) as caught:
            self.bind_media(media_ref="media-1")
        self.assertIn("ir_attachment_job_media_unique", str(caught.exception))

    def test_api_service_group_is_required_for_media(self):
        self.bind_media()
        with self.assertRaises(AccessError):
            self.env["picking.assistant.integration.job"].with_user(
                self.picker
            ).api_get_job_media(self.job.job_id, "media-1", 1, self.token)

    def test_non_api_user_cannot_bind_an_attachment_to_a_job(self):
        """Die pwr_*-Felder sind die Job-Bindung. Waeren sie fuer jeden
        schreibbar, koennte ein Picker fremde Anhaenge an seinen Job haengen
        und sie ueber die signierte Route auslesen.

        Seit FIX 1 ist die Regel schaerfer als "nur die API-Gruppe darf": ueber
        `write` darf es NIEMAND, deshalb ValidationError statt AccessError."""
        attachment = self.env["ir.attachment"].with_user(self.picker).create(
            {"name": "own.png", "type": "binary", "datas": encoded(PNG_BYTES)}
        )
        with self.assertRaises(ValidationError):
            attachment.write({"pwr_job_record_id": self.job.id, "pwr_media_ref": "x"})


class TestCallerOwnLeaseToken(ResourceCase):
    """Task 8: #5b. Vor diesem Fix pruefte jeder Ressourcenzugriff nur
    "Generation passt und IRGENDEINE Lease auf diesem Job/Event laeuft"
    (`require_token=False`). Das ist eine schwaechere Aussage als "DU bist
    ihr Inhaber": ein Angreifer, der ein Token aus einer FRUEHEREN, laengst
    abgeloesten Lease-Vergabe desselben Events kennt (Replay, Log-Leck,
    kompromittierter n8n-Knoten), waere durchgekommen, solange irgendeine
    Lease gerade laeuft. Jeder Test hier haelt eine ECHTE, laufende Lease und
    liefert trotzdem ein FALSCHES Token -- genau der Fall, den
    `require_token=False` durchliess.
    """

    def test_media_access_refuses_a_wrong_token_under_a_live_lease(self):
        self.bind_media()
        with self.assertRaises(ValidationError):
            self.jobs.api_get_job_media(
                self.job.job_id, "media-1", 1, "not-the-held-token"
            )

    def test_artifact_access_refuses_a_wrong_token_under_a_live_lease(self):
        with self.assertRaises(ValidationError):
            self.store(processing_lease_token="not-the-held-token")
        self.assertFalse(
            self.env["ir.attachment"].sudo().search_count(
                [("pwr_job_record_id", "=", self.job.id)]
            )
        )

    def test_bind_job_media_refuses_a_wrong_token_under_a_live_lease(self):
        with self.assertRaises(ValidationError):
            self.bind_media(supplied_token="not-the-held-token")

    def test_media_access_refuses_a_stale_but_still_active_lease_era_token(self):
        """The exact #5b shape: a token from an EARLIER lease grant on the
        SAME event, replayed while a newer lease on that event is active.
        Under the old `require_token=False` gate this passed -- generation
        matched and *some* lease was active -- even though the caller does
        not hold the CURRENT token."""
        self.bind_media()
        receipt = self.env["picking.assistant.event.receipt"].sudo().search(
            [("event_id", "=", self.outbox.event_id)]
        )
        stale_token = self.token
        receipt.write({"processing_lease_token": "a-newer-lease-token"})
        with self.assertRaises(ValidationError):
            self.jobs.api_get_job_media(self.job.job_id, "media-1", 1, stale_token)

    def test_media_access_refuses_no_token_under_a_live_lease(self):
        self.bind_media()
        with self.assertRaises(ValidationError):
            self.jobs.api_get_job_media(self.job.job_id, "media-1", 1, False)

    def test_media_access_refuses_a_non_string_token_with_the_uniform_message(self):
        """Fix-round-1 review: a JSON-RPC caller can send any type. Before
        the `isinstance(..., str)` guard, `secrets.compare_digest` raised a
        raw `TypeError` for a non-string token instead of the uniform
        `ValidationError(LEASE_REFUSED_MESSAGE)` -- breaking the same-text
        property `_assert_active_lease`'s own docstring promises."""
        self.bind_media()
        with self.assertRaises(ValidationError) as caught:
            self.jobs.api_get_job_media(self.job.job_id, "media-1", 1, 12345)
        self.assertEqual(str(caught.exception.args[0]), "Processing lease mismatch.")

    def test_media_access_with_the_correct_token_still_succeeds(self):
        """Gegenprobe: die neue Pruefung darf den legitimen Aufrufer nicht
        aussperren."""
        self.bind_media()
        payload = self.jobs.api_get_job_media(self.job.job_id, "media-1", 1, self.token)
        self.assertEqual(base64.b64decode(payload["content_base64"]), PNG_BYTES)

    def test_higher_id_lease_holder_still_succeeds_when_a_lower_id_lease_is_also_live(self):
        """Fix-round-1 review, Finding 1: a job can hold more than one live
        receipt at once (the exact scenario `_require_current_generation`'s
        own docstring describes). Selection used to be `ORDER BY id LIMIT 1`,
        so the holder of the receipt with the HIGHER id was refused whenever
        a receipt with a LOWER id also happened to be live -- even though
        that holder supplied its own, genuinely correct token. This is the
        availability regression the fix-round introduced and then closed by
        selecting the receipt BY the supplied token instead of by id.
        """
        self.bind_media()
        now = fields.Datetime.now()
        # A second, independent live receipt on the SAME job. Created after
        # setUp's receipt, so its id is guaranteed higher.
        second_receipt = self.env["picking.assistant.event.receipt"].sudo().create(
            {
                "event_id": "6f1c0f0e-6a3c-4f2a-9d2b-2f4a4a6f0b99",
                "job_record_id": self.job.id,
                "payload_fingerprint": "a" * 64,
                "delivery_generation": self.job.delivery_generation,
                "state": "processing",
                "processing_lease_token": "higher-id-holders-own-token",
                "processing_lease_expires_at": now + timedelta(minutes=5),
            }
        )
        first_receipt = self.env["picking.assistant.event.receipt"].sudo().search(
            [("event_id", "=", self.outbox.event_id)]
        )
        self.assertGreater(
            second_receipt.id, first_receipt.id, "sanity: fixture assumption"
        )
        # The lower-id receipt (self.token, from setUp) is STILL live too --
        # this is the two-live-leases scenario, not a replacement.
        # The higher-id holder presents its OWN token and must succeed.
        payload = self.jobs.api_get_job_media(
            self.job.job_id, "media-1", 1, "higher-id-holders-own-token"
        )
        self.assertEqual(base64.b64decode(payload["content_base64"]), PNG_BYTES)
        # And the lower-id holder's token must still work too -- neither
        # holder should be able to lock the other out.
        payload = self.jobs.api_get_job_media(self.job.job_id, "media-1", 1, self.token)
        self.assertEqual(base64.b64decode(payload["content_base64"]), PNG_BYTES)

    def test_require_token_opt_out_no_longer_exists(self):
        """`require_token` was the ONE named, greppable opt-out on
        `_assert_active_lease`. Task 8 deletes it outright rather than
        leaving it unused -- a named opt-out on a security primitive is
        exactly what the next hurried caller reaches for.

        Checked on all three lease functions, not just `_assert_active_lease`:
        fix-round-1 review noted a `require_token` added to `_check_lease_state`
        (the shared core both other two call) would currently slip past a
        guard that only looked at `_assert_active_lease`."""
        receipts = self.env["picking.assistant.event.receipt"]
        for name in (
            "_check_lease_state",
            "_assert_lease_state_is_active",
            "_assert_active_lease",
        ):
            signature = inspect.signature(getattr(receipts, name))
            self.assertNotIn(
                "require_token",
                signature.parameters,
                f"{name} grew back a require_token parameter",
            )

    def test_no_call_site_passes_require_token_as_a_keyword(self):
        """Static guard against the opt-out reappearing as a call-site
        keyword argument. Parses the AST rather than grepping the source so
        that the historical explanation of the removed parameter (which
        legitimately still names it in prose/docstrings) cannot trip a naive
        text search."""
        import ast

        from odoo.addons.picking_assistant_integration.models import receipts, resources

        for module in (receipts, resources):
            tree = ast.parse(inspect.getsource(module))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    keyword_names = {kw.arg for kw in node.keywords if kw.arg}
                    self.assertNotIn(
                        "require_token",
                        keyword_names,
                        f"{module.__name__} still passes require_token=... somewhere",
                    )


class TestResourceRetentionCron(ResourceCase):
    def _expired(self, job, media_ref):
        return self.bind_media(
            media_ref=media_ref,
            job=job,
            retention_until=fields.Datetime.now() - timedelta(days=1),
        )

    def test_cleanup_removes_expired_but_never_legal_held_resources(self):
        held_job, held_outbox = self.env[
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
        self.lease(held_job, held_outbox, "80")
        free = self._expired(self.job, "media-free")
        held = self._expired(held_job, "media-held")
        held_job.write({"legal_hold": True})

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
            self.token,
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
                self.token,
            )
        # ... und eine veraltete Generation wird abgelehnt.
        #
        # Seit Task 3 laeuft die Reservierung VOR der Generationspruefung
        # (LOCK_ORDER beginnt mit "nonce"). Der Schutz ist damit nicht die
        # Reihenfolge, sondern die Transaktionsgrenze: der Fehlschlag rollt die
        # Reservierung mit zurueck. `assertRaises` legt dafuer denselben
        # Savepoint um den Block, den der RPC-Dispatcher um den Request legt --
        # die Nonce darf danach nicht existieren, und genau das wird geprueft.
        for stale_nonce, job_id, generation in (
            ("123e4567-e89b-42d3-a456-426614174071", self.job.job_id, 99),
            (
                "123e4567-e89b-42d3-a456-426614174072",
                "00000000-0000-4000-8000-000000000099",
                1,
            ),
        ):
            with self.assertRaises(ValidationError):
                nonces.api_reserve_request_nonce(
                    "n8n_to_backend", "n2b-test", stale_nonce, False, job_id,
                    generation, self.token,
                )
            self.assertFalse(
                self.env["picking.assistant.webhook.nonce"]
                .sudo()
                .search_count([("nonce", "=", stale_nonce)]),
                "a rejected reservation left its nonce behind",
            )

    def test_nonce_reservation_refuses_the_wrong_lease_token(self):
        """Fix-round-1, Finding 3: closing the wire means the nonce
        reservation is now the AUTHORITATIVE ownership check too, not a
        weaker "some lease is active" pre-check."""
        nonces = self.env["picking.assistant.webhook.nonce"].with_user(self.api_user)
        with self.assertRaises(ValidationError):
            nonces.api_reserve_request_nonce(
                "n8n_to_backend",
                "n2b-test",
                "123e4567-e89b-42d3-a456-426614174099",
                False,
                self.job.job_id,
                1,
                "not-the-held-token",
            )
        self.assertFalse(
            self.env["picking.assistant.webhook.nonce"]
            .sudo()
            .search_count([("nonce", "=", "123e4567-e89b-42d3-a456-426614174099")]),
            "a rejected reservation left its nonce behind",
        )

    def test_reservation_without_a_job_keeps_the_task_8_behaviour(self):
        """Task 8/10 rufen ohne Job-Bindung auf; diese Aufrufe duerfen sich
        nicht aendern, sonst braeche die Acceptance-Route."""
        nonces = self.env["picking.assistant.webhook.nonce"].with_user(self.api_user)
        result = nonces.api_reserve_request_nonce(
            "n8n_to_backend", "n2b-test", "123e4567-e89b-42d3-a456-426614174073"
        )
        self.assertTrue(result["reserved"])


class TestReviewRegressions(ResourceCase):
    """Regressionen aus dem Review (Runde 1)."""

    def test_stale_generation_cannot_bind_media(self):
        """CRITICAL 3: `_bind_job_media` nahm gar keine Generation entgegen.
        Ein Worker, der die Generationsrolle verpasst hat, konnte damit einen
        Anhang anlegen und binden -- genau die Invariante, die diese Task
        zusichert."""
        self.job.sudo().write({"delivery_generation": 2})
        with self.assertRaises(ValidationError):
            self.bind_media(media_ref="media-stale", generation=1)
        self.assertFalse(
            self.env["ir.attachment"].sudo().search_count(
                [("pwr_media_ref", "=", "media-stale")]
            )
        )

    def test_current_generation_binds_and_is_persisted(self):
        attachment = self.bind_media(media_ref="media-current", generation=1)
        self.assertEqual(attachment.pwr_binding_generation, 1)
        self.assertEqual(attachment.pwr_job_record_id, self.job)

    def test_binding_without_an_active_lease_is_refused(self):
        receipt = self.env["picking.assistant.event.receipt"].sudo().search(
            [("event_id", "=", self.outbox.event_id)]
        )
        receipt.write(
            {"processing_lease_expires_at": fields.Datetime.now() - timedelta(seconds=1)}
        )
        with self.assertRaises(ValidationError):
            self.bind_media(media_ref="media-noleash", generation=1)

    def test_bind_media_verifies_the_hash_itself(self):
        """Der Aufrufer liefert den Hash, aber er wird nicht geglaubt."""
        job = self.job.sudo()
        attachment = self.env["ir.attachment"].sudo().create(
            {"name": "u.png", "type": "binary", "datas": encoded(PNG_BYTES)}
        )
        with self.assertRaises(ValidationError):
            job._bind_job_media(
                attachment,
                generation=1,
                media_ref="media-liar",
                supplied_token=self.token,
                sha256="f" * 64,
            )

    def test_job_binding_is_immutable_even_under_sudo(self):
        """IMPORTANT 2: der create/write-Hook laesst `env.su` durch, also darf
        die Unveraenderlichkeit nicht an ihm haengen. Einmal gesetzt, bleibt
        die Job-Zuordnung stehen -- auch fuer sudo-faehigen Code."""
        attachment = self.bind_media(media_ref="media-owned")
        other_job, _outbox = self.env[
            "picking.assistant.integration.job"
        ]._enqueue_job_event(
            job_type="quality_assessment",
            aggregate_model="res.partner",
            aggregate_res_id=self.picker.partner_id.id,
            aggregate_revision=1,
            event_id="a4ff5ca2-4546-4ea4-8e6c-b75bc003ca44",
            event_name="quality.assessment.requested.v1",
            envelope_text='{"schema_version":"v2"}',
            payload_fingerprint="a" * 64,
            correlation_id="0b2f7909-4ad9-44c1-8527-e775fe6d4bf4",
        )
        # Ueber den GEPRUEFTEN Schreibweg -- sonst wuerde dieser Test nur die
        # Ingress-Sperre aus FIX 1 wiederholen statt die Unveraenderlichkeit.
        for values in (
            {"pwr_job_record_id": other_job.id},
            {"pwr_media_ref": "media-hijacked"},
            {"pwr_sha256": "f" * 64},
            {"pwr_binding_generation": 99},
        ):
            with self.assertRaises(ValidationError):
                attachment.sudo()._pwr_write_binding(values)
        self.assertEqual(attachment.pwr_job_record_id, self.job)

    def test_rewriting_the_same_binding_value_stays_allowed(self):
        """Gegenprobe: Unveraenderlichkeit darf keine idempotente
        Wiederholung brechen, und die Frist bleibt nachtraeglich setzbar."""
        attachment = self.bind_media(media_ref="media-idem")
        attachment.sudo()._pwr_write_binding({"pwr_media_ref": "media-idem"})
        attachment.sudo()._pwr_write_binding(
            {"pwr_retention_until": fields.Datetime.now() + timedelta(days=30)}
        )
        self.assertTrue(attachment.pwr_retention_until)

    def test_artifact_binding_is_immutable_under_sudo(self):
        result = self.store()
        attachment = self.env["ir.attachment"].sudo().search(
            [("pwr_artifact_ref", "=", result["artifact_ref"])]
        )
        for values in (
            {"pwr_artifact_kind": "zpl"},
            {"pwr_source_event_id": "00000000-0000-4000-8000-000000000098"},
            {"pwr_artifact_ref": "forged"},
        ):
            with self.assertRaises(ValidationError):
                attachment._pwr_write_binding(values)

    def test_odoo_ingress_rejects_content_that_is_not_its_declared_type(self):
        """IMPORTANT 1: ein direkter JSON-RPC-Aufruf umgeht die Tiefenpruefung
        des Backends vollstaendig. Der deklarierte Typ muss deshalb auch hier
        wenigstens WIRKLICH dieser Typ sein."""
        with self.assertRaises(ValidationError):
            self.store(
                content_base64=encoded(ZPL_BYTES), sha256=digest(ZPL_BYTES)
            )
        with self.assertRaises(ValidationError):
            self.store(
                artifact_kind="zpl",
                mimetype="application/zpl",
                content_base64=encoded(PDF_BYTES),
                sha256=digest(PDF_BYTES),
            )
        with self.assertRaises(ValidationError):
            self.store(
                content_base64=encoded(b"\x89PNG\r\n\x1a\nnope"),
                sha256=digest(b"\x89PNG\r\n\x1a\nnope"),
            )
        self.assertFalse(self.env["ir.attachment"].sudo().search_count(
            [("pwr_artifact_ref", "!=", False)]
        ))

    def test_odoo_ingress_rejects_pdf_with_an_appended_payload(self):
        hostile = PDF_BYTES + b"<?php system($_GET[0]); ?>\n%%EOF\n"
        with self.assertRaises(ValidationError):
            self.store(content_base64=encoded(hostile), sha256=digest(hostile))

    def test_odoo_ingress_rejects_zpl_outside_the_command_allowlist(self):
        for hostile in (
            b"^XA^JUS^XZ",
            b"^XA^DFE:FORMAT.ZPL^XZ",
            b"^XA^ju^XZ",
            b"^XA^FDx^FS^XZ^XA^JUS^XZ",
            "^XA^FDPäckchen^FS^XZ".encode("utf-8"),
        ):
            with self.assertRaises(ValidationError):
                self.store(
                    artifact_kind="zpl",
                    mimetype="application/zpl",
                    content_base64=encoded(hostile),
                    sha256=digest(hostile),
                )
        self.assertFalse(self.env["ir.attachment"].sudo().search_count(
            [("pwr_artifact_ref", "!=", False)]
        ))

    def test_odoo_ingress_still_accepts_the_legitimate_types(self):
        """Gegenprobe: die neue Eingangspruefung darf gueltige Artefakte
        nicht mitreissen."""
        self.store()
        self.store(
            artifact_kind="zpl",
            mimetype="application/zpl",
            content_base64=encoded(ZPL_BYTES),
            sha256=digest(ZPL_BYTES),
        )
        self.assertEqual(
            self.env["ir.attachment"].sudo().search_count(
                [("pwr_job_record_id", "=", self.job.id)]
            ),
            2,
        )


class TestOrmIngressBoundary(ResourceCase):
    """Review-Runde 2, FIX 1.

    `ir.attachment.create`/`write` sind OEFFENTLICHE ORM-Einstiegspunkte. Dass
    `_bind_job_media` privat und damit nicht per RPC erreichbar ist, half
    nichts: ein API-Service-Nutzer konnte einfach direkt einen Anhang mit
    gefaelschtem `pwr_job_record_id`, gefaelschter Identitaet, gefaelschter
    Generation und gefaelschtem Hash anlegen -- an jedem Gate vorbei. Die
    Unveraenderlichkeit aus Runde 1 zementierte die Faelschung dann sogar.
    """

    def test_api_service_user_cannot_create_a_binding_through_generic_orm(self):
        with self.assertRaises(ValidationError):
            self.env["ir.attachment"].with_user(self.api_user).create(
                {
                    "name": "forged.pdf",
                    "type": "binary",
                    "datas": encoded(PDF_BYTES),
                    "pwr_job_record_id": self.job.id,
                    "pwr_media_ref": "forged",
                    "pwr_sha256": "f" * 64,
                    "pwr_binding_generation": 1,
                }
            )
        self.assertFalse(
            self.env["ir.attachment"].sudo().search_count(
                [("pwr_media_ref", "=", "forged")]
            )
        )

    def test_api_service_user_cannot_write_a_binding_through_generic_orm(self):
        attachment = self.env["ir.attachment"].with_user(self.api_user).create(
            {"name": "plain.pdf", "type": "binary", "datas": encoded(PDF_BYTES)}
        )
        with self.assertRaises(ValidationError):
            attachment.write({"pwr_job_record_id": self.job.id})
        with self.assertRaises(ValidationError):
            attachment.write({"pwr_retention_until": fields.Datetime.now()})
        self.assertFalse(attachment.pwr_job_record_id)

    def test_sudo_cannot_create_or_write_a_binding_through_generic_orm(self):
        """Auch sudo nicht: die Grenze ist der Einstiegspunkt, nicht das Recht."""
        with self.assertRaises(ValidationError):
            self.env["ir.attachment"].sudo().create(
                {
                    "name": "forged2.pdf",
                    "type": "binary",
                    "datas": encoded(PDF_BYTES),
                    "pwr_job_record_id": self.job.id,
                    "pwr_media_ref": "forged2",
                }
            )
        attachment = self.env["ir.attachment"].sudo().create(
            {"name": "plain2.pdf", "type": "binary", "datas": encoded(PDF_BYTES)}
        )
        with self.assertRaises(ValidationError):
            attachment.write({"pwr_artifact_kind": "pdf"})

    def test_plain_attachments_are_unaffected(self):
        """Gegenprobe: gewoehnliche Anhaenge ohne pwr_*-Felder funktionieren
        unveraendert -- der Hook haengt an einem Kernmodell."""
        attachment = self.env["ir.attachment"].with_user(self.picker).create(
            {"name": "normal.png", "type": "binary", "datas": encoded(PNG_BYTES)}
        )
        attachment.write({"name": "renamed.png"})
        self.assertEqual(attachment.name, "renamed.png")

    def test_the_guarded_methods_still_bind(self):
        """Und der eine erlaubte Weg funktioniert weiterhin."""
        attachment = self.bind_media(media_ref="media-guarded")
        self.assertEqual(attachment.pwr_job_record_id, self.job)
        result = self.store()
        self.assertFalse(result["replayed"])

    def test_retention_is_settable_through_the_guarded_path_only(self):
        attachment = self.bind_media(
            media_ref="media-ret",
            retention_until=fields.Datetime.now() + timedelta(days=30),
        )
        self.assertTrue(attachment.pwr_retention_until)
