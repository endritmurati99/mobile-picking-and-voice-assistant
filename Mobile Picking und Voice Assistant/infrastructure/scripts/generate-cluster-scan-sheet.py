#!/usr/bin/env python3
"""Erzeugt den einseitigen Cluster-Scantestbogen als Vektor-PDF.

Das Skript nutzt ausschließlich ReportLab aus dem laufenden Odoo-Container.

Beispiel vom Projektroot aus:

    docker exec -i mobilepickingundvoiceassistant-odoo-1 \
      python3 - --output /tmp/cluster-scan-testbogen.pdf \
      < infrastructure/scripts/generate-cluster-scan-sheet.py
    docker cp \
      mobilepickingundvoiceassistant-odoo-1:/tmp/cluster-scan-testbogen.pdf \
      docs/testing/cluster-scan-testbogen.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm


PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 12 * mm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

NAVY = colors.HexColor("#16324F")
BLUE = colors.HexColor("#176B87")
BLUE_TINT = colors.HexColor("#EAF5F8")
ORANGE = colors.HexColor("#A94F00")
ORANGE_TINT = colors.HexColor("#FFF3E8")
RED = colors.HexColor("#A61B1B")
RED_TINT = colors.HexColor("#FDECEC")
INK = colors.HexColor("#17202A")
MUTED = colors.HexColor("#4E5D6C")
WHITE = colors.white


def add_text(
    page: Drawing,
    x: float,
    y: float,
    value: str,
    *,
    size: float,
    color=INK,
    font: str = "Helvetica",
    anchor: str = "start",
) -> None:
    """Platziert eine einzelne Textzeile auf der Seite."""
    page.add(
        String(
            x,
            y,
            value,
            fontName=font,
            fontSize=size,
            fillColor=color,
            textAnchor=anchor,
        )
    )


def add_barcode(
    page: Drawing,
    value: str,
    *,
    center_x: float,
    y: float,
    height: float,
) -> None:
    """Zeichnet einen Code128 mit ausreichender Ruhezone zentriert ein."""
    barcode = createBarcodeDrawing(
        "Code128",
        value=value,
        barWidth=0.42 * mm,
        barHeight=height,
        humanReadable=False,
        quiet=True,
    )
    barcode.translate(center_x - barcode.width / 2, y)
    page.add(barcode)


def add_scan_card(
    page: Drawing,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    accent,
    status: str,
    description: str,
    value: str,
    barcode_y: float,
    barcode_height: float,
) -> None:
    """Zeichnet eine kompakte Karte mit Status, Beschreibung und Barcode."""
    page.add(
        Rect(
            x,
            y,
            width,
            height,
            rx=3 * mm,
            ry=3 * mm,
            fillColor=WHITE,
            strokeColor=accent,
            strokeWidth=1.2,
        )
    )
    add_text(
        page,
        x + 4 * mm,
        y + height - 6.5 * mm,
        status,
        size=8,
        color=accent,
        font="Helvetica-Bold",
    )
    if description:
        add_text(
            page,
            x + width / 2,
            y + height - 13 * mm,
            description,
            size=8.5,
            color=INK,
            anchor="middle",
        )
    add_barcode(
        page,
        value,
        center_x=x + width / 2,
        y=barcode_y,
        height=barcode_height,
    )
    add_text(
        page,
        x + width / 2,
        y + 3.2 * mm,
        value,
        size=10.5,
        color=INK,
        font="Helvetica-Bold",
        anchor="middle",
    )


def build_sheet() -> Drawing:
    """Baut den vollständigen A4-Testbogen als ReportLab-Zeichnung."""
    page = Drawing(PAGE_WIDTH, PAGE_HEIGHT)
    page.add(Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fillColor=WHITE, strokeColor=None))

    # Kopf
    page.add(
        Rect(
            MARGIN,
            261 * mm,
            CONTENT_WIDTH,
            24 * mm,
            rx=3 * mm,
            ry=3 * mm,
            fillColor=NAVY,
            strokeColor=None,
        )
    )
    add_text(
        page,
        PAGE_WIDTH / 2,
        275.5 * mm,
        "CLUSTER-SCANTESTBOGEN",
        size=19,
        color=WHITE,
        font="Helvetica-Bold",
        anchor="middle",
    )
    add_text(
        page,
        PAGE_WIDTH / 2,
        266.5 * mm,
        "Lager 1 | WH/OUT/00061 + WH/OUT/00064",
        size=9.5,
        color=WHITE,
        anchor="middle",
    )

    # Richtige Artikel
    page.add(
        Rect(
            MARGIN,
            190 * mm,
            CONTENT_WIDTH,
            64 * mm,
            rx=3 * mm,
            ry=3 * mm,
            fillColor=BLUE_TINT,
            strokeColor=BLUE,
            strokeWidth=1.2,
        )
    )
    add_text(
        page,
        MARGIN + 5 * mm,
        245 * mm,
        "1  RICHTIGE ARTIKEL",
        size=12,
        color=BLUE,
        font="Helvetica-Bold",
    )
    add_text(
        page,
        MARGIN + 5 * mm,
        237.5 * mm,
        "Produktcode scannen und erwartete Scanner-Reaktion prüfen.",
        size=8.5,
        color=MUTED,
    )

    card_gap = 5 * mm
    card_width = (CONTENT_WIDTH - 10 * mm - card_gap) / 2
    left_x = MARGIN + 5 * mm
    right_x = left_x + card_width + card_gap
    add_scan_card(
        page,
        x=left_x,
        y=196 * mm,
        width=card_width,
        height=37 * mm,
        accent=BLUE,
        status="POSITIV",
        description="Erster realer Halt | A-01",
        value="6023350",
        barcode_y=204 * mm,
        barcode_height=12.5 * mm,
    )
    add_scan_card(
        page,
        x=right_x,
        y=196 * mm,
        width=card_width,
        height=37 * mm,
        accent=BLUE,
        status="POSITIV",
        description="Gruppierter Sollhalt | C-02 | 4 Stück",
        value="343701",
        barcode_y=204 * mm,
        barcode_height=12.5 * mm,
    )

    # Falsche Artikel
    page.add(
        Rect(
            MARGIN,
            128 * mm,
            CONTENT_WIDTH,
            54 * mm,
            rx=3 * mm,
            ry=3 * mm,
            fillColor=ORANGE_TINT,
            strokeColor=ORANGE,
            strokeWidth=1.2,
        )
    )
    add_text(
        page,
        MARGIN + 5 * mm,
        173 * mm,
        "2  DECOYS / NEGATIVTEST",
        size=12,
        color=ORANGE,
        font="Helvetica-Bold",
    )
    add_text(
        page,
        MARGIN + 5 * mm,
        165.5 * mm,
        "Beide Codes müssen als falscher Artikel abgewiesen werden.",
        size=8.5,
        color=MUTED,
    )
    add_scan_card(
        page,
        x=left_x,
        y=133 * mm,
        width=card_width,
        height=28 * mm,
        accent=ORANGE,
        status="DECOY - MUSS ABGEWIESEN WERDEN",
        description="",
        value="343702",
        barcode_y=139 * mm,
        barcode_height=9.5 * mm,
    )
    add_scan_card(
        page,
        x=right_x,
        y=133 * mm,
        width=card_width,
        height=28 * mm,
        accent=ORANGE,
        status="DECOY - MUSS ABGEWIESEN WERDEN",
        description="",
        value="343710",
        barcode_y=139 * mm,
        barcode_height=9.5 * mm,
    )

    # Kartoncodes: bewusst räumlich und farblich von Artikelcodes getrennt.
    page.add(
        Rect(
            MARGIN,
            25 * mm,
            CONTENT_WIDTH,
            95 * mm,
            rx=3 * mm,
            ry=3 * mm,
            fillColor=RED_TINT,
            strokeColor=RED,
            strokeWidth=2,
        )
    )
    add_text(
        page,
        PAGE_WIDTH / 2,
        109.5 * mm,
        "3  KARTONCODES - BUCHT IN ODOO",
        size=14,
        color=RED,
        font="Helvetica-Bold",
        anchor="middle",
    )
    add_text(
        page,
        PAGE_WIDTH / 2,
        101 * mm,
        "Nur nach Batchanlage und nur für eine bewusst beabsichtigte Buchung scannen.",
        size=9,
        color=RED,
        font="Helvetica-Bold",
        anchor="middle",
    )

    carton_x = MARGIN + 5 * mm
    carton_width = CONTENT_WIDTH - 10 * mm
    for y, label, value in (
        (65 * mm, "KARTON 1 | WH/OUT/00061", "CLUSTER-B1/WH/OUT/00061"),
        (30 * mm, "KARTON 2 | WH/OUT/00064", "CLUSTER-B2/WH/OUT/00064"),
    ):
        page.add(
            Rect(
                carton_x,
                y,
                carton_width,
                31 * mm,
                rx=2 * mm,
                ry=2 * mm,
                fillColor=WHITE,
                strokeColor=RED,
                strokeWidth=1.2,
            )
        )
        add_text(
            page,
            carton_x + 4 * mm,
            y + 24.5 * mm,
            f"BUCHT IN ODOO | {label}",
            size=8.5,
            color=RED,
            font="Helvetica-Bold",
        )
        add_barcode(
            page,
            value,
            center_x=PAGE_WIDTH / 2,
            y=y + 7 * mm,
            height=12 * mm,
        )
        add_text(
            page,
            PAGE_WIDTH / 2,
            y + 2.5 * mm,
            value,
            size=10.5,
            color=INK,
            font="Helvetica-Bold",
            anchor="middle",
        )

    add_text(
        page,
        PAGE_WIDTH / 2,
        15 * mm,
        "Code128 | Klartext entspricht exakt dem Scanwert | A4 bei 100 % drucken",
        size=8,
        color=MUTED,
        anchor="middle",
    )
    return page


def write_pdf(output: Path) -> None:
    """Schreibt den Testbogen an den angeforderten Pfad."""
    if output.suffix.lower() != ".pdf":
        raise ValueError("--output muss auf .pdf enden")
    output.parent.mkdir(parents=True, exist_ok=True)
    renderPDF.drawToFile(
        build_sheet(),
        str(output),
        msg="Cluster-Scantestbogen Lager 1",
        canvasKwds={"pageCompression": 1, "invariant": 1},
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Einseitigen Cluster-Scantestbogen als Code128-Vektor-PDF erzeugen."
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Zielpfad der PDF-Datei",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    write_pdf(args.output)
    print(f"Testbogen erzeugt: {args.output}")


if __name__ == "__main__":
    main()
