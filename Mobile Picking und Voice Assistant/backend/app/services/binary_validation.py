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
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from typing import Callable

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.filters import ASCII85Decode, ASCIIHexDecode
from pypdf.generic import DictionaryObject, IndirectObject, StreamObject

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
MAX_PDF_PAGES = 20
MAX_PDF_OBJECTS = 20_000
# Zweiter Deckel derselben Art, auf die Schritte durch Arrays und
# Referenzketten. `MAX_PDF_OBJECTS` deckelt nur die Dictionaries; ein
# Angreifer koennte sonst 20.000 Dictionaries auf dieselbe lange Kette
# indirekter Arrays zeigen lassen und ein Kreuzprodukt erzwingen, ohne einen
# einzigen zusaetzlichen Knoten. Reichlich bemessen: ein echtes
# 20-Seiten-Dokument braucht einige Tausend Schritte.
MAX_PDF_GRAPH_STEPS = 16 * MAX_PDF_OBJECTS
# Gesamtbudget fuer ALLE dekomprimierten Streams eines PDF zusammen. Ein
# 10-MiB-PDF darf sich damit gut dreifach entfalten -- eine Bombe, die aus
# 200 KB 200 MB macht, nicht.
MAX_PDF_EXPANDED_BYTES = 32 * 1024 * 1024
_INFLATE_STEP_BYTES = 1024 * 1024
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

# Allowlist der Stream-Filter. Bewusst KLEINER als die Menge der zulaessigen
# PDF-Filter -- ein Filter steht hier nur, wenn seine Expansion GEBUNDEN
# geprueft werden kann:
#
# * /LZWDecode und /RunLengthDecode expandieren stark; ich baue fuer sie
#   keinen gebundenen Dekodierer.
# * /DCTDecode und /CCITTFaxDecode sind Bildcodecs. Ihre Ausgabe laesst sich
#   nicht aus dem Stream ableiten, und die frueher hier benutzten DEKLARIERTEN
#   /Width und /Height sind wertlos: ein Stream darf 1x1 behaupten und
#   Codecdaten fuer ein riesiges Bild tragen. Sie ohne Dekodierung zu
#   akzeptieren war ein Loch im Expansionsbudget -- also fliegen sie raus.
# * /Crypt ohnehin nicht.
#
# FOLGE, bewusst in Kauf genommen: ein PDF mit eingebettetem JPEG oder
# CCITT-Fax wird abgelehnt. Etiketten und Lieferscheine sind Text, Vektor und
# Barcode; wer Rasterbilder braucht, kodiert sie /FlateDecode (gebunden
# geprueft). Sollte das spaeter nicht reichen, ist der richtige Weg eine
# Pillow-gestuetzte Pruefung der INTRINSISCHEN Bildmasse, nicht die Rueckkehr
# zu den deklarierten.
_PDF_FILTERS = {
    "/FlateDecode",
    "/ASCII85Decode",
    "/ASCIIHexDecode",
}
# Diese beiden expandieren nie ueber ihre Eingabelaenge hinaus.
_PDF_NON_EXPANDING_FILTERS = {"/ASCII85Decode", "/ASCIIHexDecode"}

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


# Inline-Bilder leben INNERHALB eines Inhaltsstroms (BI ... ID <daten> EI) und
# werden nie zu Stream-Objekten. Der Objektgraph mit seiner Filter-Allowlist und
# seinem Expansionsbudget sieht sie deshalb nie: ein Inline-Bild traegt seinen
# eigenen abgekuerzten Filter (/F /DCT) und seine eigenen /W und /H, und ein
# 586-Byte-PDF darf so 65535x65535 behaupten.
#
# Unter der geltenden Politik -- ein Filter ist nur erlaubt, wenn seine
# Expansion GEBUNDEN geprueft werden kann -- werden Inline-Bilder rundheraus
# abgelehnt. Sie spaeter wieder zuzulassen hiesse: den Inhaltsstrom dekodieren
# und die INTRINSISCHEN Bildmasse pruefen. Es darf NIE heissen, den
# deklarierten /W und /H zu glauben -- das ist genau der Fehler, an dem
# /DCTDecode und /CCITTFaxDecode schon einmal gescheitert sind.
#
# "BI" muss als OPERATOR erkannt werden, nicht als Teilzeichenkette: ein
# Lieferschein mit dem Wort "KABINE" ist kein Inline-Bild. Der Operator steht
# deshalb am Strom-/Zeilenanfang oder hinter einem Trenner, und ihm folgt ein
# Schluesselname, ein Array, ein Dictionary oder ein Kommentar.
#
# Die Trennerklassen folgen der PDF-SPEZIFIKATION -- nicht Pythons `\s` und
# nicht einer handgeschriebenen Zeichenliste. Beide Tabellen stehen deshalb
# als benannte Konstanten hier und werden in die Regex EINGESETZT: eine
# Abweichung von der Spezifikation muss an dieser einen Stelle sichtbar sein.
#
# ISO 32000-1 Tabelle 1 (Whitespace): NUL 0x00, TAB 0x09, LF 0x0A, FF 0x0C,
# CR 0x0D, SP 0x20. Pythons `\s` fuer Bytes ist [ \t\n\r\f\v]: NUL fehlt dort,
# dafuer ist VT 0x0B enthalten, das PDF gar nicht als Whitespace kennt. Genau
# daran scheiterte die erste Fassung -- `q\x00BI /W 65535 ...` tokenisiert
# jeder konforme Renderer wie `q BI ...`.
_PDF_WHITESPACE = b"\x00\x09\x0a\x0c\x0d\x20"
# ISO 32000-1 Tabelle 2 (Delimiter). Sie beenden ein Token ebenso.
_PDF_DELIMITERS = b"()<>[]{}/%"
# VT 0x0B ist KEIN PDF-Whitespace, bleibt aber in der Klasse: mehr fangen ist
# erlaubt, weniger nicht.
_NON_PDF_WHITESPACE_KEPT = b"\x0b"

