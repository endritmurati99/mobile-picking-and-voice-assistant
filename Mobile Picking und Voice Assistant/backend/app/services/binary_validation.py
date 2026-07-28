"""Fail-closed Validierung roher Binaerdaten (Task 11).

Grundprinzip: ALLOWLIST, nicht Blocklist. Jeder Validator beschreibt, was
*erlaubt* ist, und lehnt alles andere ab -- eine unbekannte oder neu
erfundene Angriffsform ist damit automatisch verboten, ohne dass sie jemand
vorher aufgezaehlt haben muss. Konkret:

* Bild: genau drei Container (JPEG, PNG, WebP), genau ein Frame, exakt
  passender deklarierter MIME-Typ, harte Pixel- und Byte-Obergrenzen und ein
  vollstaendiger Dekodierdurchlauf, damit ein gueltiger Header mit kaputtem
  oder feindlichem Rumpf nicht durchkommt.
* PDF: erlaubte Versionen, erlaubte Katalog-, Seiten- und Annotations-Formen,
  erlaubte Stream-Filter -- plus eine vorgelagerte, benannte Erkennung der
  bekannten aktiven Konstrukte (JavaScript, eingebettete Dateien,
  Launch/URI-Aktionen), damit die Fehlermeldung sagt, WAS gefunden wurde,
  statt nur "nicht auf der Liste". Die Allowlist bleibt die eigentliche
  Absicherung; die benannte Erkennung ist nur die bessere Diagnose davor.
* ZPL: genau ein ^XA/^XZ-Dokument, reines druckbares ASCII und eine
  Positions-Allowlist -- JEDES Vorkommen von "^" oder "~" muss ein erlaubtes
  Kommando eroeffnen. Ein `findall`-basierter Filter wuerde `^ju`
  (Kleinschreibung, von vielen Firmwares akzeptiert) gar nicht erst sehen und
  damit stillschweigend durchlassen.

Dieses Modul ist der EINZIGE Ort, an dem Fremdformate dekodiert werden, und
es kennt weder FastAPI noch Odoo: es nimmt Bytes und gibt entweder ein
`ValidatedBinary` zurueck oder wirft `BinaryValidationError`. Es gibt keinen
Rueckgabewert, der "hat nicht ganz geklappt" bedeutet.
"""
from __future__ import annotations

import hashlib
import re
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from typing import Callable

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.generic import DictionaryObject, IndirectObject

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
MAX_PDF_PAGES = 20
MAX_PDF_OBJECTS = 20_000
MAX_FILENAME_LENGTH = 120


class BinaryValidationError(ValueError):
    """Abweisung. Traegt bewusst keine Angreiferdaten ausser Zeichen aus einer
    Allowlist (z. B. ein ZPL-Kommando), damit die Meldung gefahrlos in eine
    HTTP-Antwort oder ein Log wandern kann."""


@dataclass(frozen=True)
class ValidatedBinary:
    """Beweis einer BESTANDENEN Pruefung. Es gibt keinen Konstruktionsweg zu
    diesem Objekt, der an einem Validator vorbeifuehrt -- Aufrufer koennen
    `mime_type`/`extension` deshalb ohne weitere Pruefung verwenden."""

    mime_type: str
    size: int
    sha256: str
    extension: str


def _result(body: bytes, mime_type: str, extension: str) -> ValidatedBinary:
    return ValidatedBinary(
        mime_type=mime_type,
        size=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        extension=extension,
    )


# ---------------------------------------------------------------------------
# Dateinamen
# ---------------------------------------------------------------------------


def sanitize_filename(value: str) -> str:
    """Reduziert einen beliebigen Namen auf ein ASCII-Blatt ohne Pfadanteile.

    Drei Schritte, jeder gegen eine eigene Angriffsklasse:

    1. Backslashes werden zu Slashes und `PurePath(...).name` nimmt NUR das
       letzte Segment -- `../../etc/passwd` und `..\\windows\\cmd.exe`
       verlieren ihren Pfad, statt ihn maskiert zu behalten.
    2. Eine ASCII-Allowlist ersetzt alles andere. Damit verschwinden NUL,
       Zeilenumbrueche (Log-Injection), RTL-Override (U+202E, laesst
       "exe.jpg" wie "gpj.exe" aussehen) und Homoglyphen -- ohne dass diese
       Faelle einzeln aufgezaehlt werden muessten.
    3. Fuehrende/abschliessende Punkte und Unterstriche fallen weg, damit
       weder "." noch ".." noch eine versteckte Dotfile uebrig bleibt.

    Ein leeres Ergebnis wird zu "upload" -- diese Funktion gibt niemals einen
    leeren String, "." oder ".." zurueck.
    """
    leaf = PurePath(str(value).replace("\\", "/")).name
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", leaf).strip("._")
    return clean[:MAX_FILENAME_LENGTH].strip("._") or "upload"


