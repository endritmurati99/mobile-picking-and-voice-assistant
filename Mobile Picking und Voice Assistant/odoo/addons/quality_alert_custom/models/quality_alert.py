# -*- coding: utf-8 -*-
from odoo import models, fields, api

class QualityAlert(models.Model):
    _inherit = 'quality.alert'

    # Verknüpfung zum Picking-Prozess (Referenzielle Integrität)
    x_picking_id = fields.Many2one(
        'stock.picking', 
        string="Zugehöriges Picking", 
        help="Das Picking, bei dem der Defekt festgestellt wurde."
    )

    # Das Binärfeld für das Foto (wird als bytea in Postgres gespeichert)
    x_damage_photo = fields.Binary(
        string="Schadensfoto", 
        attachment=True, # Speichert das Bild im Dateisystem statt in der DB (Performance!)
        help="Foto der Beschädigung für die Dokumentation."
    )

    # Problemkategorisierung für n8n-Auswertungen
    x_problem_category = fields.Selection([
        ('damaged', 'Beschädigt'),
        ('wrong_item', 'Falscher Artikel'),
        ('missing_part', 'Fehlendes Teil'),
        ('label_issue', 'Etiketten-Problem'),
        ('bin_issue', 'Fach-Problem'),
        ('other', 'Sonstiges')
    ], string="Problem-Kategorie", default='damaged', required=True)

    # Ausführliche Beschreibung vom Voice-Assistant
    x_description_long = fields.Text(
        string="Detail-Beschreibung", 
        help="Vollständige Transkription des Sprachbefehls."
    )
