"""Job-gebundene Anhaenge: Medien (eingehend) und Artefakte (ausgehend).

Odoo ist hier die Autoritaet, nicht das Backend. Das Backend validiert die
Bytes (siehe `backend/app/services/binary_validation.py`), aber WEM eine
Datei gehoert und OB sie in diesem Moment noch angefasst werden darf,
entscheidet ausschliesslich dieses Modul -- unter Sperre, in derselben
Transaktion wie die Nonce-Reservierung.

Drei Invarianten:

1. Jeder Anhang haengt an genau einem Job (`pwr_job_record_id`). Eine
   Medienreferenz ist nur INNERHALB ihres Jobs eindeutig; dieselbe Referenz
   unter einem anderen Job ist eine andere Datei und darf nicht auffindbar
   sein.
2. Jeder Zugriff prueft die aktuelle Delivery-Generation UND eine laufende
   Processing-Lease. Sobald der Watchdog die Generation erhoeht, ist ein
   noch laufender Worker sofort ausgesperrt -- er kann weder anhaengen noch
   lesen.
3. Die `pwr_*`-Felder SIND die Bindung. Sie sind deshalb nur fuer die
   Integrations-API schreibbar; koennte ein beliebiger Nutzer sie setzen,
   haenge er eine fremde Datei an seinen eigenen Job und liest sie ueber die
   signierte Route aus.

Aufbewahrung: die Foundation erfindet keine Frist. `pwr_retention_until`
bleibt leer, bis ein Feature-Add-on eine EXPLIZITE Frist setzt (Visual
Quality: Alarm-/Review-Abschluss + 30 Tage, Shipping: Versand/Storno + 90
Tage). Ohne gesetzte Frist ist der Anhang nicht in der Cron-Domain, und der
gemeinsame `legal_hold` des Jobs blockiert jede verknuepfte Ressource.
"""
import base64
import binascii
import hashlib
from uuid import uuid4

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Allowlist der Artefaktarten: Art -> erlaubter MIME-Typ. Spiegelt bewusst
# `binary_validation._ARTIFACT_KINDS` im Backend: das Backend prueft den
# Inhalt, diese Schicht prueft unabhaengig davon noch einmal Art und Typ,
# damit ein direkter JSON-RPC-Aufruf am Backend vorbei nichts anderes
# ablegen kann.
ARTIFACT_MIMETYPES = {
    "pdf": "application/pdf",
    "zpl": "application/zpl",
}

# Obergrenze fuer den dekodierten Anhang. Entspricht dem Dokumentenlimit des
# Backends; sie existiert hier trotzdem, weil dieser Aufruf auch ohne das
# Backend erreichbar waere.
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024

# Die Bindungsfelder. Ein Schreibzugriff darauf ist ein Rechteakt, kein
# Datenpflegevorgang.
PWR_BINDING_FIELDS = frozenset(
    {
        "pwr_job_record_id",
        "pwr_media_ref",
        "pwr_artifact_ref",
        "pwr_source_event_id",
        "pwr_artifact_kind",
        "pwr_sha256",
        "pwr_original_filename",
        "pwr_retention_until",
    }
)


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    pwr_job_record_id = fields.Many2one(
        "picking.assistant.integration.job", ondelete="cascade", index=True
    )
    pwr_media_ref = fields.Char(index=True)
    pwr_artifact_ref = fields.Char(index=True)
    pwr_source_event_id = fields.Char(index=True)
    pwr_artifact_kind = fields.Char(index=True)
    pwr_sha256 = fields.Char(index=True)
    pwr_original_filename = fields.Char()
    pwr_retention_until = fields.Datetime(index=True)

    # NULLs kollidieren in Postgres nicht: gewoehnliche Anhaenge ohne
    # pwr_job_record_id bleiben von beiden Constraints unberuehrt.
    _job_media_unique = models.Constraint(
        "UNIQUE(pwr_job_record_id, pwr_media_ref)",
        "Media reference must be unique per job.",
    )
    _job_artifact_unique = models.Constraint(
        "UNIQUE(pwr_job_record_id, pwr_source_event_id, pwr_artifact_kind)",
        "Artifact kind must be unique per job event.",
    )

    def _check_pwr_binding_access(self, values):
        """Nur die Integrations-API darf die Bindung setzen oder aendern.

        `readonly=True` waere hier wertlos -- es ist eine UI-Eigenschaft und
        haelt keinen ORM-Schreibzugriff auf. Diese Pruefung laeuft in create
        UND write; eine der beiden allein waere eine Luecke.
        """
        if self.env.su:
            return
        touched = PWR_BINDING_FIELDS.intersection(values or {})
        if touched:
            self.env["picking.assistant.api.mixin"]._require_api_service()

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            self._check_pwr_binding_access(values)
        return super().create(vals_list)

    def write(self, values):
        self._check_pwr_binding_access(values)
        return super().write(values)