# ---------------------------------------------------------------------------
# Bild
# ---------------------------------------------------------------------------

# Allowlist: Format -> (erlaubter deklarierter MIME-Typ, Dateiendung).
_IMAGE_FORMATS: dict[str, tuple[str, str]] = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}

# Pillow meldet Dekodierprobleme je nach Plugin sehr unterschiedlich.
# DecompressionBombError ist KEIN OSError -- ohne den expliziten Eintrag hier
# waere eine Bombe ein 500 statt einer Ablehnung.
_IMAGE_DECODER_ERRORS = (
    UnidentifiedImageError,
    Image.DecompressionBombError,
    Image.DecompressionBombWarning,
    OSError,
    ValueError,
    EOFError,
    SyntaxError,
)


def _strict_image_container(body: bytes, image_format: str) -> None:
    """Der Container muss GENAU die Datei sein -- kein Vorspann, kein Anhang.

    Decoder sind tolerant: sie ignorieren Bytes hinter dem Bildende, was
    Polyglots ("gueltiges PNG, danach ein PDF/PHP-Rumpf") erst moeglich
    macht. Hier wird deshalb zusaetzlich geprueft, dass Anfang UND Ende exakt
    zum Format gehoeren. Jedes Format der Allowlist hat hier einen Zweig --
    ein neues Format ohne Container-Regel faellt in `else` und wird
    abgelehnt, statt ungeprueft durchzulaufen.
    """
    if image_format == "JPEG":
        if not body.startswith(b"\xff\xd8\xff") or not body.endswith(b"\xff\xd9"):
            raise BinaryValidationError("JPEG is malformed or polyglot")
    elif image_format == "PNG":
        if not body.startswith(b"\x89PNG\r\n\x1a\n") or not body.endswith(
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        ):
            raise BinaryValidationError("PNG is malformed or polyglot")
    elif image_format == "WEBP":
        if (
            len(body) < 12
            or body[:4] != b"RIFF"
            or body[8:12] != b"WEBP"
            or int.from_bytes(body[4:8], "little") + 8 != len(body)
        ):
            raise BinaryValidationError("WebP is malformed or polyglot")
    else:  # pragma: no cover - durch die Format-Allowlist unerreichbar
        raise BinaryValidationError("Image container has no strict check")


def _inspect_image(body: bytes) -> tuple[str, int, int, int]:
    """Erster Durchlauf: Struktur lesen und pruefen, ohne Pixel zu erzeugen."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(body)) as image:
                image_format = str(image.format)
                width, height = image.size
                frames = int(getattr(image, "n_frames", 1))
                image.verify()
    except _IMAGE_DECODER_ERRORS as exc:
        raise BinaryValidationError("Image decoder rejected input") from exc
    return image_format, width, height, frames


def _decode_image_fully(body: bytes) -> None:
    """Zweiter Durchlauf: tatsaechlich dekodieren.

    `verify()` prueft nur die Struktur und macht das Bildobjekt danach
    unbrauchbar -- ein gueltiger Header mit kaputtem oder feindlichem Rumpf
    ueberlebt das. `load()` erzwingt den vollstaendigen Dekodierpfad, wieder
    unter der Bomben-Sperre.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(body)) as image:
                image.load()
    except _IMAGE_DECODER_ERRORS as exc:
        raise BinaryValidationError("Image decoder rejected input") from exc


def validate_image(body: bytes, *, declared_mime: str) -> ValidatedBinary:
    """Akzeptiert genau ein einzelbildiges JPEG/PNG/WebP innerhalb der Limits.

    Die Reihenfolge ist Absicht: Byte-Limit vor dem Decoder (eine 15-MiB-Datei
    wird nie geparst), Format-Allowlist vor dem MIME-Vergleich (ein GIF hoert
    "nicht erlaubt", nicht "falscher MIME"), Pixel- und Frame-Grenzen vor der
    Container-Pruefung, und der teure vollstaendige Dekodierdurchlauf ganz zum
    Schluss -- er laeuft nur fuer Daten, die alle billigen Pruefungen bereits
    bestanden haben.
    """
    if len(body) > MAX_IMAGE_BYTES:
        raise BinaryValidationError("Image exceeds 15 MiB")
    image_format, width, height, frames = _inspect_image(body)
    if image_format not in _IMAGE_FORMATS:
        raise BinaryValidationError("Only JPEG, PNG, and WebP are allowed")
    expected_mime, extension = _IMAGE_FORMATS[image_format]
    if declared_mime != expected_mime:
        raise BinaryValidationError("Declared MIME does not match image")
    if width * height > MAX_IMAGE_PIXELS:
        raise BinaryValidationError("Image exceeds 24 megapixels")
    if frames != 1:
        raise BinaryValidationError("Animated or multi-frame image is forbidden")
    _strict_image_container(body, image_format)
    _decode_image_fully(body)
    return _result(body, expected_mime, extension)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

