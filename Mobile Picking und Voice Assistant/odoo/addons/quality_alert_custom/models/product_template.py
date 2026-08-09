"""Die SOLL-Beschreibung eines Artikels -- einmal geprueft, dann fest.

**Warum das Feld existiert.** Der Artikelabgleich der Bewertungskette
vergleicht keine Pixel: das Bildmodell beschreibt Katalogbild und Meldefoto
getrennt, das Textmodell entscheidet auf den zwei Beschreibungen. Die
SOLL-Seite dieser Rechnung war bisher fluechtig -- sie entstand bei jedem Lauf
neu aus dem Katalogbild.

Und sie entstand reproduzierbar falsch. Das Katalogbild von `[6023350] Brick
2x2x2 R=15 gelb` wurde an drei Tagen wortgleich als "plastic corner protector,
yellow, cube with rounded top" beschrieben (QA/0227 am 2026-08-08, QA/0233 und
QA/0234 am 2026-08-09). Ein Duplo-Stein ist kein Eckenschutz. Dagegen hilft
kein Mitteln ueber viele Laeufe: derselbe Aufruf auf demselben Bild ergibt
immer dasselbe Wort. Es hilft nur, den Satz einmal von einem Menschen
durchsehen zu lassen und danach stehen zu lassen.

**Warum eine Pruefsumme dabeisteht.** Ein Satz ueber ein Bild, das inzwischen
ein anderes ist, waere schlimmer als kein Satz -- er saehe geprueft aus.
Deshalb liefert `api_get_assessment_media` die Beschreibung nur aus, solange
sie zu den aktuellen Bytes gehoert. Wird das Katalogbild getauscht, faellt die
Kette von selbst auf den Bildaufruf zurueck, und das Feld muss neu erzeugt und
neu durchgesehen werden.

**Warum ein Produkt ohne Katalogbild trotzdem eine Beschreibung haben darf.**
23 von 70 Artikeln haben kein `image_1920`; fuer sie fiel der Abgleich bisher
still aus. Ein hinterlegter Satz laesst ihn laufen. Die Pruefsumme ist dann
leer, und "leer gegen leer" ist ein gueltiger Vergleich.
"""
from __future__ import annotations

import base64
import hashlib

from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ai_reference_description = fields.Text(
        string="Sollbeschreibung Katalogbild",
        help=(
            "Wie das Bildmodell den Artikel sehen SOLL: Art, Farbe, Form, "
            "Aufdruck -- ein kurzer englischer Satzteil, so wie ihn das "
            "Bildmodell selbst formulieren wuerde. Steht hier etwas, "
            "beschreibt die Bewertungskette das Katalogbild nicht mehr selbst."
        ),
    )
    ai_reference_image_sha1 = fields.Char(
        string="Pruefsumme des beschriebenen Bildes",
        readonly=True,
        copy=False,
        help=(
            "Zu welchen Bildbytes die Sollbeschreibung gehoert. Passt sie "
            "nicht mehr zum Katalogbild, wird die Beschreibung nicht "
            "ausgeliefert."
        ),
    )
    ai_reference_reviewed = fields.Boolean(
        string="Sollbeschreibung geprueft",
        copy=False,
        help=(
            "Ein Mensch hat die Beschreibung gegen den echten Artikel "
            "gelesen. Unmarkiert heisst: vom Bildmodell erzeugt und noch "
            "niemandem vorgelegt."
        ),
    )

    def _ai_reference_checksum(self):
        """Pruefsumme der KATALOGBILD-BYTES, oder False ohne Bild.

        Gerechnet wird auf den dekodierten Bytes, nicht auf dem
        Base64-Text: dieselben Bytes duerfen nicht je nach Kodierung zwei
        verschiedene Summen ergeben.
        """
        self.ensure_one()
        raw = self.image_1920
        if not raw:
            return False
        return hashlib.sha1(base64.b64decode(raw)).hexdigest()

    def ai_reference_description_if_current(self):
        """Die Beschreibung -- aber nur, solange sie zum aktuellen Bild passt.

        Der einzige Weg, auf dem die Kette an das Feld kommt. Wer die
        Beschreibung woanders ausliest, umgeht die Pruefsumme.
        """
        self.ensure_one()
        text = (self.ai_reference_description or "").strip()
        if not text:
            return ""
        if (self.ai_reference_image_sha1 or False) != self._ai_reference_checksum():
            return ""
        return text

    @api.model
    def api_set_reference_description(self, product_tmpl_id, description, reviewed=False):
        """Setzt Beschreibung UND Pruefsumme in einem Zug.

        Die Summe wird hier gerechnet und nicht vom Aufrufer mitgebracht:
        stammte sie von aussen, koennte ein Fehler in einem Hilfsskript eine
        Beschreibung dauerhaft gueltig erscheinen lassen, die zu keinem Bild
        gehoert. Eine leere Beschreibung loescht das Feld samt Summe -- damit
        ist die Zuruecknahme genauso einfach wie das Setzen.
        """
        template = self.sudo().browse(int(product_tmpl_id)).exists()
        if not template:
            return False
        text = (description or "").strip()
        if not text:
            template.write({
                "ai_reference_description": False,
                "ai_reference_image_sha1": False,
                "ai_reference_reviewed": False,
            })
            return True
        template.write({
            "ai_reference_description": text,
            "ai_reference_image_sha1": template._ai_reference_checksum(),
            "ai_reference_reviewed": bool(reviewed),
        })
        return True
