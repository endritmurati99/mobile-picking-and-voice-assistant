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

VERTRAUENSGRENZE (wichtig, im Review ausdruecklich verlangt): die TIEFE
Formatpruefung lebt am Backend-Rand, in
`backend/app/services/binary_validation.py` -- dort steht die vollstaendige
PDF-Objektgraph-Allowlist, das Expansionsbudget gegen Dekompressionsbomben
und die Pillow-gestuetzte Bildpruefung. Jeder Aufrufer, der Odoo DIREKT per
JSON-RPC erreicht, liegt ausserhalb dieser Zusicherung. Deshalb -- und nur
deshalb -- revalidiert dieses Modul zusaetzlich am Eingang: ein deklarierter
Typ muss wenigstens WIRKLICH dieser Typ sein (Magic, Revisionsdisziplin,
und fuer ZPL die vollstaendige Kommando-Allowlist, die ohne Fremdbibliothek
auskommt). Das ist bewusst WENIGER als die Backend-Pruefung: `pypdf` ist im
Odoo-Image nicht installiert (nur das unwartete PyPDF2 2.12.1, das ich
feindlichen Eingaben nicht vorsetze), und eine zweite, abweichende
Tiefenpruefung waere ohnehin eine Quelle fuer Drift. Wer die harte Garantie
will, muss ueber die signierte Backend-Route kommen.

