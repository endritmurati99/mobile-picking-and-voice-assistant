"""Bilder fuer die Qualitaetsbewertung aufbereiten.

Zwischen Odoo und dem Bildmodell liegen zwei Fallen, beide gemessen:

1. Der in Odoo gespeicherte MIME luegt. `api_create_alert` schrieb jedem
   Anhang hart `image/jpeg` an, auch wenn die Bytes PNG oder WebP sind -- das
   Hundefoto aus QA/0014 steht so in der Datenbank und ist WebP. Wer den Wert
   glaubt, laesst `validate_image` an jedem Bestandsanhang scheitern. Der Typ
   wird deshalb aus den Bytes bestimmt, nach demselben Grundsatz, nach dem auf
   den signierten Routen ein deklarierter Content-Type nie als Beweis gilt.

2. Ein grosses Bild sprengt das Kontextfenster des Modells. Ein Bildmodell
   zerlegt jedes Bild in Kacheln und zaehlt jede als Token; bei `qwen2.5vl`
   sind das 28x28 Pixel, ein 1920x1799-Foto ergibt also rund 4.400 Kacheln --
   mehr als die 4096 des Fensters, bevor ein Wort Prompt dazukommt. Gemessen:
   genau dieses Bild lief in HTTP 400, dasselbe auf 512 px verkleinert ging
   durch. Das Verkleinern ist Voraussetzung, keine Optimierung.

`MAX_EDGE` ist trotzdem eine Wahl und keine Naturkonstante. Zeigt sich 512 px
als zu grob fuer feine Schaeden, ist der Ausweg nicht ein groesseres Bild --
das trifft wieder auf dieselbe Grenze --, sondern das Foto in Kacheln zu
zerlegen und jede einzeln zu pruefen.
"""
from __future__ import annotations

import io

from PIL import Image

from app.services.binary_validation import BinaryValidationError, validate_image

MAX_EDGE = 512
_JPEG_QUALITY = 88

# Dieselbe Allowlist wie `binary_validation._IMAGE_FORMATS`. Sie steht hier
# noch einmal, weil dort das Format auf den MIME abgebildet wird, hier aber
# umgekehrt aus den Bytes geschlossen werden muss.
_FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


class MediaError(Exception):
    """Das Bild ist unbrauchbar.

    Der Aufrufer vermerkt den Grund im Klartext und macht ohne Bildbefund
    weiter -- er erfindet keinen.
    """


def sniff_mime(body: bytes) -> str:
    """MIME aus den Bytes, nicht aus dem, was jemand behauptet."""
    try:
        with Image.open(io.BytesIO(body)) as image:
            fmt = (image.format or "").upper()
    except Exception as exc:  # noqa: BLE001 - jedes Leseproblem ist dasselbe
        raise MediaError(f"Bild nicht lesbar: {exc}") from exc
    if fmt not in _FORMAT_TO_MIME:
        raise MediaError(f"Nicht unterstuetztes Bildformat: {fmt or 'unbekannt'}")
    return _FORMAT_TO_MIME[fmt]


def _flatten_onto_white(source: Image.Image) -> Image.Image:
    """Transparenz auf Weiss legen statt den Alphakanal wegzuwerfen.

    JPEG kennt keine Transparenz. Ein blosses `convert("RGB")` verwirft den
    Alphakanal, und transparente Flaechen werden dabei SCHWARZ -- das
    Meldefoto von QA/0011 ist ein Palettenbild mit Transparenz und haette so
    schwarze Flecken bekommen. Ein Schadensmodell sucht genau nach solchen
    Flaechen; wir wuerden ihm den Schaden also selbst hineinmalen. Weiss
    entspricht dem, was ein Betrachter im Bildbetrachter saehe.
    """
    if source.mode in ("RGBA", "LA") or "transparency" in source.info:
        rgba = source.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[3])
        return background
    return source.convert("RGB")


def prepare_image(body: bytes, *, max_edge: int = MAX_EDGE) -> bytes:
    """Prueft das Bild und gibt ein verkleinertes JPEG zurueck.

    Die Pruefung laeuft ueber `validate_image` und damit ueber genau dieselben
    Grenzen wie die signierten Binaerrouten: Bytezahl, Format-Allowlist,
    Pixelzahl, Einzelbild, strenger Container, vollstaendiger Dekodierlauf.
    Erst danach wird verkleinert -- ein Bild, das die Pruefung nicht besteht,
    soll auch nicht durch den Skalierer laufen.

    Kleinere Bilder bleiben unangetastet. Das Katalogbild ist 192x192; es
    hochzurechnen erfindet nur Pixel.
    """
    declared = sniff_mime(body)
    try:
        validate_image(body, declared_mime=declared)
    except BinaryValidationError as exc:
        raise MediaError(str(exc)) from exc

    with Image.open(io.BytesIO(body)) as source:
        image = _flatten_onto_white(source)
    if max(image.size) > max_edge:
        image.thumbnail((max_edge, max_edge), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
    return buffer.getvalue()