# Welche Delimiter duerfen VOR "BI" stehen, damit "BI" noch ein Operator sein
# kann?
#
#   ) > ]  schliessen String, Hex-String/Dictionary und Array; danach beginnt
#          wieder ein Token.
#   { }    sind Delimiter des Inhaltsstrom-Lexers. "q}BI /W ..." zerfaellt in
#          q, }, BI -- ein Interpreter fuehrt das Inline-Bild aus. Diese
#          beiden fehlten und waren die zweite Luecke derselben Wurzel:
#          Tabelle 2 war nie aufgezaehlt worden.
#
# Bewusst NICHT aufgenommen; nach ihnen ist "BI" nachweislich Text und nie ein
# Operator, und ihre Aufnahme wuerde gueltige Dokumente ablehnen:
#
#   %  danach ist der Rest der Zeile Kommentar.
#   (  danach steht Zeichenkettentext -- "(BI 42)" ist ein Lieferscheintext.
#   /  danach steht ein Name.
#   <  danach steht ein Hex-String oder ein Dictionary-Schluessel.
#   [  danach steht ein Array-Element; ein nacktes "BI" darin ist ungueltig.
_INLINE_IMAGE_PREFIX_DELIMITERS = b")>]{}"
# Nach dem Operator folgt das Bild-Dictionary: Name, Array, Dictionary oder
# Kommentar. Die uebrigen Delimiter fehlen bewusst -- ein konformes
# Inline-Bild-Dictionary kann nicht mit ihnen beginnen, "BI)" oder "BI}" ist
# also nie ein zeichenbares Bild.
_INLINE_IMAGE_SUFFIX_DELIMITERS = b"/[<%"

assert set(_INLINE_IMAGE_PREFIX_DELIMITERS) <= set(_PDF_DELIMITERS)
assert set(_INLINE_IMAGE_SUFFIX_DELIMITERS) <= set(_PDF_DELIMITERS)
_INLINE_IMAGE_OPERATOR = re.compile(
    b"(?:^|["
    + re.escape(_PDF_WHITESPACE + _NON_PDF_WHITESPACE_KEPT + _INLINE_IMAGE_PREFIX_DELIMITERS)
    + b"])BI["
    + re.escape(_PDF_WHITESPACE + _NON_PDF_WHITESPACE_KEPT + _INLINE_IMAGE_SUFFIX_DELIMITERS)
    + b"]"
)
# Laengster moeglicher Treffer (4 Bytes) minus eins: so viele Bytes muessen
# beim schrittweisen Scannen vom vorigen Block mitgenommen werden, damit ein
# "BI", das auf der Blockgrenze zerfaellt, trotzdem gesehen wird. Genauer:
# `carry` traegt die letzten Bytes des letzten INFLATE-BLOCKS, nicht des
# bisherigen Stroms -- bei `_INFLATE_STEP_BYTES` = 1 MiB ist jeder Block weit
# groesser als 3 Bytes, der Unterschied ist also unerreichbar. Das "^" der
# Regex verankert ausserdem am Anfang jedes `carry + plain`-Puffers, nicht am
# Stromanfang; das kann nur zu frueh anschlagen (wenn `carry` leer ist), nie
# zu spaet.
_INLINE_IMAGE_CARRY = 3


def _reject_inline_images(content: bytes) -> None:
    if _INLINE_IMAGE_OPERATOR.search(content):
        raise BinaryValidationError(
            "PDF contains an inline image; artifact PDFs must use bounded "
            "FlateDecode stream objects"
        )


def _reject_inline_images_outside_streams(body: bytes) -> None:
    """Derselbe Scan fuer Phase 1, aber OHNE die Stream-Nutzdaten.

    Warum das sicher ist: Phase 1 ist fuer diese Abwehr nicht tragend. Jeder
    Strom, den sie im Klartext saehe, wird in Phase 3 ohnehin gescannt (Zweig
    "kein Filter"), und ein Strom, den Phase 3 nicht scannt, ist nachweislich
    kein Inhalt (siehe `_exempt_raster_idnums`).

    Diese Vorbedingung war zweimal FALSCH, waehrend sie hier behauptet wurde:
    ein befreiter Strom mit unkomprimiertem Inhalt war in beiden Phasen
    unsichtbar (A2u bei 879037f, A5 bei 0e58053). Beide Male lag die Ursache in
    der Befreiung, nicht im Hebel, und beide Male war der Graph unvollstaendig.
    Sie wird deshalb nicht mehr nur behauptet, sondern geprueft, und zwar gegen
    eine vom Modul UNABHAENGIGE Kantenliste:
    `test_every_stream_phase_three_skips_is_provably_not_content`.

    Phase 1 darf deshalb LOCKER
    sein -- und muss es sein, denn sie laeuft ueber die komprimierten Bytes
    von Rasterbildern. Das Vier-Byte-Muster trifft dort rein zufaellig mit
    rund 3e-8 pro Byte; ein 200-KB-Raster wuerde so etwa eines von 160
    voellig gueltigen Dokumenten grundlos ablehnen.

    Wer die Schluesselwoerter faelscht, laesst Phase 1 nur MEHR ueberspringen
    -- und alles Uebersprungene sieht Phase 3. Der Sicherheitspreis ist null.

    Ein einziger linearer Durchlauf, kein Parser, keine Dekompression: die
    Phasenordnung bleibt unberuehrt.
    """
    position = 0
    region_start = 0
    while True:
        start = body.find(b"stream", position)
        if start < 0:
            break
        if body[max(0, start - 3) : start] == b"end":
            # "endstream" enthaelt "stream" -- das eroeffnet keine Nutzdaten.
            position = start + 6
            continue
        _reject_inline_images(body[region_start : start + 6])
        end = body.find(b"endstream", start + 6)
        if end < 0:
            # Unabgeschlossener Strom: der Rest der Datei sind Nutzdaten.
            return
        region_start = end
        position = end + 9
    _reject_inline_images(body[region_start:])