_PDF_VERSIONS = tuple(
    f"%PDF-{version}".encode("ascii")
    for version in ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "2.0")
)

# Allowlist der Katalog-Schluessel. Alles Aktive haengt am Katalog:
# /Names (JavaScript, EmbeddedFiles), /OpenAction, /AA, /AcroForm (XFA),
# /Outlines (Aktionen). Nichts davon steht hier -- und alles, was noch
# erfunden wird, ebenso wenig.
_PDF_CATALOG_KEYS = {
    "/Type",
    "/Pages",
    "/Version",
    "/Lang",
    "/Metadata",
    "/MarkInfo",
    "/StructTreeRoot",
    "/ViewerPreferences",
    "/PageLayout",
    "/PageMode",
    "/Extensions",
}

# Allowlist der Seiten-Schluessel: reine Darstellung. /AA (Seitenaktionen)
# und /Annots (interaktive Elemente) fehlen bewusst -- Etiketten und
# Lieferscheine brauchen beides nicht.
_PDF_PAGE_KEYS = {
    "/Type",
    "/Parent",
    "/Resources",
    "/Contents",
    "/MediaBox",
    "/CropBox",
    "/BleedBox",
    "/TrimBox",
    "/ArtBox",
    "/Rotate",
    "/Group",
    "/StructParents",
    "/UserUnit",
    "/Tabs",
}

_PDF_PAGES_NODE_KEYS = {"/Type", "/Kids", "/Count", "/Parent", "/MediaBox", "/Resources", "/Rotate"}

# Allowlist der Stream-Filter: nur verlustfreie/Bild-Dekodierer, kein /Crypt.
_PDF_FILTERS = {
    "/FlateDecode",
    "/LZWDecode",
    "/ASCII85Decode",
    "/ASCIIHexDecode",
    "/RunLengthDecode",
    "/DCTDecode",
    "/CCITTFaxDecode",
}

# Benannte aktive Konstrukte. NICHT die Absicherung -- die liegt in den
# Allowlists oben -- sondern die bessere Fehlermeldung davor.
_PDF_ACTION_MESSAGES = {
    "/JavaScript": "PDF JavaScript is forbidden",
    "/Launch": "PDF launch actions are forbidden",
    "/GoToR": "PDF remote go-to actions are forbidden",
    "/GoToE": "PDF embedded go-to actions are forbidden",
    "/URI": "PDF URI actions are forbidden",
    "/SubmitForm": "PDF form submission is forbidden",
    "/ImportData": "PDF data import is forbidden",
    "/Movie": "PDF movie actions are forbidden",
    "/Sound": "PDF sound actions are forbidden",
    "/Rendition": "PDF rendition actions are forbidden",
    "/SetOCGState": "PDF optional-content actions are forbidden",
}


def _pdf_nodes(root):
    """Alle erreichbaren Dictionaries ab `root`, zyklensicher und gedeckelt.

    Der Zaehler ist kein Feinschliff: ein PDF mit Millionen kreuzverlinkter
    Objekte waere sonst ein CPU-Verbrauchsangriff auf den Validator selbst.
    """
    stack = [root]
    seen_objects: set[int] = set()
    visited = 0
    while stack:
        value = stack.pop()
        if isinstance(value, IndirectObject):
            if value.idnum in seen_objects:
                continue
            seen_objects.add(value.idnum)
            try:
                value = value.get_object()
            except Exception as exc:
                raise BinaryValidationError("PDF parser rejected input") from exc
        if isinstance(value, DictionaryObject):
            visited += 1
            if visited > MAX_PDF_OBJECTS:
                raise BinaryValidationError("PDF object graph is too large")
            yield value
            stack.extend(value.values())
        elif isinstance(value, (list, tuple)):
            stack.extend(value)