class PickingAssistantIntegrationJobResources(models.Model):
    _inherit = "picking.assistant.integration.job"

    def _require_current_generation(self, generation):
        """Die EINE Gate-Funktion beider Ressourcenzugriffe.

        Sie steht bewusst nicht zweimal ausgeschrieben in `api_get_job_media`
        und `api_store_job_artifact`: genau so entsteht der Fehler, dass eine
        Pruefung in der einen Funktion verschaerft wird und in der anderen
        veraltet.
        """
        self.ensure_one()
        try:
            requested = int(generation)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Delivery generation must be an integer.") from exc
        if self.delivery_generation != requested:
            raise ValidationError("Stale delivery generation.")
        receipt = self.env["picking.assistant.event.receipt"].sudo().search(
            [
                ("job_record_id", "=", self.id),
                ("state", "=", "processing"),
                ("processing_lease_expires_at", ">", fields.Datetime.now()),
            ],
            limit=1,
        )
        if not receipt:
            raise ValidationError("Job has no active processing lease.")
        return receipt

    @api.model
    def _locked_job(self, job_id):
        """Job anhand seiner oeffentlichen job_id sperren und danach neu
        lesen. Gleiche Reihenfolge und gleiches Muster wie in Task 8
        (job -> receipt -> outbox), damit keine Sperrinversion entsteht."""
        jobs = self.sudo()
        jobs.flush_model()
        self.env.cr.execute(
            "SELECT id FROM picking_assistant_integration_job "
            "WHERE job_id = %s FOR UPDATE",
            (job_id,),
        )
        row = self.env.cr.fetchone()
        if not row:
            raise ValidationError("Job not found.")
        job = jobs.browse(row[0])
        job.invalidate_recordset()
        return job

    def _bind_job_media(
        self,
        attachment,
        *,
        media_ref,
        sha256,
        retention_until=False,
        original_filename=False,
    ):
        """Bindet einen bereits erzeugten Anhang als Medium an diesen Job.

        Einstiegspunkt fuer die Feature-Add-ons (Visual Quality legt das
        Bild an, die Foundation besitzt nur die Bindung). Die Frist wird hier
        durchgereicht und nie erfunden.
        """
        self.ensure_one()
        if not media_ref:
            raise ValidationError("Media reference is required.")
        attachment.sudo().write(
            {
                "pwr_job_record_id": self.id,
                "pwr_media_ref": media_ref,
                "pwr_sha256": sha256,
                "pwr_original_filename": original_filename or False,
                "pwr_retention_until": retention_until or False,
            }
        )
        attachment.sudo().flush_recordset()
        return media_ref

    @api.model
    def api_get_job_media(self, job_id, media_ref, generation):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        job = self._locked_job(job_id)
        job._require_current_generation(generation)
        attachment = self.env["ir.attachment"].sudo().search(
            [
                ("pwr_job_record_id", "=", job.id),
                ("pwr_media_ref", "=", media_ref),
            ],
            limit=1,
        )
        if not attachment:
            raise ValidationError("Media not found.")
        content = attachment.datas
        return {
            "content_base64": content.decode() if isinstance(content, bytes) else content,
            "mimetype": attachment.mimetype or "",
            "sha256": attachment.pwr_sha256 or "",
            "original_filename": attachment.pwr_original_filename or "",
        }

    @api.model
    def api_store_job_artifact(
        self,
        job_id,
        source_event_id,
        artifact_kind,
        generation,
        content_base64,
        sha256,
        mimetype,
        filename,
    ):
        self.env["picking.assistant.api.mixin"]._require_api_service()
        # Art und Typ zuerst: beides ist eine Allowlist-Pruefung und kostet
        # nichts, also passiert sie vor jeder Sperre und jedem Dekodieren.
        expected_mimetype = ARTIFACT_MIMETYPES.get(artifact_kind) if isinstance(
            artifact_kind, str
        ) else None
        if expected_mimetype is None:
            raise ValidationError("Artifact kind is not allowed.")
        if mimetype != expected_mimetype:
            raise ValidationError("Artifact mimetype does not match its kind.")
        job = self._locked_job(job_id)
        job._require_current_generation(generation)
        outbox = self.env["picking.assistant.outbox"].sudo().search(
            [
                ("job_record_id", "=", job.id),
                ("event_id", "=", source_event_id),
            ],
            limit=1,
        )
        if not outbox:
            raise ValidationError("Source event not found.")
        try:
            raw = base64.b64decode(content_base64 or "", validate=True)
        except (binascii.Error, TypeError, ValueError) as exc:
            raise ValidationError("Artifact content is not valid base64.") from exc
        if not raw:
            raise ValidationError("Artifact content is empty.")
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise ValidationError("Artifact exceeds the size limit.")
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValidationError("Artifact hash mismatch.")
        existing = self.env["ir.attachment"].sudo().search(
            [
                ("pwr_job_record_id", "=", job.id),
                ("pwr_source_event_id", "=", source_event_id),
                ("pwr_artifact_kind", "=", artifact_kind),
            ],
            limit=1,
        )
        if existing:
            # Gleiche Bytes = Wiedervorlage, andere Bytes unter derselben Art
            # = Konflikt. Nie ein stilles Ueberschreiben.
            if existing.pwr_sha256 != sha256:
                raise ValidationError("Artifact replay has different bytes.")
            return {"artifact_ref": existing.pwr_artifact_ref, "replayed": True}
        artifact_ref = str(uuid4())
        self.env["ir.attachment"].sudo().create(
            {
                "name": filename,
                "type": "binary",
                "datas": content_base64,
                "mimetype": expected_mimetype,
                "res_model": self._name,
                "res_id": job.id,
                "pwr_job_record_id": job.id,
                "pwr_artifact_ref": artifact_ref,
                "pwr_source_event_id": source_event_id,
                "pwr_artifact_kind": artifact_kind,
                "pwr_sha256": sha256,
            }
        )
        return {"artifact_ref": artifact_ref, "replayed": False}

    @api.model
    def _cron_cleanup_job_resources(self, limit=1000):
        """Taeglich: job-gebundene Anhaenge nach ihrer EXPLIZITEN Frist
        loeschen. Ohne gesetzte `pwr_retention_until` ist ein Anhang gar
        nicht in der Domain -- die Foundation loescht nie auf Verdacht."""
        domain = [
            ("pwr_job_record_id", "!=", False),
            ("pwr_retention_until", "!=", False),
            ("pwr_retention_until", "<=", fields.Datetime.now()),
            ("pwr_job_record_id.legal_hold", "=", False),
        ]
        attachments = self.env["ir.attachment"].sudo().search(domain, limit=int(limit))
        processed = len(attachments)
        attachments.unlink()
        remaining = self.env["ir.attachment"].sudo().search_count(domain)
        self._report_cron_progress(processed, remaining=remaining)
        return processed