def _pdf_nodes(root):
    """Alle erreichbaren Dictionaries ab `root`, zyklensicher und gedeckelt.

    Geliefert wird `(dictionary, idnum)`; `idnum` ist die Objektnummer, ueber
    die der Knoten erreicht wurde, oder None bei einem direkten Objekt. Die
    Nummer ist die einzige faelschungssichere Identitaet eines Streams -- sie
    wird gebraucht, um Inhaltsstroeme von Rasterbildern zu unterscheiden.

    Diese Funktion ist bewusst nur noch eine SICHT auf `_pdf_walk`. Sie hatte
    einmal einen eigenen Durchlauf, und der lief ueber Arrays, waehrend
    `_pdf_reference_map` das nicht tat -- ein indirektes Array unter /Contents
    war fuer die Kantenbuchhaltung unsichtbar und der Strom darin bekam eine
    Befreiung, die ein Interpreter durch Ausfuehren widerlegt. Zwei
    Erreichbarkeitsbegriffe koennen auseinanderlaufen; einer kann es nicht.
    """
    for record in _pdf_walk(root):
        if record[0] != _PDF_NODE:
            continue
        _, key, node = record
        kind, ident = key
        yield node, (ident if kind == "idnum" else None)


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


def _bounded_inflate(data: bytes, budget: int, *, scan: bool = True) -> int:
    """Dekomprimiert einen Flate-Stream und meldet die erzeugte Byte-Menge,
    OHNE sie je vollstaendig im Speicher zu halten.

    Der Kern der Bombenabwehr: `decompress(..., max_length)` liefert
    hoechstens `max_length` Bytes und legt den Rest in `unconsumed_tail`. Es
    wird also in 1-MiB-Schritten dekodiert und nach jedem Schritt gegen das
    Budget geprueft -- eine 200-KB-Datei, die sich auf 200 MB entfaltet,
    fliegt nach wenigen Schritten raus, statt vorher den Speicher zu fuellen.

    Der Inline-Bild-Scan laeuft aus genau demselben Grund HIER, Schritt fuer
    Schritt, und nicht beim Aufrufer auf dem fertigen Klartext: den fertigen
    Klartext gibt es bewusst nie am Stueck. `carry` traegt die letzten Bytes
    jedes Schritts in den naechsten, damit ein "BI" auf der Schrittgrenze
    nicht zerfaellt.
    """
    decompressor = zlib.decompressobj()
    produced = 0
    chunk = data
    carry = b""
    try:
        while True:
            plain = decompressor.decompress(chunk, _INFLATE_STEP_BYTES)
            if scan:
                _reject_inline_images(carry + plain)
                carry = plain[-_INLINE_IMAGE_CARRY:]
            produced += len(plain)
            if produced > budget:
                return produced
            if decompressor.eof:
                return produced
            chunk = decompressor.unconsumed_tail
            if not chunk:
                # Eingabe erschoepft, aber der Strom endete nie sauber.
                raise BinaryValidationError("PDF stream is truncated")
    except zlib.error as exc:
        raise BinaryValidationError("PDF stream is not decodable") from exc


_NON_EXPANDING_DECODERS: dict[str, Callable[[bytes], bytes]] = {
    "/ASCII85Decode": lambda data: bytes(ASCII85Decode.decode(data)),
    "/ASCIIHexDecode": lambda data: bytes(ASCIIHexDecode.decode(data)),
}
assert set(_NON_EXPANDING_DECODERS) == _PDF_NON_EXPANDING_FILTERS


# Kanten-Etiketten, die KEIN Dictionary-Schluessel sind. Ein PDF-Name beginnt
# immer mit "/", diese Sentinels bewusst nicht -- sie koennen deshalb mit
# keinem echten Schluessel kollidieren, und "ist ein Schluessel" ist an
# `startswith("/")` ablesbar.
_ARRAY_ELEMENT_LABEL = "<array element>"
_ROOT_LABEL = "<root>"


