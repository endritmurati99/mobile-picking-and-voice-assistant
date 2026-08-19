#!/usr/bin/env python3
"""Erzeugt den Kommissionierbogen als PDF -- im Fliesssatz, nicht auf Millimeter gesetzt.

Warum neu: die Vorgaengerfassung platzierte jeden Kasten, jeden Text und jeden
Barcode auf absoluten Millimeterkoordinaten. Sobald ein Datensatz eine Zeile
laenger wurde oder ein Karton dazukam, ueberlappte etwas -- am 19.08.2026 lief
der fuenfte Halt ueber den Seitenrand, die Fusszeile lag im Text und das vierte
Kartonetikett stand ausserhalb seines Rahmens. Ein Layout, das bei jeder
Datenaenderung nachgemessen werden muss, ist kaputt.

Deshalb: Inhalt als HTML mit Fliesssatz, Seitenumbrueche ueber CSS, gedruckt von
Chrome. Ueberlappen kann dabei nichts, weil nichts absolut positioniert ist.

Die Barcodes kommen als SVG aus ReportLab im Odoo-Container -- ein erprobter
Code128-Erzeuger, kein selbstgeschriebener. Als Vektor eingebettet skalieren sie
verlustfrei; die Modulbreite ist auf 0,52 mm gesetzt, weil darunter das
Abscannen vom Bildschirm (96 dpi) nachweislich scheitert.

Aufruf aus dem Projektwurzelverzeichnis:

    python3 infrastructure/scripts/generate-picking-sheet.py
    python3 infrastructure/scripts/generate-picking-sheet.py --output /tmp/probe.pdf
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import subprocess
import tempfile
from pathlib import Path

# --------------------------------------------------------------------------
# Stammdaten -- nur hier anpassen, wenn ein anderer Sammelauftrag abgedeckt
# werden soll. Alle Werte stammen aus `masterfischer_o19` (Instanz "Lager 1").
# --------------------------------------------------------------------------

TITLE = "Kommissionierbogen"
WAREHOUSE = "Lager 1"
ORDERS = ["WH/OUT/00047", "WH/OUT/00051", "WH/OUT/00053", "WH/OUT/00054"]
SHEET_DATE = "19.08.2026"

PWA_URL = "https://172.22.147.158/"
LOGIN_USER = "lena.lager"
LOGIN_PASSWORD = "admin"

STOPS = [
    {"location": "Regal B-01", "barcode": "4166960",
     "product": "Brick 2x2 blau", "split": "2 Stück in Karton 3"},
    {"location": "Regal B-02", "barcode": "6269088",
     "product": "Brick 2x2 dot blau Propeller", "split": "je 1 Stück in Karton 1, 2 und 4"},
    {"location": "Regal C-01", "barcode": "6294208",
     "product": "Flower hellblau", "split": "1 Stück in Karton 3"},
    {"location": "Regal C-02", "barcode": "343701",
     "product": "Brick 2x2 weiß", "split": "je 1 Stück in Karton 1, 2 und 4"},
    {"location": "Regal C-02", "barcode": "6096680",
     "product": "Brick Round 2x2x2 weiß", "split": "je 2 Stück in Karton 1, 2 und 4"},
]

CARTONS = [
    {"label": "Karton 1", "order": "WH/OUT/00047", "value": "CLUSTER-B1/WH/OUT/00047"},
    {"label": "Karton 2", "order": "WH/OUT/00051", "value": "CLUSTER-B2/WH/OUT/00051"},
    {"label": "Karton 3", "order": "WH/OUT/00053", "value": "CLUSTER-B3/WH/OUT/00053"},
    {"label": "Karton 4", "order": "WH/OUT/00054", "value": "CLUSTER-B4/WH/OUT/00054"},
]

DECOYS = [
    {"barcode": "343721", "product": "Brick 2x2 rot"},
    {"barcode": "343724", "product": "Brick 2x2 gelb"},
]

CHECKS = [
    "11 Positionen gebucht.",
    "Vier Aufträge abgeschlossen: WH/OUT/00047, 00051, 00053, 00054.",
    "Beide Kontrollcodes wurden abgewiesen.",
    "Kein Fehlschlag beim Kartonwechsel.",
]

# --------------------------------------------------------------------------
# Technik
# --------------------------------------------------------------------------

DOCKER = "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
ODOO_CONTAINER = "mobilepickingundvoiceassistant-odoo-1"
CHROME = "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"

# 0,52 mm Modulbreite in Punkt. Darunter reicht die Aufloesung eines
# Bildschirmfotos bei 96 dpi nicht mehr fuer eine sichere Erkennung.
MODULE_WIDTH_PT = 0.52 * 72 / 25.4

BARCODE_SCRIPT = '''
import base64, io, json, sys
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.graphics import renderPM
from reportlab.graphics.shapes import Drawing

values = json.load(sys.stdin)
out = {}
for value, bar_width, bar_height in values:
    barcode = createBarcodeDrawing(
        "Code128", value=value, barWidth=bar_width, barHeight=bar_height,
        humanReadable=False, quiet=True, lquiet=22, rquiet=22,
    )
    # Die Zeichenflaeche MUSS auf die tatsaechliche Ausdehnung des Barcodes
    # gesetzt werden. Ohne das schneidet ReportLab lange Werte an der
    # Vorgabebreite ab -- am 19.08.2026 kamen die 23-stelligen Kartoncodes so
    # als unlesbarer Stummel heraus, dekodierbar bei keiner Aufloesung.
    x0, y0, x1, y1 = barcode.getBounds()
    canvas = Drawing(x1 - x0, y1 - y0)
    barcode.translate(-x0, -y0)
    canvas.add(barcode)
    # Bei 600 dpi ist selbst die duennste Linie mehr als zwoelf Pixel breit;
    # die Rasterung fuegt dem Code damit keinen Fehler mehr zu.
    scale = 600 / 72.0
    buffer = io.BytesIO()
    renderPM.drawToFile(canvas, buffer, "PNG", dpi=600, bg=0xFFFFFF)
    out[value] = {
        "png": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "width_pt": x1 - x0,
        "height_pt": y1 - y0,
    }
print(json.dumps(out))
'''


QR_SCRIPT = '''
import base64, io, json, sys
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPM

url = json.load(sys.stdin)
widget = qr.QrCodeWidget(url, barLevel="M")
x0, y0, x1, y1 = widget.getBounds()
side = 600  # Punkte; bei 600 dpi ergibt das ein sehr grosszuegiges Raster
drawing = Drawing(side, side, transform=[side / (x1 - x0), 0, 0, side / (y1 - y0), -x0, -y0])
drawing.add(widget)
buffer = io.BytesIO()
renderPM.drawToFile(drawing, buffer, "PNG", dpi=300, bg=0xFFFFFF)
print(json.dumps(base64.b64encode(buffer.getvalue()).decode("ascii")))
'''


def build_qr(url: str) -> str:
    """QR-Code als eingebettetes PNG, Kantenlaenge spaeter per CSS."""
    result = subprocess.run(
        [DOCKER, "exec", "-i", ODOO_CONTAINER, "python3", "-c", QR_SCRIPT],
        input=json.dumps(url), capture_output=True, text=True, check=True, timeout=180,
    )
    return json.loads(result.stdout)


def build_barcodes(values: list[str], *, height_pt: float = 46.0) -> dict[str, tuple[str, float]]:
    """Liefert je Wert ein eingebettetes PNG und seine natuerliche Breite in mm."""
    # Das Skript geht als -c mit, die Werte ueber stdin. `docker cp` scheidet
    # aus: docker.exe laeuft unter Windows und kann WSL-Pfade nicht lesen.
    payload = json.dumps([[v, MODULE_WIDTH_PT, height_pt] for v in values])
    result = subprocess.run(
        [DOCKER, "exec", "-i", ODOO_CONTAINER, "python3", "-c", BARCODE_SCRIPT],
        input=payload, capture_output=True, text=True, check=True, timeout=300,
    )
    raw = json.loads(result.stdout)
    barcodes: dict[str, tuple[str, float]] = {}
    for value, entry in raw.items():
        width_mm = entry["width_pt"] * 25.4 / 72
        height_mm = entry["height_pt"] * 25.4 / 72
        tag = (
            f'<img class="code" alt="" src="data:image/png;base64,{entry["png"]}" '
            f'style="width:{width_mm:.2f}mm;height:{height_mm:.2f}mm">'
        )
        barcodes[value] = (tag, width_mm)
    return barcodes


CSS = """
@page { size: A4; margin: 12mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Arial, sans-serif; color: #16202b; margin: 0; font-size: 10pt; }
.sheet { page-break-after: always; }
.sheet:last-child { page-break-after: auto; }
.head { background: #1c3552; color: #fff; border-radius: 3mm; padding: 5mm 6mm; margin-bottom: 5mm; }
.head h1 { margin: 0; font-size: 17pt; letter-spacing: .3pt; }
.head p { margin: 1.5mm 0 0; font-size: 9.5pt; opacity: .92; }
.note { border: 1px solid #2f6f8f; background: #eef6fa; border-radius: 2.5mm;
        padding: 4mm 5mm; margin-bottom: 5mm; }
.note h2 { margin: 0 0 2mm; font-size: 11pt; color: #1d5b78; text-transform: uppercase; letter-spacing: .4pt; }
.note p { margin: 0; font-size: 9.5pt; line-height: 1.45; }
h2.section { font-size: 12.5pt; color: #1d5b78; margin: 0 0 3mm; text-transform: uppercase; letter-spacing: .4pt; }
h2.section.warn { color: #a8442a; }
.card { border: 1.2px solid #2f6f8f; border-radius: 2.5mm; padding: 4mm 5mm; margin-bottom: 4mm;
        display: flex; align-items: center; gap: 6mm; page-break-inside: avoid; }
.card.warn { border-color: #c2643f; background: #fdf4ef; }
.card .info { flex: 1 1 auto; min-width: 0; }
.card .eyebrow { font-size: 9pt; font-weight: 700; color: #1d5b78; margin-bottom: 1.5mm; }
.card.warn .eyebrow { color: #a8442a; }
.card .name { font-size: 13pt; font-weight: 700; margin-bottom: 1.5mm; }
.card .split { font-size: 10.5pt; font-weight: 600; }
.card .split span { display: block; font-size: 8.5pt; font-weight: 400; color: #5b6672; margin-bottom: .6mm; }
.bc { flex: 0 0 auto; text-align: center; }
.bc img.code { display: block; }
.bc .plain { font-family: "Consolas", monospace; font-size: 11pt; font-weight: 700; margin-top: 1.5mm; letter-spacing: .5pt; }
.label { border: 1.2px solid #c2643f; border-radius: 2.5mm; padding: 4mm 5mm 3mm; margin-bottom: 5mm;
         text-align: center; page-break-inside: avoid; }
.label .eyebrow { font-size: 9.5pt; font-weight: 700; color: #a8442a; margin-bottom: 2.5mm; text-align: left; }
.label img.code { display: block; margin: 0 auto; }
.label .plain { font-family: "Consolas", monospace; font-size: 12pt; font-weight: 700; margin-top: 2mm; letter-spacing: .5pt; }
ul.checks { list-style: none; margin: 0; padding: 0; }
ul.checks li { position: relative; padding: 0 0 0 8mm; margin-bottom: 3mm; font-size: 10.5pt; }
ul.checks li::before { content: ""; position: absolute; left: 0; top: .4mm;
                       width: 4.5mm; height: 4.5mm; border: 1.2px solid #2c7a5a; border-radius: 1mm; }
.start { text-align: center; }
.start .lead { font-size: 11pt; color: #40505f; margin: 6mm 0 5mm; }
.start img.qr { display: block; width: 72mm; height: 72mm; margin: 0 auto; }
.start .url { font-size: 17pt; font-weight: 700; margin: 5mm 0 1.5mm; font-family: "Consolas", monospace; }
.start .hint { font-size: 9pt; color: #6b7683; margin: 0 0 7mm; }
table.login { width: 90mm; margin: 0 auto 7mm; border-collapse: collapse; text-align: left; }
table.login th { font-weight: 400; color: #5b6672; font-size: 10pt; padding: 1.6mm 0; width: 32mm; }
table.login td { font-size: 13pt; font-weight: 700; padding: 1.6mm 0; }
.foot { margin-top: 6mm; padding-top: 2.5mm; border-top: 1px solid #c8ced8;
        font-size: 8pt; color: #6b7683; text-align: center; }
"""


def card(stop: dict, number: int, barcodes: dict) -> str:
    svg, _ = barcodes[stop["barcode"]]
    return f"""
    <div class="card">
      <div class="info">
        <div class="eyebrow">HALT {number} &nbsp;|&nbsp; {html.escape(stop['location'])}</div>
        <div class="name">{html.escape(stop['product'])}</div>
        <div class="split"><span>Verteilung auf die Kartons</span>{html.escape(stop['split'])}</div>
      </div>
      <div class="bc">{svg}<div class="plain">{html.escape(stop['barcode'])}</div></div>
    </div>"""


def build_start_html(qr_png: str) -> str:
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<title>Handy-Start {html.escape(WAREHOUSE)}</title><style>{CSS}</style></head><body>
<div class="sheet start">
  <div class="head"><h1>Handy-Start &ndash; {html.escape(WAREHOUSE)}</h1>
    <p>Kommissionier-App &nbsp;|&nbsp; Stand {SHEET_DATE}</p></div>
  <p class="lead">QR-Code mit der Handykamera scannen &ndash; nichts abtippen.</p>
  <img class="qr" alt="" src="data:image/png;base64,{qr_png}">
  <div class="url">{html.escape(PWA_URL)}</div>
  <p class="hint">Falls der QR-Code nicht gelesen wird: Adresse von Hand im Browser eingeben.</p>
  <table class="login">
    <tr><th>Benutzer</th><td>{html.escape(LOGIN_USER)}</td></tr>
    <tr><th>Passwort</th><td>{html.escape(LOGIN_PASSWORD)}</td></tr>
    <tr><th>Lager</th><td>{html.escape(WAREHOUSE)}</td></tr>
  </table>
  <div class="note" style="text-align:left">
    <h2>Zertifikatswarnung</h2>
    <p>Zeigt der Browser eine Zertifikatswarnung, ist die Stammzertifizierungsstelle noch nicht
       auf dem Gerät installiert. Der Weg dorthin steht in der Bedienanleitung, Abschnitt 1.</p>
  </div>
  <div class="note" style="text-align:left">
    <h2>Barcode scannen</h2>
    <p>Die Erkennung läuft über die Handykamera. Erkennt das Gerät einen Code einmal nicht,
       lässt er sich im Scanner-Fenster auch von Hand eingeben.</p>
  </div>
  <div class="foot">Die Adresse ist an das WLAN gebunden und kann sich ändern &ndash; stimmt sie
    nicht mehr, muss dieses Blatt neu erzeugt werden. A4, bei 100 Prozent drucken.</div>
</div>
</body></html>"""


def build_html(barcodes: dict) -> str:
    orders = " &middot; ".join(ORDERS)
    stops = "".join(card(s, i + 1, barcodes) for i, s in enumerate(STOPS))
    labels = "".join(
        f"""
    <div class="label">
      <div class="eyebrow">{html.escape(c['label'])} &nbsp;|&nbsp; Auftrag {html.escape(c['order'])}</div>
      {barcodes[c['value']][0]}
      <div class="plain">{html.escape(c['value'])}</div>
    </div>"""
        for c in CARTONS
    )
    decoys = "".join(
        f"""
    <div class="card warn">
      <div class="info">
        <div class="eyebrow">MUSS ABGEWIESEN WERDEN</div>
        <div class="name">{html.escape(d['product'])}</div>
        <div class="split"><span>Gehört zu keinem der vier Aufträge</span>Die App muss &bdquo;falscher Artikel&ldquo; melden</div>
      </div>
      <div class="bc">{barcodes[d['barcode']][0]}<div class="plain">{html.escape(d['barcode'])}</div></div>
    </div>"""
        for d in DECOYS
    )
    checks = "".join(f"<li>{html.escape(c)}</li>" for c in CHECKS)

    def head(subtitle: str) -> str:
        return (f'<div class="head"><h1>{html.escape(TITLE)} &ndash; {html.escape(WAREHOUSE)}</h1>'
                f'<p>{subtitle}</p></div>')

    def foot(page: int) -> str:
        return (f'<div class="foot">Seite {page} von 3 &nbsp;|&nbsp; A4, bei 100 Prozent drucken '
                f'&nbsp;|&nbsp; Klartext unter dem Code entspricht exakt dem Scanwert</div>')

    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<title>{html.escape(TITLE)} {html.escape(WAREHOUSE)}</title><style>{CSS}</style></head><body>

<div class="sheet">
  {head(f'Sammelauftrag {orders} &nbsp;|&nbsp; Stand {SHEET_DATE}')}
  <div class="note">
    <h2>So arbeiten Sie den Rundgang ab</h2>
    <p>Die Halte stehen in der Reihenfolge, in der die App sie anzeigt. An jedem Halt zuerst den
       Artikelcode scannen, danach den Karton, in den die Menge gehört. Sind mehrere Kartons
       genannt, wiederholt sich der Kartonschritt je Karton &ndash; der Artikel bleibt geprüft.</p>
  </div>
  <h2 class="section">1 &nbsp; Artikel in Rundgangsreihenfolge</h2>
  {stops}
  {foot(1)}
</div>

<div class="sheet">
  {head('Kartonetiketten')}
  <div class="note">
    <h2>2 &nbsp; Kartonetiketten</h2>
    <p>Diese Namen vergibt das System selbst, sobald der Sammelauftrag gestartet wird
       (Muster CLUSTER-B{{Nummer}}/{{Auftrag}}, Nummer nach aufsteigender Auftrags-ID).
       Sie gelten nur für genau diesen Sammelauftrag. Wird ein anderer gestartet, ändern sich
       die Namen und dieser Bogen muss neu erzeugt werden.</p>
  </div>
  {labels}
  {foot(2)}
</div>

<div class="sheet">
  {head('Kontrollcodes und Abschluss')}
  <h2 class="section warn">3 &nbsp; Kontrollcodes &ndash; müssen abgewiesen werden</h2>
  <div class="note">
    <p>Beide Artikel gibt es wirklich im Lager, sie gehören aber nicht zu diesem Sammelauftrag:
       gleiche Bauform, falsche Farbe. Genau diese Verwechslung passiert im Betrieb.</p>
  </div>
  {decoys}
  <h2 class="section" style="margin-top:8mm">4 &nbsp; Nach dem Rundgang prüfen</h2>
  <ul class="checks">{checks}</ul>
  {foot(3)}
</div>

</body></html>"""


def to_windows_path(path: Path) -> str:
    resolved = str(path.resolve())
    if not resolved.startswith("/mnt/"):
        raise SystemExit(f"FEHLER: {resolved} liegt nicht auf einem Windows-Laufwerk.")
    return f"{resolved[5].upper()}:{resolved[6:]}".replace("/", "\\")


def print_pdf(document: str, target: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".html", encoding="utf-8",
                                     dir=target.parent, delete=False) as handle:
        handle.write(document)
        html_path = Path(handle.name)
    try:
        subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={to_windows_path(target)}",
             "file:///" + to_windows_path(html_path).replace("\\", "/")],
            capture_output=True, text=True, timeout=180,
        )
    finally:
        html_path.unlink(missing_ok=True)
    if not target.exists() or target.stat().st_size == 0:
        raise SystemExit("FEHLER: Chrome hat kein PDF erzeugt.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Startblatt und Kommissionierbogen erzeugen.")
    parser.add_argument("--sheet", choices=("start", "picking", "both"), default="both")
    parser.add_argument("--output-dir", type=Path, default=Path("docs/testing"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.sheet in ("start", "both"):
        target = args.output_dir / "handy-start.pdf"
        print_pdf(build_start_html(build_qr(PWA_URL)), target)
        print(f"OK  {target}  ({target.stat().st_size // 1024} KB)")

    if args.sheet in ("picking", "both"):
        values = [s["barcode"] for s in STOPS] + [c["value"] for c in CARTONS] \
            + [d["barcode"] for d in DECOYS]
        barcodes = build_barcodes(values)
        for value, (_, width_mm) in sorted(barcodes.items(), key=lambda kv: -kv[1][1]):
            print(f"  {value:<26} {width_mm:6.1f} mm breit")
        target = args.output_dir / "kommissionierbogen-lager1.pdf"
        print_pdf(build_html(barcodes), target)
        print(f"OK  {target}  ({target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
