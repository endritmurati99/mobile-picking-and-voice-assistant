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
from reportlab.pdfgen import canvas

MUSTER_TEXT = "MUSTER - kein gueltiges Versandlabel"
ROWS_PER_PACKLIST_PAGE = 25


def _draw_label_page(c, data):
    width, height = A6
    c.setPageSize(A6)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(6 * mm, height - 10 * mm, f"Absender: {data.get('sender_name', '')}")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(6 * mm, height - 22 * mm, data.get("carrier_name", ""))
    c.setFont("Helvetica", 8)
    c.drawString(6 * mm, height - 27 * mm, data.get("service_note", ""))

    r = data.get("recipient", {})
    c.setFont("Helvetica-Bold", 10)
    c.drawString(6 * mm, height - 40 * mm, "Empfaenger")
    c.setFont("Helvetica", 10)
    lines = [r.get("name", ""), r.get("street", ""), r.get("street2", ""),
             f"{r.get('zip', '')} {r.get('city', '')}".strip(), r.get("country_code", "")]
    y = height - 46 * mm
    for line in lines:
        if line:
            c.drawString(6 * mm, y, line)
            y -= 5 * mm

    c.setFont("Helvetica", 8)
    c.drawString(6 * mm, height - 78 * mm,
                 f"Gewicht: {data.get('total_weight_kg', 0.0):.3f} kg")
    c.drawString(6 * mm, height - 83 * mm, f"Lieferschein: {data.get('picking_name', '')}")

    barcode = code128.Code128(data.get("picking_name", ""), barHeight=10 * mm,
                              barWidth=0.3 * mm)
    barcode.drawOn(c, 6 * mm, height - 98 * mm)

    tracking = data.get("tracking_number", "")
    qr_widget = qr.QrCodeWidget(tracking)
    bounds = qr_widget.getBounds()
    size = 22 * mm
    d = Drawing(size, size, transform=[size / (bounds[2] - bounds[0]), 0, 0,
                                       size / (bounds[3] - bounds[1]), 0, 0])
    d.add(qr_widget)
    renderPDF.draw(d, c, width - size - 6 * mm, height - 100 * mm)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(6 * mm, height - 106 * mm, tracking)

    c.setFont("Helvetica-Bold", 8)
    c.setFillGray(0.4)
    c.drawString(6 * mm, 5 * mm, MUSTER_TEXT)
    c.setFillGray(0.0)
    c.showPage()


def _draw_packlist_pages(c, data):
    width, height = A4
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
        c.drawString(55 * mm, y, "Bezeichnung")
        c.drawString(150 * mm, y, "Menge")
        c.drawString(170 * mm, y, "kg/Stk")
        y -= 6 * mm
        c.setFont("Helvetica", 9)
        for item in chunk:
            c.drawString(20 * mm, y, str(item.get("default_code", "")))
            c.drawString(55 * mm, y, str(item.get("name", ""))[:55])
            c.drawRightString(162 * mm, y, f"{item.get('qty', 0.0):g}")
            c.drawRightString(185 * mm, y, f"{item.get('weight_kg', 0.0):.3f}")
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