def _node_identity(value):
    """Faelschungssichere Identitaet eines Knotens fuer die Kantenbuchhaltung.

    Indirekte Objekte werden ueber die OBJEKTNUMMER gefuehrt, nicht ueber
    `id()`. `get_object()` darf bei einem Cache-Miss ein zweites Python-Objekt
    fuer dasselbe PDF-Objekt liefern; eine Identitaetspruefung saehe dann zwei
    Knoten, wo einer ist, wuerde also Kanten uebersehen und eine Befreiung zu
    Unrecht erteilen. Genau das war der Fehler der vorigen Fassung.

    Direkte Objekte haben keine Objektnummer und brauchen auch keine: ein
    direktes Dictionary steht an GENAU EINER syntaktischen Stelle der Datei und
    ist damit per Konstruktion unaliasbar. `id()` ist hier zulaessig, weil das
    Objekt in seinem Elternknoten gespeichert bleibt, also waehrend des ganzen
    Durchlaufs lebt und identisch ist -- es gibt kein `get_object()` und damit
    keinen Cache dazwischen. Und selbst wenn zwei verschiedene direkte
    Dictionaries dieselbe Identitaet erhielten, verschmelzen nur ihre
    Etikettenmengen: MEHR Etiketten bedeutet eine strengere, nie eine laxere
    Entscheidung.
    """
    if isinstance(value, IndirectObject):
        return ("idnum", value.idnum)
    return ("direct", id(value))


def _resolve_reference(value, budget):
    """Folgt einer Referenzkette bis zum letzten indirekten Glied.

    ISO 32000-1, 7.3.10: der WERT eines indirekten Objekts darf jedes Objekt
    sein -- auch selbst wieder eine indirekte Referenz. `5 0 obj 6 0 R endobj`
    ist gueltiges PDF, und `get_object()` loest genau ein Glied auf. Wer nur
    einmal aufloest, sieht bei einer Kette ein Nicht-Dictionary und verliert
    den ganzen Teilbaum dahinter -- derselbe Fehler wie beim indirekten Array.

    Rueckgabe `(link, target)`: `target` ist das aufgeloeste Objekt, `link` das
    LETZTE indirekte Glied der Kette (oder das direkte Objekt selbst). Die
    Kantenidentitaet haengt an `link`, damit ein Zwischenglied nicht als
    eigener Knoten zwischen Kante und Ziel steht und dessen Etiketten schluckt.
    `(None, None)` heisst: hier ist nichts, was Kanten aufspannen kann -- eine
    Kette im Kreis. Das ist die strenge Richtung: ohne Ziel gibt es keinen
    Knoten, der befreit werden koennte.
    """
    seen: set[int] = set()
    current = value
    while isinstance(current, IndirectObject):
        budget()
        if current.idnum in seen:
            return None, None
        seen.add(current.idnum)
        try:
            resolved = current.get_object()
        except Exception as exc:
            raise BinaryValidationError("PDF parser rejected input") from exc
        if isinstance(resolved, IndirectObject):
            current = resolved
            continue
        return current, resolved
    return value, value


def _labelled_children(key: str, value, budget=None):
    """Alle Kanten, die EIN Schluessel-Wert-Paar in den Graphen aufspannt.

    Abgeleitet aus dem Objektmodell von ISO 32000-1, 7.3, nicht aus einem
    beobachteten Angriff. Dort gibt es genau zwei Container, in denen sich eine
    Referenz verstecken kann:

      * Array (7.3.6) -- "may contain any combination of ... including other
        arrays", also beliebig verschachtelt, und selbst als indirektes Objekt
        speicherbar;
      * Dictionary (7.3.7), inklusive Stream (7.3.8), dessen Dictionary ein
        gewoehnliches Dictionary ist.

    Alles andere (Boolean 7.3.2, Zahl 7.3.3, String 7.3.4, Name 7.3.5, Null
    7.3.9) kann keine Referenz enthalten und spannt deshalb keine Kante auf.
    Referenzen (7.3.10) koennen in beiden Containern und in beliebiger
    Verschachtelung stehen, und beide Container koennen ueber eine Kette von
    Referenzen erreicht werden.

    Arrays sind hier TRANSPARENT: sie tragen keine eigene Kante, sondern
    reichen die Kanten ihrer Elemente an das umgebende Dictionary weiter,
    etikettiert mit dem Array-Sentinel. Das ist die Stelle, an der es dreimal
    geklemmt hat -- ein Array (direkt ODER indirekt, flach ODER verschachtelt)
    darf einen Verweis nicht verschlucken. Und das Sentinel ist notwendig, weil
    ein Array-Element niemals ein sauberer /Resources -> /XObject-Platz ist.
    """
    if budget is None:

        def budget() -> None:
            return None

    stack: list[tuple[str, object]] = [(key, value)]
    seen_arrays: set[tuple] = set()
    while stack:
        label, item = stack.pop()
        budget()
        link, target = _resolve_reference(item, budget)
        if target is None:
            continue
        if isinstance(target, DictionaryObject):
            # Streams eingeschlossen: StreamObject IST ein DictionaryObject.
            yield label, link
        elif isinstance(target, (list, tuple)):
            marker = _node_identity(link)
            if marker in seen_arrays:
                # Ein indirektes Array darf sich selbst enthalten.
                continue
            seen_arrays.add(marker)
            stack.extend((_ARRAY_ELEMENT_LABEL, element) for element in target)


_PDF_NODE = "node"
_PDF_EDGE = "edge"


