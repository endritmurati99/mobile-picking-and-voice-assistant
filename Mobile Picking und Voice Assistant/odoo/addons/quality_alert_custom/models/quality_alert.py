import base64

from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.tools.mimetypes import guess_mimetype
from markupsafe import Markup, escape


class QualityAlertStage(models.Model):
    _name = "quality.alert.stage.custom"
    _description = "Quality Alert Stage"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    fold = fields.Boolean(default=False)


class QualityAlert(models.Model):
    _name = "quality.alert.custom"
    _description = "Quality Alert"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="Referenz",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "quality.alert.custom"
        ) or "NEU",
    )
    description = fields.Text(string="Beschreibung", required=True)

    # Verknüpfungen
    picking_id = fields.Many2one(
        "stock.picking", string="Transfer", ondelete="set null", tracking=True,
    )
    product_id = fields.Many2one(
        "product.product", string="Produkt", ondelete="set null", tracking=True,
    )
    location_id = fields.Many2one(
        "stock.location", string="Lagerort", ondelete="set null",
    )
    lot_id = fields.Many2one(
        "stock.lot", string="Charge/Seriennummer", ondelete="set null",
    )

    # Workflow
    stage_id = fields.Many2one(
        "quality.alert.stage.custom",
        string="Status",
        tracking=True,
        group_expand="_read_group_stage_ids",
        default=lambda self: self._get_default_stage(),
    )
    priority = fields.Selection(
        [("0", "Normal"), ("1", "Niedrig"), ("2", "Hoch"), ("3", "Kritisch")],
        string="Priorität",
        default="0",
        tracking=True,
    )
    user_id = fields.Many2one(
        "res.users", string="Erfasst von", default=lambda self: self.env.user,
    )

    # Systembewertung (automatische Auswertung via n8n-Heuristik)
    ai_disposition = fields.Selection(
        [
            ("sellable", "Verkaufbar"),
            ("rework", "Nacharbeit"),
            ("quarantine", "Quarantäne"),
            ("scrap", "Totalschaden"),
        ],
        string="Einstufung",
        tracking=True,
    )
    ai_confidence = fields.Float(string="Konfidenz", tracking=True)
    ai_summary = fields.Text(string="System-Begründung", tracking=True)
    ai_enhanced_description = fields.Text(string="Systembeschreibung")
    ai_photo_analysis = fields.Text(string="Fotoanalyse")
    ai_recommended_action = fields.Text(string="Empfohlene Aktion", tracking=True)
    ai_last_analyzed_at = fields.Datetime(string="Analysiert am", tracking=True)
    ai_provider = fields.Char(string="Provider")
    ai_model = fields.Char(string="Modell")
    ai_evaluation_status = fields.Selection(
        [
            ("pending", "Ausstehend"),
            ("completed", "Abgeschlossen"),
            # Vierter Wert: das Modell hat NICHT geantwortet, und niemand hat
            # ersatzweise geraten. Ohne diesen Zustand muesste ein Ausfall als
            # "fehlgeschlagen" oder -- schlimmer -- als Bewertung erscheinen.
            ("review_required", "Manuelle Pruefung noetig"),
            ("failed", "Fehlgeschlagen"),
        ],
        string="Analyse-Status",
        tracking=True,
    )
    ai_failure_reason = fields.Char(string="Fehlergrund")

    # Monoton steigende Revision des Datensatzes. `_enqueue_job_event` verlangt
    # `aggregate_revision >= 1`; ein spaeteres Ereignis zum selben Alert traegt
    # damit eine hoehere Revision und kann ein aelteres abloesen.
    integration_revision = fields.Integer(
        string="Integrationsrevision", default=1, required=True, copy=False,
    )

    # Fotos
    photo = fields.Binary(string="Foto", attachment=True)
    photo_filename = fields.Char(string="Dateiname")
    photo_count = fields.Integer(string="Anzahl Fotos", compute="_compute_photo_count")
    photo_gallery = fields.Html(string="Foto-Galerie", compute="_compute_photo_gallery", sanitize=False)

    def _compute_photo_count(self):
        for rec in self:
            rec.photo_count = self.env["ir.attachment"].search_count([
                ("res_model", "=", "quality.alert.custom"),
                ("res_id", "=", rec.id),
                ("mimetype", "like", "image"),
            ])

    def _compute_photo_gallery(self):
        for rec in self:
            attachments = self.env["ir.attachment"].search([
                ("res_model", "=", "quality.alert.custom"),
                ("res_id", "=", rec.id),
                ("mimetype", "like", "image"),
            ])
            if not attachments:
                rec.photo_gallery = Markup("<p style='color:#888'>Keine Fotos vorhanden.</p>")
                continue
            parts = []
            for att in attachments:
                url = escape(f"/web/image/{int(att.id)}")
                title = escape(att.name or "")
                parts.append(
                    f'<a href="{url}" target="_blank" title="{title}"'
                    f' style="display:block;overflow:hidden;border-radius:8px;">'
                    f'<img src="{url}" style="width:100%;height:120px;'
                    f'border:1px solid #ddd;object-fit:cover;display:block;'
                    f'border-radius:8px;"/>'
                    f'</a>'
                )
            html = (
                '<div style="display:grid;'
                'grid-template-columns:repeat(auto-fill,minmax(120px,1fr));'
                'gap:8px;padding:8px 0;max-height:300px;overflow-y:auto;">'
                + "".join(parts)
                + '</div>'
            )
            rec.photo_gallery = Markup(html)

    def _get_default_stage(self):
        return self.env["quality.alert.stage.custom"].search(
            [], order="sequence asc", limit=1
        )

    # Nur Felder, die die Bewertung beeinflussen. Eine Revision, die bei jedem
    # ai_*-Rueckschreiben hochzaehlt, wuerde die eigene Antwort als Aenderung
    # des Sachverhalts missverstehen.
    _REVISION_TRIGGER_FIELDS = ("description", "priority", "photo")

    # Abbildung Callback-Status -> Analyse-Status. Nur `succeeded` darf ein
    # Urteil schreiben; alles andere laesst ai_disposition leer, damit im
    # System nie eine Bewertung steht, die kein Modell getroffen hat.
    _ASSESSMENT_STATUS_MAP = {
        "succeeded": "completed",
        "review_required": "review_required",
        "failed": "failed",
    }

    def api_apply_assessment(self, status, result, error):
        """Traegt das Ergebnis der Kette in die ai_*-Felder.

        Aufgerufen aus `picking.assistant.callback.receipt.api_apply_callback`,
        also in DERSELBEN Transaktion wie Job- und Receipt-Zustand: entweder
        der Callback gilt vollstaendig, oder er gilt gar nicht.
        """
        self.ensure_one()
        mapped = self._ASSESSMENT_STATUS_MAP.get(status)
        if mapped is None:
            raise ValidationError(f"Unbekannter Bewertungsstatus: {status!r}")
        result = result or {}
        error = error or {}
        values = {
            "ai_evaluation_status": mapped,
            "ai_last_analyzed_at": fields.Datetime.now(),
            "ai_failure_reason": error.get("message") or False,
        }
        if mapped == "completed":
            values.update(
                {
                    "ai_disposition": result.get("disposition") or False,
                    "ai_confidence": result.get("confidence") or 0.0,
                    "ai_summary": result.get("summary") or False,
                    "ai_recommended_action": result.get("recommended_action") or False,
                    "ai_provider": result.get("provider") or False,
                    "ai_model": result.get("model") or False,
                }
            )
        self.sudo().write(values)
        return True

    # Mehr als drei Fotos zu pruefen kostet je Bild rund 21 Sekunden und bringt
    # selten mehr Erkenntnis. Die Gesamtzahl reist trotzdem mit, damit niemand
    # glaubt, es sei alles angesehen worden.
    _MAX_ASSESSMENT_PHOTOS = 3

    @api.model
    def api_get_assessment_media(self, job_id, delivery_generation, processing_lease_token):
        """Liefert dem Bewertungsschritt Meldefoto und Katalogbild.

        Der Zugriff haengt am JOB, nicht an einer mitgeschickten Alert-Kennung:
        wer den Alert frei waehlen koennte, kaeme mit einer einzigen gueltigen
        Signatur an jedes Foto im System. Dieselbe Lease- und
        Generationspruefung wie bei `api_get_job_media` -- eine abgelaufene
        Bearbeitung darf nichts mehr lesen.

        Gelesen werden ausschliesslich Anhaenge mit `res_field = False`. Odoo
        legt je Foto ZWEI Zeilen an: die Ablage des Binaerfeldes `photo` (von
        Odoo neu kodiert, und es gibt sie nur einmal, auch bei mehreren Fotos)
        und diese hier mit den urspruenglichen Bytes und dem urspruenglichen
        Dateinamen.

        Der gespeicherte `mimetype` wird bewusst NICHT mitgeliefert. Die
        Leseseite bestimmt den Typ aus den Bytes -- derselbe Grundsatz, nach
        dem auf den signierten Routen ein deklarierter Content-Type nie als
        Beweis gilt.
        """
        job = self.env["picking.assistant.integration.job"].sudo().search(
            [("job_id", "=", job_id), ("aggregate_model", "=", self._name)],
            limit=1,
        )
        if not job:
            raise ValidationError(f"Unbekannter Job: {job_id!r}")
        job._require_current_generation(delivery_generation, processing_lease_token)

        alert = self.sudo().browse(job.aggregate_res_id).exists()
        if not alert:
            raise ValidationError(f"Zum Job {job_id!r} fehlt der Alert.")

        attachments = self.env["ir.attachment"].sudo()
        domain = [
            ("res_model", "=", self._name),
            ("res_id", "=", alert.id),
            ("res_field", "=", False),
        ]
        total = attachments.search_count(domain)
        photos = attachments.search(
            domain, order="id asc", limit=self._MAX_ASSESSMENT_PHOTOS
        )

        template = alert.product_id.product_tmpl_id
        reference = template.image_1920 if template else False
        return {
            "photos": [
                {
                    "filename": photo.name or "",
                    "data_b64": (photo.datas or b"").decode("ascii"),
                }
                for photo in photos
            ],
            "photo_total": total,
            "reference_image_b64": reference.decode("ascii") if reference else False,
            "product_label": alert.product_id.display_name if alert.product_id else "",
        }

    def write(self, vals):
        bumps = any(field in vals for field in self._REVISION_TRIGGER_FIELDS)
        if not bumps or "integration_revision" in vals:
            return super().write(vals)
        for record in self:
            super(QualityAlert, record).write(
                dict(vals, integration_revision=record.integration_revision + 1)
            )
        return True

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return self.env["quality.alert.stage.custom"].search([])

    def action_set_in_progress(self):
        stage = self.env.ref(
            "quality_alert_custom.stage_in_progress", raise_if_not_found=False
        )
        if stage:
            self.write({"stage_id": stage.id})

    def action_set_done(self):
        stage = self.env.ref(
            "quality_alert_custom.stage_done", raise_if_not_found=False
        )
        if stage:
            self.write({"stage_id": stage.id})

    @api.model
    def api_create_alert(self, vals):
        """
        Atomare Methode für externe Alert-Erstellung.
        Akzeptiert photos als Liste von {data_b64, filename}.
        sudo() wird verwendet, da die Rechteprüfung auf API-Ebene (FastAPI) erfolgt.
        """
        photos = vals.pop("photos", [])
        single_b64 = vals.pop("photo_base64", None)
        single_name = vals.pop("photo_filename", None)
        if single_b64 and single_name:
            photos.insert(0, {"data_b64": single_b64, "filename": single_name})

        if photos:
            vals["photo"] = photos[0]["data_b64"]

        alert = self.sudo().create(vals)

        for i, p in enumerate(photos):
            self.env["ir.attachment"].sudo().create({
                "name": p.get("filename", f"photo_{i}.jpg"),
                "type": "binary",
                "datas": p["data_b64"],
                "res_model": self._name,
                "res_id": alert.id,
                # Der Typ kommt aus den Bytes, nicht aus einer Annahme. Vorher
                # stand hier hart "image/jpeg" -- auch fuer PNG und WebP, und
                # die Bestandsanhaenge tragen deshalb einen falschen Wert. Die
                # Leseseite (`api_get_assessment_media` -> Backend) glaubt ihn
                # ohnehin nicht; korrigiert wird er trotzdem, weil ein falscher
                # Wert in der Datenbank irgendwann jemanden in die Irre fuehrt.
                "mimetype": guess_mimetype(base64.b64decode(p["data_b64"])),
            })

        # Transactional Outbox: der Beleg entsteht in DERSELBEN Transaktion wie
        # der Datensatz. Entweder beides oder nichts -- ein Alert ohne Ereignis
        # waere eine Bewertung, die nie kommt, ein Ereignis ohne Alert eine
        # Bewertung fuer nichts. Der Anhang-Zaehler steht erst hier fest,
        # deshalb wird der Envelope nach den Anhaengen gebaut.
        alert.sudo().write({"ai_evaluation_status": "pending"})
        built = self.env["quality.alert.event.builder"].build(alert)
        self.env["picking.assistant.integration.job"]._enqueue_job_event(
            job_type="quality_assessment",
            aggregate_model=alert._name,
            aggregate_res_id=alert.id,
            aggregate_revision=alert.integration_revision,
            event_id=built["event_id"],
            event_name="quality.assessment.requested.v1",
            envelope_text=built["envelope_text"],
            payload_fingerprint=built["payload_fingerprint"],
            correlation_id=built["correlation_id"],
            job_id=built["job_id"],
        )

        return {"alert_id": alert.id, "name": alert.name}
