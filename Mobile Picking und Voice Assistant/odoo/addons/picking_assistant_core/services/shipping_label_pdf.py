"""Dummy-Versandlabel als PDF.

Reine Funktion ohne Odoo-Import, damit sie einzeln testbar bleibt. Seite 1
ist ein A6-Aufkleber, ab Seite 2 folgt die Packliste auf A4. ReportLab ist
Bestandteil des Odoo-Images (Odoo braucht es fuer eigene Berichte).
"""
import io

from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A4, A6
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

MUSTER_TEXT = "MUSTER - kein gueltiges Versandlabel"
ROWS_PER_PACKLIST_PAGE = 25
LABEL_MARGIN = 6 * mm

# Empfaenger-Block: kleinere Schrift als der Rest des Aufklebers, damit lange
# Firmennamen/Strassen umgebrochen werden koennen, ohne den Barcode-/QR-
# Bereich weiter unten zu ueberdecken. RECIPIENT_MAX_LINES begrenzt den Block
# nach unten hin hart (ueberzaehlige Zeilen werden abgeschnitten) statt den
# Aufkleber unkontrolliert wachsen zu lassen.
RECIPIENT_FONT = "Helvetica"
RECIPIENT_FONT_SIZE = 9
RECIPIENT_LINE_HEIGHT = 4.5 * mm
RECIPIENT_MAX_LINES = 6

PACKLIST_NAME_FONT = "Helvetica"
PACKLIST_NAME_FONT_SIZE = 9
PACKLIST_NAME_COLUMN_X = 55 * mm
PACKLIST_QTY_COLUMN_X = 150 * mm
PACKLIST_NAME_MAX_WIDTH = PACKLIST_QTY_COLUMN_X - PACKLIST_NAME_COLUMN_X - 5 * mm
PACKLIST_ARTICLE_COLUMN_X = 20 * mm
PACKLIST_ARTICLE_MAX_WIDTH = PACKLIST_NAME_COLUMN_X - PACKLIST_ARTICLE_COLUMN_X - 3 * mm


def _wrap_recipient_lines(raw_lines, max_width):
    """Bricht jede Adresszeile einzeln um und deckelt die Gesamtzeilenzahl."""
    wrapped = []
    for raw in raw_lines:
        if not raw:
            continue
        wrapped.extend(simpleSplit(raw, RECIPIENT_FONT, RECIPIENT_FONT_SIZE, max_width))
    return wrapped[:RECIPIENT_MAX_LINES]


def _truncate_to_width(text, font_name, font_size, max_width):
    """Kuerzt `text` mit "..." auf `max_width`, statt blind Zeichen zu zaehlen."""
    if stringWidth(text, font_name, font_size) <= max_width:
        return text
    suffix = "..."
    truncated = text
    while truncated and stringWidth(truncated + suffix, font_name, font_size) > max_width:
        truncated = truncated[:-1]
    return (truncated + suffix) if truncated else suffix