def _pdf_walk(root):
    """DIE Erreichbarkeitsdefinition des Objektgraphen -- genau eine, fuer alle.

    Warum das ein eigener Generator ist und nicht zwei Durchlaeufe: es gab
    zwei, und sie sind auseinandergelaufen. `_pdf_nodes` folgte Arrays,
    `_pdf_reference_map` brach bei jedem aufgeloesten Nicht-Dictionary ab. Ein
    `/Contents <indirekte Referenz auf ein Array>` war damit fuer die
    Kantenbuchhaltung unsichtbar: der Strom darin sah aus, als haenge er nur im
    /XObject-Platz, bekam die Raster-Befreiung -- und wurde vom Interpreter als
    Seiteninhalt ausgefuehrt. Solange beide Konsumenten ihre Erreichbarkeit aus
    DIESEM Generator ziehen, ist die Kantenmenge per Konstruktion eine
    Obermenge der Knotenmenge; ein Test haelt die Beziehung zusaetzlich fest.

    Ereignisse:
      * `(_PDF_NODE, key, dictionary)` -- einmal je erreichbarem Dictionary
      * `(_PDF_EDGE, parent_key, label, key)` -- JEDE Referenzkante, auch die
        zweite auf denselben Knoten; genau daran ist Aliasing sichtbar.

    Zwei Deckel, beide gegen CPU-Verbrauch am Validator selbst:
    `MAX_PDF_OBJECTS` auf den Dictionaries (unveraendert) und
    `MAX_PDF_GRAPH_STEPS` auf den Schritten durch Arrays und Referenzketten --
    ohne den zweiten koennte ein Angreifer 20.000 Dictionaries auf dieselbe
    lange Kette indirekter Arrays zeigen lassen und ein Kreuzprodukt erzwingen.
    """
    steps = 0

    def budget() -> None:
        nonlocal steps
        steps += 1
        if steps > MAX_PDF_GRAPH_STEPS:
            raise BinaryValidationError("PDF object graph is too large")

    root_link, root_value = _resolve_reference(root, budget)
    if root_value is None:
        return
    root_key = _node_identity(root_link)
    yield (_PDF_EDGE, None, _ROOT_LABEL, root_key)
    stack = [(root_key, root_value)]
    expanded = {root_key}
    visited = 0
    while stack:
        key, value = stack.pop()
        if isinstance(value, IndirectObject):
            _, value = _resolve_reference(value, budget)
        if not isinstance(value, DictionaryObject):
            continue
        visited += 1
        if visited > MAX_PDF_OBJECTS:
            raise BinaryValidationError("PDF object graph is too large")
        yield (_PDF_NODE, key, value)
        for name, child in value.items():
            for label, target in _labelled_children(str(name), child, budget):
                child_key = _node_identity(target)
                yield (_PDF_EDGE, key, label, child_key)
                if child_key not in expanded:
                    expanded.add(child_key)
                    stack.append((child_key, target))


def _pdf_reference_map(root):
    """Wie jeder erreichbare Knoten erreicht wird -- ALLE eingehenden Kanten.

    Eine reine Sicht auf `_pdf_walk`, wie `_pdf_nodes`. Der Unterschied zu
    `_pdf_nodes` ist nur, dass hier die Kanten mitgeschrieben werden: dass
    dasselbe Dictionary MEHRFACH und unter VERSCHIEDENEN Etiketten eingehaengt
    sein kann, ist genau die Information, die eine Knotenliste verliert.

    Rueckgabe:
      * `labels[k]`       -- alle Etiketten, unter denen k erreicht wird
      * `parents[k]`      -- die Identitaeten aller Dictionaries, die k verweisen
      * `dictionaries[k]` -- das aufgeloeste Dictionary zu k
    """
    labels: dict[tuple, set[str]] = {}
    parents: dict[tuple, set[tuple]] = {}
    dictionaries: dict[tuple, DictionaryObject] = {}
    for record in _pdf_walk(root):
        if record[0] == _PDF_NODE:
            _, key, node = record
            dictionaries[key] = node
        else:
            _, parent_key, label, key = record
            labels.setdefault(key, set()).add(label)
            if parent_key is not None:
                parents.setdefault(key, set()).add(parent_key)
    return labels, parents, dictionaries