def _reject_active_pdf_constructs(node: DictionaryObject) -> None:
    if "/JS" in node or "/JavaScript" in node:
        raise BinaryValidationError("PDF JavaScript is forbidden")
    if "/EmbeddedFiles" in node or "/EmbeddedFile" in node:
        raise BinaryValidationError("PDF embedded files are forbidden")
    node_type = str(node.get("/Type", ""))
    if node_type in ("/Filespec", "/EmbeddedFile"):
        raise BinaryValidationError("PDF embedded files are forbidden")
    if node_type == "/RichMedia" or "/RichMediaContent" in node:
        raise BinaryValidationError("PDF rich media is forbidden")
    message = _PDF_ACTION_MESSAGES.get(str(node.get("/S", "")))
    if message:
        raise BinaryValidationError(message)


def _check_pdf_filters(node: DictionaryObject) -> None:
    raw = node.get("/Filter")
    if raw is None:
        return
    if isinstance(raw, IndirectObject):
        raw = raw.get_object()
    names = raw if isinstance(raw, (list, tuple)) else [raw]
    for name in names:
        if str(name) not in _PDF_FILTERS:
            raise BinaryValidationError("PDF stream filter is not allowed")


def _check_pdf_shape(node: DictionaryObject) -> None:
    """Allowlist je nach Knotentyp. Unbekannte Typen werden nicht geprueft --
    sie sind ueber den Katalog gar nicht erreichbar, weil dessen eigene
    Allowlist nur /Pages als Einstieg in den Baum zulaesst."""
    node_type = str(node.get("/Type", ""))
    if node_type == "/Page":
        unexpected = sorted(str(key) for key in node.keys() if str(key) not in _PDF_PAGE_KEYS)
        if unexpected:
            raise BinaryValidationError(f"PDF page key is not allowed: {unexpected[0]}")
    elif node_type == "/Pages":
        unexpected = sorted(
            str(key) for key in node.keys() if str(key) not in _PDF_PAGES_NODE_KEYS
        )
        if unexpected:
            raise BinaryValidationError(f"PDF page tree key is not allowed: {unexpected[0]}")
    _check_pdf_filters(node)


def validate_pdf(body: bytes) -> ValidatedBinary:
    """Akzeptiert ein unverschluesseltes, rein darstellendes PDF <= 20 Seiten.

    Reihenfolge wie beim Bild: Byte-Limit und Magic vor dem Parser, danach
    Verschluesselung und Seitenzahl (beides billig), dann der Objektgraph.
    """
    if len(body) > MAX_DOCUMENT_BYTES:
        raise BinaryValidationError("PDF exceeds 10 MiB")
    if not body.startswith(_PDF_VERSIONS):
        raise BinaryValidationError("PDF magic or version is not allowed")
    _reject_trailing_pdf_bytes(body)
    try:
        reader = PdfReader(BytesIO(body), strict=True)
    except Exception as exc:
        raise BinaryValidationError("PDF parser rejected input") from exc
    # Vor jedem weiteren Zugriff: auf einem verschluesselten Dokument wirft
    # schon `reader.pages` -- die Ablehnung muss "Encrypted" heissen und darf
    # nicht als generischer Parserfehler erscheinen.
    if reader.is_encrypted:
        raise BinaryValidationError("Encrypted PDF is forbidden")
    try:
        page_count = len(reader.pages)
        catalog = reader.trailer["/Root"]
    except Exception as exc:
        raise BinaryValidationError("PDF parser rejected input") from exc
    if page_count > MAX_PDF_PAGES:
        raise BinaryValidationError("PDF exceeds 20 pages")
    if isinstance(catalog, IndirectObject):
        catalog = catalog.get_object()
    if not isinstance(catalog, DictionaryObject):
        raise BinaryValidationError("PDF parser rejected input")

    # 1. Benannte aktive Konstrukte im gesamten erreichbaren Graphen. Laeuft
    #    VOR der Katalog-Allowlist, damit ein JavaScript-PDF "JavaScript"
    #    hoert und nicht das vagere "catalog key is not allowed: /Names".
    for node in _pdf_nodes(catalog):
        _reject_active_pdf_constructs(node)
    # 2. Die eigentliche Absicherung: Allowlist des Katalogs ...
    unexpected = sorted(str(key) for key in catalog.keys() if str(key) not in _PDF_CATALOG_KEYS)
    if unexpected:
        raise BinaryValidationError(f"PDF catalog key is not allowed: {unexpected[0]}")
    # 3. ... und der Formen darunter.
    for node in _pdf_nodes(catalog):
        _check_pdf_shape(node)
    return _result(body, "application/pdf", "pdf")