def _draw_label_page(c, data):
    width, height = A6
    c.setPageSize(A6)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(LABEL_MARGIN, height - 10 * mm, f"Absender: {data.get('sender_name', '')}")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(LABEL_MARGIN, height - 22 * mm, data.get("carrier_name", ""))
    c.setFont("Helvetica", 8)
    c.drawString(LABEL_MARGIN, height - 27 * mm, data.get("service_note", ""))

    r = data.get("recipient", {})
    c.setFont("Helvetica-Bold", 10)
    c.drawString(LABEL_MARGIN, height - 40 * mm, "Empfaenger")

    raw_lines = [r.get("name", ""), r.get("street", ""), r.get("street2", ""),
                 f"{r.get('zip', '')} {r.get('city', '')}".strip(), r.get("country_code", "")]
    usable_width = width - 2 * LABEL_MARGIN
    wrapped_lines = _wrap_recipient_lines(raw_lines, usable_width)
    c.setFont(RECIPIENT_FONT, RECIPIENT_FONT_SIZE)
    y = height - 46 * mm
    for line in wrapped_lines:
        c.drawString(LABEL_MARGIN, y, line)
        y -= RECIPIENT_LINE_HEIGHT

    c.setFont("Helvetica", 8)
    c.drawString(LABEL_MARGIN, height - 78 * mm,
                 f"Gewicht: {data.get('total_weight_kg') or 0.0:.3f} kg")
    c.drawString(LABEL_MARGIN, height - 83 * mm, f"Lieferschein: {data.get('picking_name', '')}")

    barcode = code128.Code128(data.get("picking_name", ""), barHeight=10 * mm,
                              barWidth=0.3 * mm)
    barcode.drawOn(c, LABEL_MARGIN, height - 98 * mm)

    tracking = data.get("tracking_number", "")
    qr_widget = qr.QrCodeWidget(tracking)
    bounds = qr_widget.getBounds()
    size = 22 * mm
    d = Drawing(size, size, transform=[size / (bounds[2] - bounds[0]), 0, 0,
                                       size / (bounds[3] - bounds[1]), 0, 0])
    d.add(qr_widget)
    renderPDF.draw(d, c, width - size - LABEL_MARGIN, height - 100 * mm)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(LABEL_MARGIN, height - 106 * mm, tracking)

    c.setFont("Helvetica-Bold", 8)
    c.setFillGray(0.4)
    c.drawString(LABEL_MARGIN, 5 * mm, MUSTER_TEXT)
    c.setFillGray(0.0)
    c.showPage()


def _draw_packlist_pages(c, data):
    _, height = A4
    items = list(data.get("items", []))
    pages = [items[i:i + ROWS_PER_PACKLIST_PAGE]
             for i in range(0, len(items), ROWS_PER_PACKLIST_PAGE)] or [[]]
    for page_no, chunk in enumerate(pages, start=1):
        c.setPageSize(A4)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(20 * mm, height - 20 * mm,
                     f"Packliste {data.get('picking_name', '')}")
        c.setFont("Helvetica", 9)
        c.drawString(20 * mm, height - 27 * mm,
                     f"Sendung {data.get('tracking_number', '')}  Seite {page_no}/{len(pages)}")
        y = height - 40 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20 * mm, y, "Artikelnr.")
        c.drawString(PACKLIST_NAME_COLUMN_X, y, "Bezeichnung")
        c.drawString(PACKLIST_QTY_COLUMN_X, y, "Menge")
        c.drawString(170 * mm, y, "kg/Stk")
        y -= 6 * mm
        c.setFont("Helvetica", 9)
        for item in chunk:
            default_code = _truncate_to_width(
                str(item.get("default_code", "")), PACKLIST_NAME_FONT,
                PACKLIST_NAME_FONT_SIZE, PACKLIST_ARTICLE_MAX_WIDTH,
            )
            c.drawString(PACKLIST_ARTICLE_COLUMN_X, y, default_code)
            name = _truncate_to_width(str(item.get("name", "")), PACKLIST_NAME_FONT,
                                       PACKLIST_NAME_FONT_SIZE, PACKLIST_NAME_MAX_WIDTH)
            c.drawString(PACKLIST_NAME_COLUMN_X, y, name)
            c.drawRightString(162 * mm, y, f"{item.get('qty') or 0.0:g}")
            c.drawRightString(185 * mm, y, f"{item.get('weight_kg') or 0.0:.3f}")
            y -= 5.5 * mm
        c.setFont("Helvetica-Bold", 8)
        c.setFillGray(0.4)
        c.drawString(20 * mm, 12 * mm, MUSTER_TEXT)
        c.setFillGray(0.0)
        c.showPage()


def render_label(data):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A6, pageCompression=0)
    c.setTitle(f"Versandlabel {data.get('picking_name', '')}")
    _draw_label_page(c, data)
    _draw_packlist_pages(c, data)
    c.save()
    return buffer.getvalue()