Aufbewahrung: die Foundation erfindet keine Frist. `pwr_retention_until`
bleibt leer, bis ein Feature-Add-on eine EXPLIZITE Frist setzt (Visual
Quality: Alarm-/Review-Abschluss + 30 Tage, Shipping: Versand/Storno + 90
Tage). Ohne gesetzte Frist ist der Anhang nicht in der Cron-Domain, und der
gemeinsame `legal_hold` des Jobs blockiert jede verknuepfte Ressource.
"""
import base64
import binascii
import hashlib
import re
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
        "pwr_binding_generation",
    }
)

# Die Teilmenge, die die IDENTITAET der Bindung ausmacht. Sie ist nach dem
# ersten Setzen unveraenderlich -- auch fuer sudo-faehigen Code.
# Nicht enthalten: pwr_retention_until und pwr_original_filename, die ein
# Feature-Add-on spaeter noch setzen koennen muss.
PWR_IMMUTABLE_FIELDS = frozenset(
    {
        "pwr_job_record_id",
        "pwr_media_ref",
        "pwr_artifact_ref",
        "pwr_source_event_id",
        "pwr_artifact_kind",
        "pwr_sha256",
        "pwr_binding_generation",
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
    # Die Generation, unter der die Bindung entstanden ist. Sie macht im
    # Nachhinein nachvollziehbar, welcher Zustellversuch die Datei gebracht
    # hat, und ist -- wie die uebrige Bindung -- unveraenderlich.
    pwr_binding_generation = fields.Integer()

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

    def _check_pwr_binding_immutable(self, values):
        """Einmal gesetzt, bleibt die Bindung stehen -- UNABHAENGIG von sudo.

        `_check_pwr_binding_access` ist eine Rechtepruefung und wird von
        `env.su` bewusst uebersprungen; genau deshalb darf die Zuordnung
        nicht an ihr haengen. Diese Pruefung hier laeuft immer, hat keine
        Kontext-Hintertuer und macht aus "wer darf schreiben" ein
        "was ist ueberhaupt aenderbar". Idempotentes Neuschreiben desselben
        Wertes bleibt erlaubt, `pwr_retention_until` und
        `pwr_original_filename` bleiben nachtraeglich setzbar (die Frist
        kommt erst vom Feature-Add-on).
        """
        touched = PWR_IMMUTABLE_FIELDS.intersection(values or {})
        if not touched:
            return
        for record in self:
            for name in sorted(touched):
                current = record[name]
                if name == "pwr_job_record_id":
                    current = current.id
                requested = values[name]
                if current and current != requested:
                    raise ValidationError(
                        "Job binding fields cannot be changed once set."
                    )

    def _reject_binding_through_generic_orm(self, values):
        """Die Bindungsfelder sind ueber `create`/`write` UEBERHAUPT NICHT
        schreibbar -- fuer niemanden, auch nicht fuer sudo oder die
        API-Service-Gruppe.

        Die vorige Fassung fragte hier nach der Gruppe und liess die
        Integrations-API durch. Das war die Luecke: `ir.attachment.create` und
        `write` sind OEFFENTLICHE ORM-Einstiegspunkte, ein API-Nutzer konnte
        also per JSON-RPC direkt einen Anhang mit gefaelschter Job-Zuordnung,
        gefaelschter Generation und gefaelschtem Hash anlegen und umging damit
        jedes Gate. Dass `_bind_job_media` privat ist, half nicht -- der
        Angriff ging nie durch `_bind_job_media`.

        Die Grenze ist jetzt der EINSTIEGSPUNKT statt des Rechts: gesetzt
        werden die Felder ausschliesslich in `_pwr_write_binding`, das
        unterstrichen und damit per RPC unaufrufbar ist und nur aus den
        gepruefte Methoden heraus benutzt wird.
        """
        touched = PWR_BINDING_FIELDS.intersection(values or {})
        if touched:
            raise ValidationError(
                "Job binding fields can only be set through the guarded "
                "media and artifact methods."
            )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            self._reject_binding_through_generic_orm(values)
        return super().create(vals_list)

    def write(self, values):
        self._reject_binding_through_generic_orm(values)
        return super().write(values)

    def _pwr_write_binding(self, values):
        """Der EINZIGE Weg, Bindungsfelder zu schreiben.

        Umgeht bewusst `IrAttachment.write` (und damit die Sperre oben),
        erzwingt aber weiterhin die Unveraenderlichkeit. Unterstrichen, also
        per JSON-RPC nicht aufrufbar; alle Aufrufer sind die bereits
        generations- und lease-gepruefte `_bind_job_media` sowie
        `api_store_job_artifact`.
        """
        self._check_pwr_binding_immutable(values)
        return super(IrAttachment, self).write(values)


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
        # Zweite Sperre in der globalen Reihenfolge job -> receipt -> outbox
        # (Task 8 und Task 9 mussten fuer genau diese Nachlaessigkeit
        # korrigiert werden). Ein ungesperrtes `search` haette die Lease
        # gelesen, waehrend der Watchdog sie nebenan freigibt.
        receipts = self.env["picking.assistant.event.receipt"].sudo()
        receipts.flush_model()
        now = fields.Datetime.now()
        self.env.cr.execute(
            "SELECT id FROM picking_assistant_event_receipt "
            "WHERE job_record_id = %s AND state = 'processing' "
            "AND processing_lease_expires_at > %s "
            "ORDER BY id LIMIT 1 FOR UPDATE",
            (self.id, now),
        )
        row = self.env.cr.fetchone()
        if not row:
            raise ValidationError("Job has no active processing lease.")
        receipt = receipts.browse(row[0])
        receipt.invalidate_recordset()
        # Unter der Sperre neu lesen statt dem Vorher-Zustand zu glauben --
        # und zwar durch DIE Lease-Primitive, nicht durch eine hier
        # nachgebaute zweite Meinung. `require_token=False`, weil dieser
        # RPC-Vertrag kein Lease-Token entgegennimmt (zweite Haelfte von
        # Review-Befund #5, siehe `_assert_active_lease`).
        receipts._assert_active_lease(
            self,
            receipt,
            generation=requested,
            supplied_token=False,
            now=now,
            require_token=False,
        )
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
        generation,
        media_ref,
        sha256=False,
        retention_until=False,
        original_filename=False,
    ):
        """Bindet einen bereits erzeugten Anhang als Medium an diesen Job.

        Einstiegspunkt fuer die Feature-Add-ons (Visual Quality legt das
        Bild an, die Foundation besitzt nur die Bindung). Die Frist wird hier
        durchgereicht und nie erfunden.

        `generation` ist PFLICHT. Die erste Fassung nahm keine entgegen und
        war damit das Loch in der zentralen Zusage dieser Task: ein Worker,
        der eine Generationsrolle verpasst hatte, konnte einen Anhang anlegen
        und binden, obwohl `api_get_job_media` und `api_store_job_artifact`
        ihn laengst aussperrten. Der Job wird deshalb hier gesperrt und unter
        der Sperre gegen Generation UND laufende Lease revalidiert -- dieselbe
        Gate-Funktion, die die beiden API-Methoden benutzen.

        Der Hash wird selbst berechnet und ein mitgelieferter nur noch
        gegengeprueft: der Aufrufer bestimmt den Inhalt, aber nicht, wofuer
        er sich ausgibt.
        """
        self.ensure_one()
        if not media_ref:
            raise ValidationError("Media reference is required.")
        attachment.ensure_one()
        job = self._locked_job(self.job_id)
        job._require_current_generation(generation)
        raw = base64.b64decode(attachment.sudo().datas or b"", validate=False)
        computed = hashlib.sha256(raw).hexdigest()
        if sha256 and sha256 != computed:
            raise ValidationError("Media hash mismatch.")
        attachment.sudo()._pwr_write_binding(
            {
                "pwr_job_record_id": job.id,
                "pwr_media_ref": media_ref,
                "pwr_sha256": computed,
                "pwr_binding_generation": int(generation),
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
        # Dritte Sperre in der globalen Reihenfolge job -> receipt -> outbox.
        outboxes = self.env["picking.assistant.outbox"].sudo()
        outboxes.flush_model()
        self.env.cr.execute(
            "SELECT id FROM picking_assistant_outbox "
            "WHERE job_record_id = %s AND event_id = %s FOR UPDATE",
            (job.id, source_event_id),
        )
        row = self.env.cr.fetchone()
        if not row:
            raise ValidationError("Source event not found.")
        outbox = outboxes.browse(row[0])
        outbox.invalidate_recordset()
        if outbox.job_record_id.id != job.id or outbox.event_id != source_event_id:
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
        # Siehe Vertrauensgrenze im Modul-Docstring: der Backend-Rand macht
        # die Tiefenpruefung, dieser Eingang stellt nur sicher, dass der
        # deklarierte Typ ueberhaupt dieser Typ IST.
        _revalidate_artifact_bytes(artifact_kind, raw)
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
        # Anlegen und Binden sind zwei Schritte, weil `create` die
        # Bindungsfelder nicht mehr annimmt (siehe
        # `_reject_binding_through_generic_orm`). Beide liegen in derselben
        # Transaktion, ein Anhang ohne Bindung kann also nicht zurueckbleiben.
        attachment = self.env["ir.attachment"].sudo().create(
            {
                "name": filename,
                "type": "binary",
                "datas": content_base64,
                "mimetype": expected_mimetype,
                "res_model": self._name,
                "res_id": job.id,
            }
        )
        attachment._pwr_write_binding(
            {
                "pwr_job_record_id": job.id,
                "pwr_artifact_ref": artifact_ref,
                "pwr_source_event_id": source_event_id,
                "pwr_artifact_kind": artifact_kind,
                "pwr_sha256": sha256,
                "pwr_binding_generation": int(generation),
            }
        )
        attachment.flush_recordset()
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


# ---------------------------------------------------------------------------
# Eingangs-Revalidierung (siehe Vertrauensgrenze im Modul-Docstring)
# ---------------------------------------------------------------------------

PDF_VERSION_PREFIXES = tuple(
    ("%%PDF-%s" % version).encode("ascii")
    for version in ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "2.0")
)
# Aktive Konstrukte, die in einem Etikett oder Lieferschein nichts zu suchen
# haben. Ausdruecklich nur ein billiges Zusatznetz -- die massgebliche,
# allowlist-basierte Pruefung des Objektgraphen sitzt am Backend-Rand.
PDF_ACTIVE_MARKERS = (
    b"/JavaScript",
    b"/JS",
    b"/EmbeddedFile",
    b"/Launch",
    b"/OpenAction",
    b"/AA",
    b"/AcroForm",
    b"/RichMedia",
)

ZPL_COMMAND = re.compile(r"[\^~][A-Z@][A-Z0-9@]?", re.ASCII)
ZPL_ALLOWED = {
    "^XA", "^XZ", "^FO", "^FD", "^FS", "^A", "^A0", "^BC", "^BQ",
    "^BY", "^CI", "^PW", "^LL", "^LH",
}
ZPL_TEXT = re.compile(r"\A[\x20-\x7e\r\n]*\Z", re.ASCII)


def _revalidate_pdf_bytes(raw):
    """Magic, Version und Revisionsdisziplin -- ohne Fremdbibliothek."""
    if not raw.startswith(PDF_VERSION_PREFIXES):
        raise ValidationError("Artifact is not a PDF of an allowed version.")
    if raw.count(b"%%EOF") != 1:
        raise ValidationError("PDF must contain exactly one revision.")
    marker = raw.find(b"%%EOF")
    if raw[marker + len(b"%%EOF"):].strip(b"\r\n\t ") != b"":
        raise ValidationError("PDF has bytes after %%EOF.")
    for needle in PDF_ACTIVE_MARKERS:
        if needle in raw:
            raise ValidationError("PDF contains an active construct.")


def _revalidate_zpl_bytes(raw):
    """Vollstaendige Portierung der Backend-Allowlist. Anders als beim PDF
    braucht ZPL keine Fremdbibliothek, also gibt es hier keinen Grund, sich
    mit weniger zufriedenzugeben."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValidationError("ZPL must be ASCII.") from exc
    if not ZPL_TEXT.fullmatch(text):
        raise ValidationError("ZPL contains control characters.")
    if (
        not text.startswith("^XA")
        or not text.endswith("^XZ")
        or text.count("^XA") != 1
        or text.count("^XZ") != 1
    ):
        raise ValidationError("ZPL requires exactly one ^XA/^XZ document.")
    for position, character in enumerate(text):
        if character not in "^~":
            continue
        if character == "~":
            raise ValidationError("ZPL tilde commands are forbidden.")
        match = ZPL_COMMAND.match(text, position)
        if match is None or match.group() not in ZPL_ALLOWED:
            raise ValidationError("ZPL command is not allowed.")


ARTIFACT_REVALIDATORS = {
    "pdf": _revalidate_pdf_bytes,
    "zpl": _revalidate_zpl_bytes,
}


def _revalidate_artifact_bytes(artifact_kind, raw):
    revalidate = ARTIFACT_REVALIDATORS.get(artifact_kind)
    if revalidate is None:
        raise ValidationError("Artifact kind is not allowed.")
    revalidate(raw)


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