def _reject_trailing_pdf_bytes(body: bytes) -> None:
    """Nach dem letzten %%EOF darf nur Whitespace stehen.

    Der Parser ignoriert alles danach -- genau darauf beruhen PDF-Polyglots
    und angehaengte Nutzlasten.
    """
    marker = body.rfind(b"%%EOF")
    if marker < 0:
        raise BinaryValidationError("PDF has no %%EOF marker")
    if body[marker + len(b"%%EOF") :].strip(b"\r\n\t ") != b"":
        raise BinaryValidationError("PDF has bytes after %%EOF: malformed or polyglot")


# ---------------------------------------------------------------------------
# ZPL
# ---------------------------------------------------------------------------

_ZPL_COMMAND = re.compile(r"[\^~][A-Z@][A-Z0-9@]?", re.ASCII)
_ZPL_ALLOWED = {
    "^XA", "^XZ", "^FO", "^FD", "^FS", "^A", "^A0", "^BC", "^BQ",
    "^BY", "^CI", "^PW", "^LL", "^LH",
}
# Druckbares ASCII plus Zeilenumbrueche. Alles andere (NUL, ESC, ...) kann
# auf einem Zebra-Drucker eine eigene Kommandoebene oeffnen.
_ZPL_TEXT = re.compile(r"\A[\x20-\x7e\r\n]*\Z", re.ASCII)


def validate_zpl(body: bytes) -> ValidatedBinary:
    """Akzeptiert genau EIN ^XA/^XZ-Etikett aus Kommandos der Allowlist.

    Der Scan laeuft ueber POSITIONEN, nicht ueber Treffer: jedes Vorkommen
    von "^" oder "~" muss ein erlaubtes Kommando eroeffnen. Ein
    `findall`-Filter wuerde `^ju` gar nicht als Kommando erkennen und
    stillschweigend durchlassen -- viele Firmwares fuehren es trotzdem aus.
    """
    if len(body) > MAX_DOCUMENT_BYTES:
        raise BinaryValidationError("ZPL exceeds 10 MiB")
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError as exc:
        raise BinaryValidationError("ZPL must be ASCII") from exc
    if not _ZPL_TEXT.fullmatch(text):
        raise BinaryValidationError("ZPL contains control characters")
    if (
        not text.startswith("^XA")
        or not text.endswith("^XZ")
        or text.count("^XA") != 1
        or text.count("^XZ") != 1
    ):
        raise BinaryValidationError("ZPL requires exactly one ^XA/^XZ document")
    for position, character in enumerate(text):
        if character not in "^~":
            continue
        if character == "~":
            raise BinaryValidationError("ZPL tilde commands are forbidden")
        match = _ZPL_COMMAND.match(text, position)
        if match is None:
            raise BinaryValidationError("ZPL command is malformed")
        command = match.group()
        if command not in _ZPL_ALLOWED:
            raise BinaryValidationError(f"ZPL command is not allowed: {command}")
    return _result(body, "application/zpl", "zpl")


# ---------------------------------------------------------------------------
# Artefakt-Dispatch
# ---------------------------------------------------------------------------

# Allowlist der Artefaktarten: Art -> (erlaubter deklarierter MIME-Typ,
# Validator). Es gibt keinen zweiten Weg zu einem Validator; die Route ruft
# ausschliesslich `validate_artifact`, damit Art, deklarierter Typ und
# tatsaechlicher Inhalt nicht an drei Stellen unabhaengig geprueft werden.
_ARTIFACT_KINDS: dict[str, tuple[str, Callable[[bytes], ValidatedBinary]]] = {
    "pdf": ("application/pdf", validate_pdf),
    "zpl": ("application/zpl", validate_zpl),
}

ARTIFACT_KINDS = frozenset(_ARTIFACT_KINDS)


def validate_artifact(kind: str, body: bytes, *, declared_mime: str) -> ValidatedBinary:
    """Prueft Art, deklarierten Typ und tatsaechlichen Inhalt in einem Zug.

    Die Art wird exakt verglichen (kein `lower()`, kein `strip()`): "PDF" ist
    nicht "pdf", damit Gross-/Kleinschreibung nicht zu zwei verschiedenen
    Artefakt-Referenzen fuer dieselbe Datei fuehrt. `kind` wird nie in die
    Meldung uebernommen -- der Wert kommt aus dem URL-Pfad.
    """
    entry = _ARTIFACT_KINDS.get(kind) if isinstance(kind, str) else None
    if entry is None:
        raise BinaryValidationError("Artifact kind is not allowed")
    expected_mime, validator = entry
    if declared_mime != expected_mime:
        raise BinaryValidationError("Declared MIME does not match artifact kind")
    return validator(body)
