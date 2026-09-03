"""Reine Funktion, keine Odoo-Abhaengigkeit: testbar ohne Datenbank.

Hinweis: `pypdf` ist im verwendeten Odoo-Image NICHT vorhanden
(ModuleNotFoundError geprueft). Deshalb wird der Text je Seite ueber die
unkomprimierten Content-Streams ausgelesen (Renderer nutzt
`pageCompression=0`, siehe shipping_label_pdf.py). Jeder ReportLab-
`showPage()`-Aufruf erzeugt genau einen Content-Stream, die Reihenfolge der
Streams im PDF entspricht daher der Seitenreihenfolge.
"""
import re

from odoo.tests.common import BaseCase

from odoo.addons.picking_assistant_core.services.shipping_label_pdf import render_label


def _sample(items=None):
    return {
        "picking_name": "WH/OUT/00066",
        "tracking_number": "PWR-DHL-00066-4F7A",
        "carrier_name": "DHL Paket",
        "service_note": "Standard, bis 2 kg",
        "sender_name": "Lager 1",
        "recipient": {
            "name": "Alpen Bau GmbH", "street": "Ringstrasse 5", "street2": "",
            "zip": "1010", "city": "Wien", "country_code": "AT",
        },
        "items": items or [
            {"default_code": "301121", "name": "Demo Klemmbaustein 2x4 rot",
             "qty": 4.0, "weight_kg": 0.003},
        ],
        "total_weight_kg": 0.012,
    }


_STREAM_RE = re.compile(rb"stream\r?\n(.*?)endstream", re.DOTALL)
_TJ_RE = re.compile(r"\((?:[^()\\]|\\.)*\)\s*Tj")


def _page_texts(pdf_bytes):
    """Extrahiert je Content-Stream (= Seite) die gezeichneten Textstrings."""
    texts = []
    for raw_stream in _STREAM_RE.findall(pdf_bytes):
        decoded_stream = raw_stream.decode("latin-1", errors="ignore")
        fragments = []
        for match in _TJ_RE.findall(decoded_stream):
            literal = match[match.index("(") + 1:match.rindex(")")]
            literal = literal.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
            fragments.append(literal)
        texts.append(" ".join(fragments))
    return texts


class TestRenderLabel(BaseCase):
    def test_returns_pdf_with_two_pages(self):
        pdf = render_label(_sample())
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(len(_page_texts(pdf)), 2)

    def test_label_page_contains_tracking_recipient_and_muster(self):
        texts = _page_texts(render_label(_sample()))
        self.assertIn("PWR-DHL-00066-4F7A", texts[0])
        self.assertIn("Wien", texts[0])
        self.assertIn("MUSTER", texts[0])
        self.assertIn("DHL Paket", texts[0])

    def test_packlist_page_lists_items(self):
        texts = _page_texts(render_label(_sample()))
        self.assertIn("301121", texts[1])
        self.assertIn("Klemmbaustein", texts[1])

    def test_many_items_spill_onto_further_pages(self):
        items = [
            {"default_code": f"A{i:04d}", "name": f"Artikel {i}", "qty": 1.0,
             "weight_kg": 0.01}
            for i in range(60)
        ]
        texts = _page_texts(render_label(_sample(items)))
        self.assertGreaterEqual(len(texts), 3)
        self.assertIn("A0059", texts[-1])
