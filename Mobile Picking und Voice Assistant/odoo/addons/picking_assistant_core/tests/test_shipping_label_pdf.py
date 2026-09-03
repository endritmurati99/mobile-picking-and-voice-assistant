"""Reine Funktion, keine Odoo-Abhaengigkeit: testbar ohne Datenbank.

Hinweis: `pypdf` ist im verwendeten Odoo-Image NICHT vorhanden
(ModuleNotFoundError geprueft). Deshalb wird der Text je Seite ueber die
unkomprimierten Content-Streams ausgelesen (Renderer nutzt
`pageCompression=0`, siehe shipping_label_pdf.py). Jeder ReportLab-
`showPage()`-Aufruf erzeugt genau einen Content-Stream, die Reihenfolge der
Streams im PDF entspricht daher der Seitenreihenfolge. `drawString`/Tj-
Literale koennen Umlaute als PDF-Oktal-Escapes (z. B. `\374` fuer "ü" in
WinAnsi/cp1252) enthalten -- `_decode_pdf_literal` loest die vor der
cp1252-Dekodierung auf, sonst kaeme z. B. "M\374ller" statt "Müller" heraus.
"""
import re

from odoo.tests.common import BaseCase

from odoo.addons.picking_assistant_core.services.shipping_label_pdf import (
    LABEL_MARGIN,
    RECIPIENT_FONT,
    RECIPIENT_FONT_SIZE,
    render_label,
)
from reportlab.lib.pagesizes import A6
from reportlab.pdfbase.pdfmetrics import stringWidth


def _sample(items=None, recipient_overrides=None):
    recipient = {
        "name": "Alpen Bau GmbH", "street": "Ringstrasse 5", "street2": "",
        "zip": "1010", "city": "Wien", "country_code": "AT",
    }
    if recipient_overrides:
        recipient.update(recipient_overrides)
    return {
        "picking_name": "WH/OUT/00066",
        "tracking_number": "PWR-DHL-00066-4F7A",
        "carrier_name": "DHL Paket",
        "service_note": "Standard, bis 2 kg",
        "sender_name": "Lager 1",
        "recipient": recipient,
        "items": items or [
            {"default_code": "301121", "name": "Demo Klemmbaustein 2x4 rot",
             "qty": 4.0, "weight_kg": 0.003},
        ],
        "total_weight_kg": 0.012,
    }


_STREAM_RE = re.compile(rb"stream\r?\n(.*?)endstream", re.DOTALL)
_TJ_RE = re.compile(r"\((?:[^()\\]|\\.)*\)\s*Tj")
_OCTAL_DIGITS = "01234567"


def _decode_pdf_literal(literal):
    """Loest `\\ddd`-Oktal-Escapes und die Standard-Escapes eines PDF-String-
    Literals auf und dekodiert das Ergebnis als cp1252 (WinAnsiEncoding).

    `literal` ist der Inhalt zwischen den Klammern eines Tj-Strings, bereits
    latin-1-dekodiert -- jedes Zeichen entspricht dabei genau einem
    Roh-Byte aus dem PDF, `ord(ch) & 0xFF` liefert also das Original-Byte.
    """
    raw = bytearray()
    i, n = 0, len(literal)
    while i < n:
        ch = literal[i]
        if ch == "\\" and i + 1 < n:
            nxt = literal[i + 1]
            if nxt in _OCTAL_DIGITS:
                j = i + 1
                digits = ""
                while j < n and len(digits) < 3 and literal[j] in _OCTAL_DIGITS:
                    digits += literal[j]
                    j += 1
                raw.append(int(digits, 8) & 0xFF)
                i = j
                continue
            if nxt in ("(", ")", "\\"):
                raw.append(ord(nxt))
            else:
                raw.append(ord(nxt))
            i += 2
            continue
        raw.append(ord(ch) & 0xFF)
        i += 1
    return bytes(raw).decode("cp1252", errors="replace")


def _page_lines(pdf_bytes):
    """Liefert je Seite die Liste der gezeichneten Textzeilen (ein Tj-Aufruf
    entspricht hier einem `drawString`/`drawRightString`-Aufruf, also einer
    Zeile)."""
    pages = []
    for raw_stream in _STREAM_RE.findall(pdf_bytes):
        decoded_stream = raw_stream.decode("latin-1", errors="ignore")
        lines = []
        for match in _TJ_RE.findall(decoded_stream):
            literal = match[match.index("(") + 1:match.rindex(")")]
            lines.append(_decode_pdf_literal(literal))
        pages.append(lines)
    return pages


def _page_texts(pdf_bytes):
    """Wie `_page_lines`, aber je Seite zu einem String zusammengefasst
    (fuer einfache `assertIn`-Pruefungen auf Substrings)."""
    return [" ".join(lines) for lines in _page_lines(pdf_bytes)]


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

    def test_long_recipient_name_wraps_within_usable_width(self):
        long_name = "Müller & Söhne Bauunternehmung Grossbaustellen GmbH & Co. KG"
        lines = _page_lines(render_label(_sample(
            recipient_overrides={"name": long_name})))[0]

        usable_width = A6[0] - 2 * LABEL_MARGIN
        # Der lange Name muss ueber mehrere Zeilen verteilt worden sein --
        # keine einzelne gezeichnete Zeile darf die nutzbare Aufkleberbreite
        # ueberschreiten.
        wrapped_name_lines = [line for line in lines if line and line in long_name]
        self.assertGreaterEqual(
            len(wrapped_name_lines), 2,
            f"Name wurde nicht umgebrochen, Zeilen: {lines!r}")
        for line in wrapped_name_lines:
            self.assertLessEqual(
                stringWidth(line, RECIPIENT_FONT, RECIPIENT_FONT_SIZE),
                usable_width,
                f"Zeile {line!r} ist breiter als die nutzbare Aufkleberbreite")

    def test_none_numeric_values_do_not_raise(self):
        """JSON-`null` landet im Callback-Payload als Python `None`. `0.0`
        als Default in `data.get(key, 0.0)` greift dabei NICHT, weil der
        Schluessel vorhanden ist (nur mit Wert None) -- ohne `or 0.0` in
        `shipping_label_pdf.py` wuerde das f-String-Format (`:.3f`/`:g`)
        mit TypeError abbrechen.
        """
        sample = _sample(items=[
            {"default_code": "301121", "name": "Demo Klemmbaustein 2x4 rot",
             "qty": None, "weight_kg": 0.003},
        ])
        sample["total_weight_kg"] = None
        pdf = render_label(sample)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(len(_page_texts(pdf)), 2)

    def test_umlauts_in_recipient_are_decoded_correctly(self):
        texts = _page_texts(render_label(_sample(recipient_overrides={
            "name": "Müller & Söhne",
            "street": "Königsallee 3",
            "city": "Düsseldorf",
        })))
        self.assertIn("Müller", texts[0])
        self.assertIn("Düsseldorf", texts[0])