def _exempt_raster_idnums(root) -> set[int]:
    """Objektnummern der Streams, die NACHWEISLICH nicht ausgefuehrt werden.

    Die Regel ist bewusst positiv formuliert, und das ist der Kern: befreit
    wird nur, was BEWIESEN kein Inhalt ist -- nicht alles, wofuer der Beweis
    "ist Inhalt" gerade nicht gelang. Die erste Fassung ("kein /Page/Contents
    und /Subtype /Image -> befreit") verwandelte jedes Beweisloch in eine
    Befreiung. Die zweite drehte das um, pruefte den PLATZ aber nicht auf
    Aliasing: sie merkte sich das /Resources -> /XObject-Dictionary und
    ueberging beim Gegenzaehlen ALLE seine ausgehenden Verweise. Ein
    Dictionary, das gleichzeitig /XObject-Dictionary und etwas anderes ist,
    bekam damit seinen ganzen Inhalt freigestellt: das /CharProcs eines
    Typ-3-Fonts, ein /Pattern-Dictionary oder das Seiten-Dictionary selbst --
    dessen /Contents dann als "kein weiterer Verweis" galt.

    Befreit ist deshalb nur ein Strom, bei dem der ganze PLATZ unaliast ist:

      * er traegt /Type /XObject UND /Subtype /Image,
      * JEDE eingehende Kante kommt aus einem "reinen" /XObject-Dictionary
        und ist eine Schluesselkante (kein Array-Element, keine Wurzel),
      * ein reines /XObject-Dictionary ist ein Dictionary, das AUSSCHLIESSLICH
        als Wert des Schluessels /XObject erreicht wird und dessen saemtliche
        Eltern reine /Resources-Dictionaries sind,
      * ein reines /Resources-Dictionary wird AUSSCHLIESSLICH als Wert des
        Schluessels /Resources erreicht.

    Damit gilt: der einzige Weg zu einem befreiten Strom fuehrt ueber
    /Resources -> /XObject, also ueber einen Bildplatz. Ein Interpreter kann
    ihn nur per `Do` als Pixelraster zeichnen; als Inhalt ausgefuehrt wird er
    nie. Sobald irgendein Glied der Kette zusaetzlich unter einem anderen
    Schluessel haengt -- /CharProcs, /Pattern, /Kids, /Contents --, faellt die
    Befreiung, und der Strom wird gescannt.

    Ueber die Objektnummer, nicht ueber `id()`: siehe `_node_identity`.

    Und die Regel ist nur so gut wie der Graph, auf dem sie rechnet. Dreimal
    war der Graph unvollstaendig -- zuletzt fehlten ihm Arrays, sodass ein
    `/Contents <indirekte Referenz auf ein Array>` keine Kante beitrug und der
    Seiteninhalt als Rasterbild durchging. Die Erreichbarkeit kommt deshalb aus
    `_pdf_walk`, das aus dem Containermodell von ISO 32000-1, 7.3 abgeleitet ist
    (siehe `_labelled_children`), und zwei Tests halten das fest:
    `test_every_iso_container_that_can_hide_a_reference_spans_an_edge` und
    `test_the_reference_map_reaches_everything_an_independent_walk_reaches`.
    """
    labels, parents, dictionaries = _pdf_reference_map(root)

    def reached_solely_as(key, label: str) -> bool:
        return labels.get(key) == {label}

    resource_dicts = {key for key in dictionaries if reached_solely_as(key, "/Resources")}
    xobject_dicts = {
        key
        for key in dictionaries
        if reached_solely_as(key, "/XObject")
        and parents.get(key)
        and parents[key] <= resource_dicts
    }

    exempt: set[int] = set()
    for key, node in dictionaries.items():
        kind, idnum = key
        # Nur indirekte Stroeme koennen ueberhaupt befreit werden -- der
        # Scan-Aufrufer kennt einen Strom an seiner Objektnummer.
        if kind != "idnum" or not isinstance(node, StreamObject):
            continue
        if str(node.get("/Type", "")) != "/XObject":
            continue
        if str(node.get("/Subtype", "")) != "/Image":
            continue
        incoming = parents.get(key, set())
        if not incoming or not incoming <= xobject_dicts:
            continue
        if not all(label.startswith("/") for label in labels.get(key, set())):
            continue
        exempt.add(idnum)
    return exempt


def _decode_non_expanding(name: str, data: bytes) -> bytes:
    """Dekodiert einen der beiden nicht expandierenden Filter.

    Ein Filter ohne Dekodierer waere ein KeyError, kein stilles
    Durchwinken -- die Tabelle wird gegen `_PDF_NON_EXPANDING_FILTERS`
    behauptet, damit beide Mengen nicht auseinanderlaufen koennen.
    """
    try:
        return _NON_EXPANDING_DECODERS[name](data)
    except BinaryValidationError:
        raise
    except Exception as exc:
        raise BinaryValidationError("PDF stream is not decodable") from exc


def _consume_stream_budget(
    node: DictionaryObject, remaining: int, *, scan_for_inline_images: bool = True
) -> int:
    """Prueft Filter und Expansion EINES Streams und gibt das Restbudget
    zurueck. Das Budget ist bewusst global ueber alle Streams: viele kleine
    Bomben sind dieselbe Bombe.

    `scan_for_inline_images` ist absichtlich fail-closed vorbelegt: wer diese
    Funktion ohne die Angabe aufruft, bekommt die strengere Pruefung."""
    raw = node.get("/Filter")
    if isinstance(raw, IndirectObject):
        raw = raw.get_object()
    if raw is None:
        names: list[str] = []
    elif isinstance(raw, (list, tuple)):
        names = [str(name) for name in raw]
    else:
        names = [str(raw)]
    # Eine Filterkette liesse sich nicht gebunden dekodieren, ohne jede Stufe
    # selbst nachzubauen -- also genau ein Filter pro Stream.
    if len(names) > 1:
        raise BinaryValidationError("PDF stream filter chains are not allowed")
    for name in names:
        if name not in _PDF_FILTERS:
            raise BinaryValidationError("PDF stream filter is not allowed")
    data = getattr(node, "_data", b"") or b""
    if not isinstance(data, (bytes, bytearray)):
        raise BinaryValidationError("PDF parser rejected input")
    # Jeder DEKODIERTE Strom, der als Inhalt ausgefuehrt werden kann, wird auf
    # Inline-Bilder geprueft -- nicht nur die rohe Datei. Ein Inhaltsstrom darf
    # selbst komprimiert oder kodiert sein; ein Rohbyte-Scan allein waere die
    # Abwehr an einer Stelle und ihre Luecke in der Schwester daneben.
    #
    # Ausgenommen sind ausschliesslich Stroeme, die NACHWEISLICH kein Inhalt
    # sind (siehe `_exempt_raster_idnums`). Das ist kein Nachlassen, sondern
    # die Beseitigung eines echten Fehlalarms: der Operator ist vier Bytes
    # lang und trifft in zufaelligen Bilddaten mit rund 3e-8 pro Byte -- ein
    # dekodiertes 600-KB-Raster wuerde so etwa eines von 55 voellig
    # gueltigen Dokumenten grundlos ablehnen.
    scan = scan_for_inline_images
    if not names:
        # Unkodiert: dieselben Bytes stehen so auch in der Datei, der
        # Rohbyte-Scan hat sie also bereits gesehen. Trotzdem auch hier --
        # diese Pruefung darf sich nicht darauf verlassen, dass der Nachbar
        # sie schon gemacht hat.
        if scan:
            _reject_inline_images(bytes(data))
        produced = len(data)
    elif names[0] in _PDF_NON_EXPANDING_FILTERS:
        # ASCIIHex/ASCII85 expandieren nie ueber ihre Eingabelaenge hinaus,
        # verbergen ein Inline-Bild vor einem Rohbyte-Scan aber genauso
        # wirksam wie Flate. Die Ausgabe ist durch die Eingabelaenge
        # gebunden, das Dekodieren am Stueck ist hier also unbedenklich.
        if scan:
            _reject_inline_images(_decode_non_expanding(names[0], bytes(data)))
        produced = len(data)
    else:
        # Flate: der Scan sitzt in `_bounded_inflate` selbst, weil der
        # Klartext dort bewusst nie am Stueck existiert.
        produced = _bounded_inflate(bytes(data), remaining, scan=scan)
    if produced > remaining:
        raise BinaryValidationError("PDF stream expands beyond the allowed budget")
    return remaining - produced