class PickingAssistantWebhookNonceResources(models.Model):
    _inherit = "picking.assistant.webhook.nonce"

    @api.model
    def api_reserve_request_nonce(
        self,
        direction,
        key_id,
        nonce,
        event_id=False,
        job_id=False,
        delivery_generation=False,
    ):
        """Erweitert die Task-8-Reservierung um eine OPTIONALE Job- und
        Generationsbindung.

        Optional, weil die Acceptance-/Callback-Routen (Task 8/10) ohne Job
        aufrufen und sich nicht aendern duerfen. Sobald ein `job_id`
        mitkommt -- so rufen die Ressourcenrouten auf -- werden Job und
        aktuelle Generation VOR der Reservierung geprueft, damit eine
        veraltete Generation nicht einmal eine Nonce verbrennen kann.

        Bewusst NICHT uebernommen: ein vom Aufrufer geliefertes `expires_at`.
        Die Retention gehoert dem Store (900s > die geforderten 600s); ein
        Aufrufer, der sie setzen darf, koennte den Replay-Schutz auf null
        stellen.
        """
        self.env["picking.assistant.api.mixin"]._require_api_service()
        if job_id:
            job = self.env["picking.assistant.integration.job"]._locked_job(job_id)
            job._require_current_generation(delivery_generation)
        return super().api_reserve_request_nonce(
            direction, key_id, nonce, event_id=event_id
        )
