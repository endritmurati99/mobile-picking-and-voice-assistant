#!/usr/bin/env python3
"""Erzeugt die beiden Demonstrationsbögen für den Handytest in Lager 2.

Das Skript nutzt ausschließlich ReportLab aus dem laufenden Odoo-Container und
erzeugt zwei Vektor-PDFs:

  * ``handy-start.pdf``            - Einseitiges Startblatt mit QR-Code,
                                     Anmeldedaten und Geräte-Hinweisen.
  * ``simulationsbogen-lager2.pdf`` - Zweiseitiger Simulationsbogen, der den
                                     physischen Regalrundgang ersetzt.

Beispiel vom Projektroot aus (WSL, Docker-Integration aus):

    docker exec -i mobilepickingundvoiceassistant-odoo-1 \
      python3 - --output-dir /tmp/demo-sheets \
      < infrastructure/scripts/generate-demo-sheets.py
    docker cp \
      mobilepickingundvoiceassistant-odoo-1:/tmp/demo-sheets/handy-start.pdf \
      docs/testing/handy-start.pdf
    docker cp \
      mobilepickingundvoiceassistant-odoo-1:/tmp/demo-sheets/simulationsbogen-lager2.pdf \
      docs/testing/simulationsbogen-lager2.pdf

Einzelne Bögen lassen sich über ``--sheet start`` bzw. ``--sheet simulation``
und ``--output`` erzeugen; ohne Angabe werden beide geschrieben.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.graphics.barcode import qr as qr_module
from reportlab.graphics.shapes import Drawing, Group, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas


# --------------------------------------------------------------------------
# Stammdaten - hier und nur hier anpassen, wenn ein anderer Sammelauftrag
# abgedeckt werden soll. Alle Werte stammen aus der Demonstrationsdatenbank
# ``lager2_o19`` (Instanz "Lager 2").
# --------------------------------------------------------------------------

SHEET_DATE = "19.08.2026"

# Startblatt -------------------------------------------------------------
PWA_URL = "https://172.22.147.158/"
LOGIN_USER = "lena.lager"
LOGIN_PASSWORD = "admin"
LOGIN_WAREHOUSE = "Lager 2"

# Abschnitt 1 - Halte in Rundgangsreihenfolge.
# Die App sortiert die Halte nach Lagerplatzname, deshalb ist die Reihenfolge
# dieser Liste identisch mit der Reihenfolge in der Anwendung.
PICK_STOPS = [
    {
        "location": "Regal A-01",
        "barcode": "4006381333931",
        "product": "Schraube M8x40",
        "split": "10 in Karton 1, 25 in Karton 2, 6 in Karton 3",
    },
    {
        "location": "Regal A-02",
        "barcode": "4006381333948",
        "product": "Mutter M8 DIN934",
        "split": "10 in Karton 1, 25 in Karton 2, 6 in Karton 3",
    },
    {
        "location": "Regal B-01",
        "barcode": "5901234123457",
        "product": "Winkel 40x40",
        "split": "5 in Karton 1",
    },
    {
        "location": "Regal C-02",
        "barcode": "4006381334013",
        "product": "Sechskantschraube M6",
        "split": "10 in Karton 3",
    },
]

# Abschnitt 2 - Kartonetiketten.
# Diese Namen vergibt Odoo selbst beim Start des Sammelauftrags nach dem Muster
# CLUSTER-B{Nummer}/{Auftrag}; die Nummer folgt der aufsteigenden Auftrags-ID
# (WH/OUT/00022 = ID 22, WH/OUT/00025 = ID 25, WH/OUT/00030 = ID 30).
CARTONS = [
    {"label": "Karton 1", "picking": "WH/OUT/00022", "value": "CLUSTER-B1/WH/OUT/00022"},
    {"label": "Karton 2", "picking": "WH/OUT/00025", "value": "CLUSTER-B2/WH/OUT/00025"},
    {"label": "Karton 3", "picking": "WH/OUT/00030", "value": "CLUSTER-B3/WH/OUT/00030"},
]

# Abschnitt 3 - Köder. Echte Artikel aus Lager 2, die aber zu keinem der drei
# Aufträge dieses Sammelauftrags gehören.
DECOYS = [
    {"barcode": "4006381333955", "product": "Unterlegscheibe M8"},
    {"barcode": "7622210100528", "product": "Gewindestange M8"},
]

# Abschnitt 4 - Prüfliste.
EXPECTED_RESULTS = [
    "8 Positionen gebucht (4 Halte, davon 2 auf je drei Kartons verteilt).",
    "3 Aufträge abgeschlossen: WH/OUT/00022, WH/OUT/00025, WH/OUT/00030.",
    "Beide Köder abgewiesen - die App meldet \"falscher Artikel\".",
    "Kein Fehlschlag beim Kartonwechsel: jeder Kartoncode wird angenommen.",
]


# --------------------------------------------------------------------------
# Seiten- und Farbdefinitionen (Stil des vorhandenen Cluster-Scanbogens)
# --------------------------------------------------------------------------

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 12 * mm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

NAVY = colors.HexColor("#16324F")
BLUE = colors.HexColor("#176B87")
BLUE_TINT = colors.HexColor("#EAF5F8")
GREEN = colors.HexColor("#1F6B3B")
GREEN_TINT = colors.HexColor("#EAF6EE")
ORANGE = colors.HexColor("#A94F00")
ORANGE_TINT = colors.HexColor("#FFF3E8")
RED = colors.HexColor("#A61B1B")
RED_TINT = colors.HexColor("#FDECEC")
INK = colors.HexColor("#17202A")
MUTED = colors.HexColor("#4E5D6C")
WHITE = colors.white
BLACK = colors.black

# Scanbarkeit: reines Schwarz auf reinem Weiß, Ruhezone mindestens 10 Module.
# Zusätzliche weiße Fläche rund um den Code, gemessen in Modulbreiten.
EXTRA_QUIET_MODULES = 8
# QR-Code: schwarze Kantenlänge (ohne Rand) und Randbreite in Modulen.
QR_DATA_SIZE = 62 * mm
QR_BORDER_MODULES = 4
EAN_BAR_WIDTH = 0.50 * mm  # 95 Module * 0,50 mm = 47,5 mm Nutzbreite (>= 45 mm)
CODE128_BAR_WIDTH = 0.52 * mm


# --------------------------------------------------------------------------
# Zeichenhilfen
# --------------------------------------------------------------------------


def add_text(
    page,
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


def add_lines(
    page,
    x: float,
    y: float,
    lines,
    *,
    size: float,
    leading: float,
    color=INK,
    font: str = "Helvetica",
    anchor: str = "start",
) -> None:
    """Setzt mehrere Zeilen untereinander, beginnend bei y (erste Zeile)."""
    for index, line in enumerate(lines):
        add_text(
            page,
            x,
            y - index * leading,
            line,
            size=size,
            color=color,
            font=font,
            anchor=anchor,
        )


def ean13_check_digit(body: str) -> str:
    """Berechnet die EAN-13-Prüfziffer aus den ersten zwölf Stellen."""
    total = sum(int(digit) * (3 if position % 2 else 1) for position, digit in enumerate(body[:12]))
    return str((10 - total % 10) % 10)


def resolve_symbology(value: str) -> str:
    """Entscheidet, ob ein Wert als EAN-13 oder als Code128 gezeichnet wird.

    ReportLab verhält sich bei ungültiger EAN-13-Prüfziffer je nach Version
    unterschiedlich (still umrechnen oder Ausnahme). Deshalb wird die Prüfziffer
    hier selbst nachgerechnet; bei Abweichung fällt der Code auf Code128 zurück.
    Die App erkennt ean_13, ean_8, code_128, code_39, qr_code und data_matrix -
    Code128 ist also immer ein gültiger Rückfall.
    """
    if len(value) == 13 and value.isdigit() and ean13_check_digit(value) == value[12]:
        return "EAN13"
    return "Code128"


def draw_barcode(page, value: str, *, center_x: float, y: float, height: float) -> str:
    """Zeichnet den Code mittig auf weißem Grund und liefert die Symbologie.

    Die Ruhezone wird als weißes Rechteck unter dem Code hinterlegt, damit kein
    getönter Abschnittshintergrund in die Ruhezone ragt.
    """
    symbology = resolve_symbology(value)
    if symbology == "EAN13":
        bar_width = EAN_BAR_WIDTH
        drawing = createBarcodeDrawing(
            "EAN13",
            value=value,
            barWidth=bar_width,
            barHeight=height,
            humanReadable=False,
            quiet=True,
            textColor=BLACK,
            barFillColor=BLACK,
            barStrokeWidth=0,
        )
    else:
        bar_width = CODE128_BAR_WIDTH
        drawing = createBarcodeDrawing(
            "Code128",
            value=value,
            barWidth=bar_width,
            barHeight=height,
            humanReadable=False,
            quiet=True,
        )

    # Weiße Unterlage inklusive zusätzlicher Ruhezone rundherum.
    # ReportLab legt selbst eine Ruhezone an (EAN-13: 9 Module, Code128:
    # mindestens 10 Module bzw. 6,35 mm). Der Zuschlag hier hebt die weiße
    # Fläche links und rechts sicher über die geforderten 10 Modulbreiten.
    pad_x = EXTRA_QUIET_MODULES * bar_width
    pad_y = 1.5 * mm
    page.add(
        Rect(
            center_x - drawing.width / 2 - pad_x,
            y - pad_y,
            drawing.width + 2 * pad_x,
            drawing.height + 2 * pad_y,
            fillColor=WHITE,
            strokeColor=None,
        )
    )
    group = Group(drawing)
    group.translate(center_x - drawing.width / 2, y)
    page.add(group)
    return symbology


def new_page() -> Drawing:
    """Legt eine leere, rein weiße A4-Seite an."""
    page = Drawing(PAGE_WIDTH, PAGE_HEIGHT)
    page.add(Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fillColor=WHITE, strokeColor=None))
    return page


def add_header(page, title: str, subtitle: str, *, y: float, height: float) -> None:
    """Zeichnet den dunklen Kopfbalken mit Titel und Unterzeile."""
    page.add(
        Rect(MARGIN, y, CONTENT_WIDTH, height, rx=3 * mm, ry=3 * mm, fillColor=NAVY, strokeColor=None)
    )
    add_text(
        page,
        PAGE_WIDTH / 2,
        y + height - 9 * mm,
        title,
        size=19,
        color=WHITE,
        font="Helvetica-Bold",
        anchor="middle",
    )
    add_text(page, PAGE_WIDTH / 2, y + height - 17 * mm, subtitle, size=9.5, color=WHITE, anchor="middle")


def add_box(page, *, y: float, height: float, fill, stroke, width: float = None, x: float = None):
    """Zeichnet einen abgesetzten Abschnittskasten."""
    page.add(
        Rect(
            MARGIN if x is None else x,
            y,
            CONTENT_WIDTH if width is None else width,
            height,
            rx=3 * mm,
            ry=3 * mm,
            fillColor=fill,
            strokeColor=stroke,
            strokeWidth=1.2,
        )
    )


# --------------------------------------------------------------------------
# Bogen 1 - Startblatt
# --------------------------------------------------------------------------


def build_start_sheet():
    """Baut das einseitige Startblatt mit QR-Code und Anmeldedaten."""
    page = new_page()
    add_header(page, "HANDY-START", f"Kommissionier-App | {LOGIN_WAREHOUSE} | Stand {SHEET_DATE}", y=262 * mm, height=23 * mm)

    add_text(
        page,
        PAGE_WIDTH / 2,
        253 * mm,
        "QR-Code mit der Handykamera scannen - nichts abtippen.",
        size=11,
        color=MUTED,
        anchor="middle",
    )

    # QR-Code: Die schwarze Fläche selbst soll mindestens 60 mm messen. Der
    # Rand von vier Modulen (Ruhezone) kommt oben drauf, deshalb wird die
    # Gesamtkante aus der tatsächlichen Modulzahl hochgerechnet.
    probe = qr_module.QrCodeWidget(PWA_URL, barLevel="M", barBorder=QR_BORDER_MODULES)
    probe.getBounds()  # füllt die Modulzahl
    data_modules = probe.qr.getModuleCount() or 25
    total_modules = data_modules + 2 * QR_BORDER_MODULES
    qr_size = QR_DATA_SIZE * total_modules / data_modules
    qr_y = 165 * mm
    widget = qr_module.QrCodeWidget(
        PWA_URL,
        barLevel="M",
        barBorder=QR_BORDER_MODULES,
        barWidth=qr_size,
        barHeight=qr_size,
    )
    # Weiße Unterlage mit zusätzlicher Ruhezone rund um den QR-Code.
    page.add(
        Rect(
            PAGE_WIDTH / 2 - qr_size / 2 - 5 * mm,
            qr_y - 5 * mm,
            qr_size + 10 * mm,
            qr_size + 10 * mm,
            fillColor=WHITE,
            strokeColor=None,
        )
    )
    qr_group = Group(widget)
    qr_group.translate(PAGE_WIDTH / 2 - qr_size / 2, qr_y)
    page.add(qr_group)

    add_text(
        page,
        PAGE_WIDTH / 2,
        155 * mm,
        PWA_URL,
        size=16,
        color=INK,
        font="Helvetica-Bold",
        anchor="middle",
    )
    add_text(
        page,
        PAGE_WIDTH / 2,
        149 * mm,
        "Falls der QR-Code nicht gelesen wird: Adresse von Hand im Browser eingeben.",
        size=9,
        color=MUTED,
        anchor="middle",
    )

    # Anmeldedaten
    add_box(page, y=100 * mm, height=42 * mm, fill=BLUE_TINT, stroke=BLUE)
    add_text(page, MARGIN + 6 * mm, 134 * mm, "ANMELDUNG", size=12, color=BLUE, font="Helvetica-Bold")
    rows = [
        ("Benutzer", LOGIN_USER),
        ("Passwort", LOGIN_PASSWORD),
        ("Lager", LOGIN_WAREHOUSE),
    ]
    for index, (label, value) in enumerate(rows):
        row_y = 125 * mm - index * 8 * mm
        add_text(page, MARGIN + 6 * mm, row_y, label, size=10.5, color=MUTED)
        add_text(page, MARGIN + 40 * mm, row_y, value, size=13, color=INK, font="Helvetica-Bold")

    # Zertifikatswarnung
    add_box(page, y=68 * mm, height=26 * mm, fill=ORANGE_TINT, stroke=ORANGE)
    add_text(page, MARGIN + 6 * mm, 87 * mm, "ZERTIFIKATSWARNUNG", size=11, color=ORANGE, font="Helvetica-Bold")
    add_lines(
        page,
        MARGIN + 6 * mm,
        80 * mm,
        [
            "Zeigt der Browser eine Zertifikatswarnung, ist die Stammzertifizierungsstelle",
            "noch nicht auf dem Gerät installiert - siehe Leitfaden.",
        ],
        size=9.5,
        leading=5.5 * mm,
        color=INK,
    )

    # Gerätehinweis
    add_box(page, y=36 * mm, height=26 * mm, fill=GREEN_TINT, stroke=GREEN)
    add_text(page, MARGIN + 6 * mm, 55 * mm, "KAMERA-SCAN NUR UNTER ANDROID", size=11, color=GREEN, font="Helvetica-Bold")
    add_lines(
        page,
        MARGIN + 6 * mm,
        48 * mm,
        [
            "Die Barcode-Erkennung über die Kamera funktioniert nur unter Android mit Chrome.",
            "Auf dem iPhone bleibt die manuelle Eingabe des Codes.",
        ],
        size=9.5,
        leading=5.5 * mm,
        color=INK,
    )

    add_lines(
        page,
        PAGE_WIDTH / 2,
        26 * mm,
        [
            f"Stand {SHEET_DATE}. Die Adresse ist an das WLAN gebunden und kann sich ändern -",
            "stimmt sie nicht mehr, muss dieses Blatt neu erzeugt werden.",
            "A4, bei 100 Prozent drucken.",
        ],
        size=9,
        leading=5.5 * mm,
        color=MUTED,
        anchor="middle",
    )
    return [page]


# --------------------------------------------------------------------------
# Bogen 2 - Simulationsbogen
# --------------------------------------------------------------------------


def build_simulation_sheet():
    """Baut den zweiseitigen Simulationsbogen für den Sammelauftrag."""
    used_symbologies = []
    page_one = new_page()

    add_header(
        page_one,
        "SIMULATIONSBOGEN LAGER 2",
        f"Sammelauftrag WH/OUT/00022 + 00025 + 00030 | Stand {SHEET_DATE}",
        y=262 * mm,
        height=23 * mm,
    )

    # Abgesetzter Kasten: dieser Bogen ersetzt das Regal.
    add_box(page_one, y=230 * mm, height=27 * mm, fill=RED_TINT, stroke=RED)
    add_text(page_one, MARGIN + 6 * mm, 250 * mm, "ES GIBT KEIN PHYSISCHES REGAL", size=12, color=RED, font="Helvetica-Bold")
    add_lines(
        page_one,
        MARGIN + 6 * mm,
        243.5 * mm,
        [
            "Lager 2 ist eine Demonstrationsdatenbank. Die hier genannten Lagerplätze existieren",
            "nicht als Regal. Dieser Bogen ersetzt den Rundgang: Code ausdrucken oder auf einem",
            "zweiten Bildschirm anzeigen und das Handy davorhalten - wie eine Entnahme aus dem Regal.",
        ],
        size=9,
        leading=5 * mm,
        color=INK,
    )

    add_text(page_one, MARGIN, 224 * mm, "1  ARTIKEL IN RUNDGANGSREIHENFOLGE", size=13, color=BLUE, font="Helvetica-Bold")
    add_text(
        page_one,
        MARGIN,
        218 * mm,
        "Die App sortiert die Halte nach Lagerplatzname - also genau in dieser Reihenfolge von oben nach unten.",
        size=8.5,
        color=MUTED,
    )

    card_height = 44 * mm
    card_gap = 4 * mm
    card_top = 213 * mm
    for index, stop in enumerate(PICK_STOPS):
        card_y = card_top - (index + 1) * card_height - index * card_gap
        used_symbologies.append(
            draw_pick_card(page_one, stop, number=index + 1, y=card_y, height=card_height)
        )

    add_text(
        page_one,
        PAGE_WIDTH / 2,
        22 * mm,
        "Seite 1 von 2 | A4, bei 100 Prozent drucken | Klartext unter dem Code entspricht exakt dem Scanwert",
        size=8,
        color=MUTED,
        anchor="middle",
    )

    # ------------------------------------------------------------------
    page_two = new_page()
    add_header(
        page_two,
        "SIMULATIONSBOGEN LAGER 2",
        "Kartonetiketten, Negativtest und erwartetes Ergebnis",
        y=266 * mm,
        height=19 * mm,
    )

    # Abschnitt 2 - Kartonetiketten
    add_box(page_two, y=128 * mm, height=134 * mm, fill=RED_TINT, stroke=RED)
    add_text(page_two, MARGIN + 6 * mm, 254 * mm, "2  KARTONETIKETTEN", size=13, color=RED, font="Helvetica-Bold")
    add_lines(
        page_two,
        MARGIN + 6 * mm,
        247.5 * mm,
        [
            "Diese Namen vergibt das System selbst, sobald der Sammelauftrag gestartet wird",
            "(Muster CLUSTER-B{Nummer}/{Auftrag}, Nummer nach aufsteigender Auftrags-ID).",
            "Sie gelten nur für genau diesen Sammelauftrag. Wird ein anderer gestartet, ändern sich",
            "die Namen und dieser Bogen muss neu erzeugt werden.",
        ],
        size=9,
        leading=5 * mm,
        color=INK,
    )

    label_height = 30 * mm
    label_gap = 3 * mm
    label_top = 228 * mm
    for index, carton in enumerate(CARTONS):
        label_y = label_top - (index + 1) * label_height - index * label_gap
        used_symbologies.append(
            draw_carton_label(page_two, carton, y=label_y, height=label_height)
        )

    # Abschnitt 3 - Negativtest
    add_box(page_two, y=62 * mm, height=62 * mm, fill=ORANGE_TINT, stroke=ORANGE)
    add_text(page_two, MARGIN + 6 * mm, 117 * mm, "3  NEGATIVTEST - MUSS ABGEWIESEN WERDEN", size=13, color=ORANGE, font="Helvetica-Bold")
    add_lines(
        page_two,
        MARGIN + 6 * mm,
        110.5 * mm,
        [
            "Beide Artikel gibt es wirklich in Lager 2, sie gehören aber nicht zu diesem Sammelauftrag.",
            "Genau diese Verwechslung passiert im Betrieb - die App MUSS beide zurückweisen.",
        ],
        size=9,
        leading=5 * mm,
        color=INK,
    )

    decoy_width = (CONTENT_WIDTH - 12 * mm - 5 * mm) / 2
    decoy_left = MARGIN + 6 * mm
    for index, decoy in enumerate(DECOYS):
        decoy_x = decoy_left + index * (decoy_width + 5 * mm)
        used_symbologies.append(
            draw_decoy_card(page_two, decoy, x=decoy_x, y=63 * mm, width=decoy_width, height=38 * mm)
        )

    # Abschnitt 4 - Erwartetes Ergebnis
    add_box(page_two, y=17 * mm, height=41 * mm, fill=GREEN_TINT, stroke=GREEN)
    add_text(page_two, MARGIN + 6 * mm, 51 * mm, "4  ERWARTETES ERGEBNIS", size=13, color=GREEN, font="Helvetica-Bold")
    for index, entry in enumerate(EXPECTED_RESULTS):
        row_y = 42 * mm - index * 6.5 * mm
        page_two.add(
            Rect(
                MARGIN + 7 * mm,
                row_y - 1 * mm,
                5 * mm,
                5 * mm,
                fillColor=WHITE,
                strokeColor=GREEN,
                strokeWidth=1.0,
            )
        )
        add_text(page_two, MARGIN + 15 * mm, row_y, entry, size=10, color=INK)

    add_text(
        page_two,
        PAGE_WIDTH / 2,
        11 * mm,
        "Seite 2 von 2 | A4, bei 100 Prozent drucken | Artikelcodes EAN-13, Kartonetiketten Code128",
        size=8,
        color=MUTED,
        anchor="middle",
    )
    return [page_one, page_two], used_symbologies


def draw_pick_card(page, stop, *, number: int, y: float, height: float) -> tuple:
    """Zeichnet eine Halt-Karte mit Barcode, Artikel und Kartonverteilung."""
    page.add(
        Rect(
            MARGIN,
            y,
            CONTENT_WIDTH,
            height,
            rx=3 * mm,
            ry=3 * mm,
            fillColor=WHITE,
            strokeColor=BLUE,
            strokeWidth=1.2,
        )
    )
    add_text(
        page,
        MARGIN + 6 * mm,
        y + height - 7 * mm,
        f"HALT {number}   |   {stop['location']}",
        size=12,
        color=BLUE,
        font="Helvetica-Bold",
    )
    add_text(page, MARGIN + 6 * mm, y + height - 17 * mm, stop["product"], size=14, color=INK, font="Helvetica-Bold")
    add_text(page, MARGIN + 6 * mm, y + height - 24 * mm, "Verteilung auf die Kartons:", size=8.5, color=MUTED)
    add_text(page, MARGIN + 6 * mm, y + height - 30 * mm, stop["split"], size=10.5, color=INK, font="Helvetica-Bold")

    barcode_center = MARGIN + CONTENT_WIDTH - 36 * mm
    symbology = draw_barcode(page, stop["barcode"], center_x=barcode_center, y=y + 13 * mm, height=18 * mm)
    add_text(
        page,
        barcode_center,
        y + 7 * mm,
        stop["barcode"],
        size=11,
        color=INK,
        font="Helvetica-Bold",
        anchor="middle",
    )
    add_text(
        page,
        barcode_center,
        y + 3 * mm,
        symbology_note(symbology),
        size=7.5,
        color=MUTED,
        anchor="middle",
    )
    return (stop["barcode"], symbology)


def draw_carton_label(page, carton, *, y: float, height: float) -> tuple:
    """Zeichnet ein Kartonetikett als Code128 mit Klartext."""
    page.add(
        Rect(
            MARGIN + 6 * mm,
            y,
            CONTENT_WIDTH - 12 * mm,
            height,
            rx=2 * mm,
            ry=2 * mm,
            fillColor=WHITE,
            strokeColor=RED,
            strokeWidth=1.2,
        )
    )
    center = PAGE_WIDTH / 2
    # Zuerst der Code samt weißer Unterlage, danach die Beschriftung darüber.
    symbology = draw_barcode(page, carton["value"], center_x=center, y=y + 8 * mm, height=14 * mm)
    add_text(
        page,
        MARGIN + 10 * mm,
        y + height - 5.5 * mm,
        f"{carton['label']} | Auftrag {carton['picking']}",
        size=9.5,
        color=RED,
        font="Helvetica-Bold",
    )
    add_text(page, center, y + 4 * mm, carton["value"], size=11, color=INK, font="Helvetica-Bold", anchor="middle")
    add_text(page, center, y + 1 * mm, symbology_note(symbology), size=7, color=MUTED, anchor="middle")
    return (carton["value"], symbology)


def draw_decoy_card(page, decoy, *, x: float, y: float, width: float, height: float) -> tuple:
    """Zeichnet eine Köder-Karte, die von der App abgewiesen werden muss."""
    page.add(
        Rect(x, y, width, height, rx=2 * mm, ry=2 * mm, fillColor=WHITE, strokeColor=ORANGE, strokeWidth=1.4)
    )
    symbology = draw_barcode(page, decoy["barcode"], center_x=x + width / 2, y=y + 10 * mm, height=13 * mm)
    add_text(page, x + width / 2, y + height - 6 * mm, "MUSS ABGEWIESEN WERDEN", size=9, color=ORANGE, font="Helvetica-Bold", anchor="middle")
    add_text(page, x + width / 2, y + height - 12 * mm, decoy["product"], size=11.5, color=INK, font="Helvetica-Bold", anchor="middle")
    add_text(page, x + width / 2, y + 6 * mm, decoy["barcode"], size=10.5, color=INK, font="Helvetica-Bold", anchor="middle")
    add_text(page, x + width / 2, y + 2.5 * mm, symbology_note(symbology), size=7, color=MUTED, anchor="middle")
    return (decoy["barcode"], symbology)


def symbology_note(symbology: str) -> str:
    """Beschriftet den Code sichtbar mit der verwendeten Symbologie."""
    return "EAN-13" if symbology == "EAN13" else "Code128"


# --------------------------------------------------------------------------
# Ausgabe
# --------------------------------------------------------------------------


def write_pages(pages, output: Path, title: str) -> None:
    """Schreibt eine Liste von Drawings als mehrseitiges PDF."""
    if output.suffix.lower() != ".pdf":
        raise ValueError("--output muss auf .pdf enden")
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas = pdf_canvas.Canvas(
        str(output),
        pagesize=A4,
        pageCompression=1,
        invariant=1,
    )
    canvas.setTitle(title)
    for page in pages:
        renderPDF.draw(page, canvas, 0, 0)
        canvas.showPage()
    canvas.save()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Startblatt und Simulationsbogen für den Handytest in Lager 2 erzeugen."
    )
    parser.add_argument(
        "--sheet",
        choices=("start", "simulation", "both"),
        default="both",
        help="Welcher Bogen erzeugt wird (Standard: beide)",
    )
    parser.add_argument("--output", type=Path, help="Zielpfad, nur bei einem einzelnen Bogen")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/demo-sheets"),
        help="Zielverzeichnis, wenn beide Bögen erzeugt werden",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Prüfziffern vor dem Zeichnen kontrollieren und Rückfälle melden.
    for value in [stop["barcode"] for stop in PICK_STOPS] + [decoy["barcode"] for decoy in DECOYS]:
        symbology = resolve_symbology(value)
        if symbology != "EAN13":
            print(f"WARNUNG: {value} hat keine gültige EAN-13-Prüfziffer -> gezeichnet als Code128")

    targets = []
    if args.sheet in ("start", "both"):
        target = args.output if args.sheet == "start" and args.output else args.output_dir / "handy-start.pdf"
        write_pages(build_start_sheet(), target, "Handy-Start Lager 2")
        targets.append(target)
    if args.sheet in ("simulation", "both"):
        target = args.output if args.sheet == "simulation" and args.output else args.output_dir / "simulationsbogen-lager2.pdf"
        pages, symbologies = build_simulation_sheet()
        write_pages(pages, target, "Simulationsbogen Lager 2")
        for value, symbology in symbologies:
            print(f"  {value}: {symbology_note(symbology)}")
        targets.append(target)

    for target in targets:
        print(f"Bogen erzeugt: {target}")


if __name__ == "__main__":
    main()