def _check_pdf_shape(node: DictionaryObject) -> None:
    """Allowlist je nach Knotentyp. Unbekannte Typen werden nicht geprueft --
    sie sind ueber den Katalog gar nicht erreichbar, weil dessen eigene
    Allowlist nur /Pages als Einstieg in den Baum zulaesst."""
    node_type = str(node.get("/Type", ""))
    # /Contents entscheidet mit, nicht nur /Type: pypdf liefert auch eine
    # Seite OHNE /Type als Seite aus und fuehrt ihren Inhaltsstrom aus. Nur
    # auf /Type zu schauen hiesse, dass ein weggelassener Schluessel die
    # ganze Seiten-Allowlist umgeht -- dieselbe Wurzel wie beim Inline-Bild.
    if node_type == "/Page" or "/Contents" in node:
        unexpected = sorted(str(key) for key in node.keys() if str(key) not in _PDF_PAGE_KEYS)
        if unexpected:
            raise BinaryValidationError(f"PDF page key is not allowed: {unexpected[0]}")
    elif node_type == "/Pages":
        unexpected = sorted(
            str(key) for key in node.keys() if str(key) not in _PDF_PAGES_NODE_KEYS
        )
        if unexpected:
            raise BinaryValidationError(f"PDF page tree key is not allowed: {unexpected[0]}")


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
    # Reiner Bytescan ausserhalb der Stream-Nutzdaten, vor dem Parser. Die
    # Nutzdaten selbst -- komprimiert wie unkomprimiert -- gehoeren dem
    # Objektgraph-Durchlauf weiter unten; siehe
    # `_reject_inline_images_outside_streams`.
    _reject_inline_images_outside_streams(body)
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
    for node, _ in _pdf_nodes(catalog):
        _reject_active_pdf_constructs(node)
    # 2. Die eigentliche Absicherung: Allowlist des Katalogs ...
    unexpected = sorted(str(key) for key in catalog.keys() if str(key) not in _PDF_CATALOG_KEYS)
    if unexpected:
        raise BinaryValidationError(f"PDF catalog key is not allowed: {unexpected[0]}")
    # 3. ... und der Formen darunter, inklusive Filter- und
    #    Expansionsbudget jedes erreichbaren Streams.
    remaining = MAX_PDF_EXPANDED_BYTES
    # Welche Stroeme sind NACHWEISLICH kein Inhalt? Nur die werden vom
    # Inline-Bild-Scan befreit -- alles andere wird gescannt.
    exempt_idnums = _exempt_raster_idnums(catalog)
    for node, idnum in _pdf_nodes(catalog):
        _check_pdf_shape(node)
        if isinstance(node, StreamObject):
            remaining = _consume_stream_budget(
                node, remaining, scan_for_inline_images=idnum not in exempt_idnums
            )
    return _result(body, "application/pdf", "pdf")


def _reject_trailing_pdf_bytes(body: bytes) -> None:
    """Genau EINE Revision, und hinter ihrem %%EOF nur Whitespace.

    Die erste Fassung dieser Pruefung sah nur hinter das LETZTE %%EOF und war
    damit wirkungslos: `gueltig.pdf + Nutzlast + b"%%EOF"` bestand sie, waehrend
    der Parser unveraendert die urspruengliche xref benutzte -- der Anhang fuhr
    unsichtbar mit. Massgeblich ist deshalb das ERSTE %%EOF, und es darf nur
    eines geben; damit sind angehaengte Nutzlasten UND inkrementelle Updates
    (bei denen nicht mehr eindeutig ist, welche Bytes ein Leser sieht) beide
    ausgeschlossen.

    Bewusste Inkaufnahme: taucht die Bytefolge "%%EOF" zufaellig in einem
    komprimierten Stream auf, lehnt diese Pruefung ein an sich gueltiges PDF
    ab. Das ist die fail-closed Richtung.
    """
    if body.count(b"%%EOF") != 1:
        raise BinaryValidationError(
            "PDF must contain exactly one revision: malformed or polyglot"
        )
    marker = body.find(b"%%EOF")
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


def precheck_artifact(kind: str, body: bytes, *, declared_mime: str) -> None:
    """Phase 1 von zwei: die BILLIGEN, streng gebundenen Pruefungen.

    Warum es diese Funktion gibt -- die Reihenfolge im Aufrufer ist ein
    Kompromiss zwischen zwei echten Angriffen, und beide wurden im Review
    vorgefuehrt:

    * Reserviert man die Nonce ZUERST, verbrennt jede signierte, aber
      ungueltige Nutzlast dauerhaft eine Nonce (Replay-Kapazitaet erschoepfbar).
    * Validiert man ZUERST vollstaendig, laesst sich dieselbe gueltige,
      signierte Anfrage beliebig oft wiedervorlegen und erzwingt jedes Mal bis
      zu 10 MiB Parsing plus 32 MiB Inflation, bevor ueberhaupt eine Nonce
      faellt.

    Aufloesung in drei Phasen: erst DAS HIER (Groesse, Magic, deklarierter Typ,
    ZPL-Kommandoscan -- alles linear, ohne Parser, ohne Dekompression), dann
    die Nonce-Reservierung, dann der teure Durchlauf. Eine Wiedervorlage
    stirbt damit an der Nonce, bevor teure Arbeit anfaellt; eine Nonce
    verbrennen kann nur, wer diese Huerde bereits genommen hat.

    Wer diese Reihenfolge aendert, macht einen der beiden Angriffe wieder auf.
    """
    require_artifact_declared_mime(kind, declared_mime)
    if len(body) > MAX_DOCUMENT_BYTES:
        raise BinaryValidationError("Artifact exceeds 10 MiB")
    _ARTIFACT_PRECHECKS[kind](body)


def _precheck_pdf(body: bytes) -> None:
    """Magic, erlaubte Version, Revisionsdisziplin und der Inline-Bild-Scan
    ausserhalb der Stream-Nutzdaten -- alles reine Bytescans, linear, ohne
    Parser und ohne Dekompression, und damit richtig in Phase 1 aufgehoben.

    Was Phase 1 hier NICHT mehr leistet, und warum das folgenlos ist: die
    Nutzdaten der Stroeme werden uebersprungen, ein Inline-Bild in einem
    Inhaltsstrom faellt also erst im teuren Durchlauf. Das war schon vorher so,
    sobald der Strom komprimiert war -- ihn hier zu sehen hiesse vor der Nonce
    dekomprimieren. Fuer den unkomprimierten Fall ist Phase 1 nur eine
    Wiederholung dessen, was Phase 3 im Zweig "kein Filter" ohnehin prueft;
    diese Wiederholung wurde aufgegeben, weil sie ueber die komprimierten
    Bytes von Rasterbildern lief und dort massenhaft Fehlalarme erzeugte."""
    if not body.startswith(_PDF_VERSIONS):
        raise BinaryValidationError("PDF magic or version is not allowed")
    _reject_trailing_pdf_bytes(body)
    _reject_inline_images_outside_streams(body)


def _precheck_zpl(body: bytes) -> None:
    """ZPL ist bereits vollstaendig linear pruefbar -- die komplette
    Kommando-Allowlist passt deshalb in die billige Phase. Fuer ZPL ist der
    teure Durchlauf danach nur noch eine Wiederholung."""
    validate_zpl(body)


def require_artifact_declared_mime(kind: str, declared_mime: str) -> str:
    """Prueft Art + deklarierten Typ OHNE den Inhalt anzufassen.

    Existiert, damit die Route den billigen Header-Vergleich vor dem
    Replay-Gate machen kann und den teuren Parserlauf erst danach -- ohne
    dass dabei eine zweite, moeglicherweise abweichende Vergleichslogik
    entsteht: `validate_artifact` ruft exakt diese Funktion auf, beide lesen
    dieselbe Tabelle.
    """
    entry = _ARTIFACT_KINDS.get(kind) if isinstance(kind, str) else None
    if entry is None:
        raise BinaryValidationError("Artifact kind is not allowed")
    expected_mime = entry[0]
    if declared_mime != expected_mime:
        raise BinaryValidationError("Declared MIME does not match artifact kind")
    return expected_mime


def validate_artifact(kind: str, body: bytes, *, declared_mime: str) -> ValidatedBinary:
    """Prueft Art, deklarierten Typ und tatsaechlichen Inhalt in einem Zug.

    Die Art wird exakt verglichen (kein `lower()`, kein `strip()`): "PDF" ist
    nicht "pdf", damit Gross-/Kleinschreibung nicht zu zwei verschiedenen
    Artefakt-Referenzen fuer dieselbe Datei fuehrt. `kind` wird nie in die
    Meldung uebernommen -- der Wert kommt aus dem URL-Pfad.
    """
    require_artifact_declared_mime(kind, declared_mime)
    return _ARTIFACT_KINDS[kind][1](body)
# Die billige Vorpruefung je Art. Gleiche Schluessel wie _ARTIFACT_KINDS --
# eine Art ohne Vorpruefung waere ein KeyError, kein stilles Durchwinken.
_ARTIFACT_PRECHECKS: dict[str, Callable[[bytes], None]] = {
    "pdf": _precheck_pdf,
    "zpl": _precheck_zpl,
}
assert set(_ARTIFACT_PRECHECKS) == ARTIFACT_KINDS
