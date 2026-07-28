"""Tests fuer die Binaer-Validierung (Task 11).

Leitmotiv: ALLOWLIST. Jeder Test hier fragt "wird genau das Erlaubte
akzeptiert und alles andere abgelehnt?", nicht "wird diese eine bekannte
Angriffsform geblockt?". Deshalb pruefen die Negativtests auch Formate, die
gar keine bekannte Schwachstelle haben (GIF, BMP, SVG, reiner Text): sie
scheitern, weil sie nicht auf der Liste stehen, nicht weil sie als
gefaehrlich erkannt wurden.

Zweites Leitmotiv: Paritaet der drei Validatoren. Groesse, Magic/Container,
deklarierter vs. tatsaechlicher Typ und der Hash-Vertrag werden fuer Bild,
PDF und ZPL jeweils gepruefte -- eine Abwehr darf nicht in einem Validator
sitzen und im Nachbarn fehlen.
"""
import hashlib
import zlib
from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    StreamObject,
    TextStringObject,
)

from app.services.binary_validation import (
    MAX_DOCUMENT_BYTES,
    MAX_IMAGE_BYTES,
    BinaryValidationError,
    precheck_artifact,
    sanitize_filename,
    validate_artifact,
    validate_image,
    validate_pdf,
    validate_zpl,
)


# --------------------------------------------------------------------------
# Fixtures / Builders
# --------------------------------------------------------------------------


def png_bytes(size=(32, 32)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, "white").save(stream, format="PNG")
    return stream.getvalue()


def jpeg_bytes(size=(32, 32)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, "white").save(stream, format="JPEG")
    return stream.getvalue()


def webp_bytes(size=(32, 32)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, "white").save(stream, format="WEBP")
    return stream.getvalue()


def animated_bytes(image_format: str) -> bytes:
    frames = [Image.new("RGB", (16, 16), color) for color in ("red", "blue")]
    stream = BytesIO()
    frames[0].save(
        stream,
        format=image_format,
        save_all=True,
        append_images=frames[1:],
        duration=100,
    )
    return stream.getvalue()


def pdf_bytes(pages: int = 1, mutate=None) -> bytes:
    stream = BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    if mutate is not None:
        mutate(writer)
    writer.write(stream)
    return stream.getvalue()


ZPL_LABEL = b"^XA^FO20,20^FDParcel 42^FS^XZ"


# --------------------------------------------------------------------------
# validate_image
# --------------------------------------------------------------------------


def test_valid_single_frame_png_passes():
    result = validate_image(png_bytes(), declared_mime="image/png")
    assert result.mime_type == "image/png"
    assert result.size > 0
    assert len(result.sha256) == 64


def test_image_result_reports_exact_size_hash_and_extension():
    body = jpeg_bytes()
    result = validate_image(body, declared_mime="image/jpeg")
    assert (result.size, result.sha256) == (len(body), hashlib.sha256(body).hexdigest())
    assert (result.mime_type, result.extension) == ("image/jpeg", "jpg")


def test_valid_static_webp_passes():
    result = validate_image(webp_bytes(), declared_mime="image/webp")
    assert (result.mime_type, result.extension) == ("image/webp", "webp")


def test_image_polyglot_and_more_than_24_megapixels_fail():
    with pytest.raises(BinaryValidationError, match="polyglot"):
        validate_image(png_bytes() + b"%PDF-1.7", declared_mime="image/png")
    with pytest.raises(BinaryValidationError, match="24 megapixels"):
        validate_image(
            png_bytes((5000, 5000)),
            declared_mime="image/png",
        )


@pytest.mark.parametrize(
    "body,declared",
    [
        (jpeg_bytes() + b"<?php system($_GET[0]); ?>", "image/jpeg"),
        (webp_bytes() + b"%PDF-1.7", "image/webp"),
        (b"GIF89a" + png_bytes(), "image/png"),
    ],
)
def test_every_allowed_container_rejects_appended_or_prepended_payload(body, declared):
    with pytest.raises(BinaryValidationError):
        validate_image(body, declared_mime=declared)


def test_declared_mime_must_match_the_decoded_format():
    with pytest.raises(BinaryValidationError, match="Declared MIME"):
        validate_image(png_bytes(), declared_mime="image/jpeg")
    with pytest.raises(BinaryValidationError, match="Declared MIME"):
        validate_image(jpeg_bytes(), declared_mime="image/png")
    # Ein Parameter-Suffix ist kein Treffer: die Allowlist vergleicht exakt.
    with pytest.raises(BinaryValidationError, match="Declared MIME"):
        validate_image(png_bytes(), declared_mime="image/png; charset=binary")


@pytest.mark.parametrize("image_format,declared", [("GIF", "image/gif"), ("BMP", "image/bmp")])
def test_formats_outside_the_allowlist_are_rejected(image_format, declared):
    stream = BytesIO()
    Image.new("RGB", (16, 16), "white").save(stream, format=image_format)
    with pytest.raises(BinaryValidationError, match="Only JPEG, PNG, and WebP"):
        validate_image(stream.getvalue(), declared_mime=declared)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not an image at all",
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"%PDF-1.7\n%%EOF\n",
    ],
)
def test_non_image_payloads_are_rejected(body):
    with pytest.raises(BinaryValidationError):
        validate_image(body, declared_mime="image/png")


def test_animated_images_are_rejected():
    with pytest.raises(BinaryValidationError, match="Animated"):
        validate_image(animated_bytes("WEBP"), declared_mime="image/webp")
    # Animiertes GIF scheitert bereits an der Format-Allowlist -- geprueft,
    # damit kein Pfad existiert, auf dem Mehrbildmaterial durchkommt.
    with pytest.raises(BinaryValidationError):
        validate_image(animated_bytes("GIF"), declared_mime="image/gif")


def test_oversized_image_is_rejected_before_decoding():
    body = b"\x89PNG\r\n\x1a\n" + b"0" * MAX_IMAGE_BYTES
    with pytest.raises(BinaryValidationError, match="15 MiB"):
        validate_image(body, declared_mime="image/png")


def test_decompression_bomb_is_rejected_not_raised_as_pillow_error():
    # 20000x20000 = 400 Megapixel in ~1.2 MB: Pillow wirft hier
    # DecompressionBombError (KEIN OSError) -- ohne explizites Abfangen
    # waere das ein 500 statt einer Ablehnung.
    with pytest.raises(BinaryValidationError):
        validate_image(png_bytes((20000, 20000)), declared_mime="image/png")


def test_valid_header_with_broken_payload_is_rejected():
    body = png_bytes((64, 64))
    truncated = body[: len(body) // 2] + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    with pytest.raises(BinaryValidationError):
        validate_image(truncated, declared_mime="image/png")


# --------------------------------------------------------------------------
# validate_pdf
# --------------------------------------------------------------------------


def test_valid_single_page_pdf_passes():
    body = pdf_bytes()
    result = validate_pdf(body)
    assert (result.mime_type, result.extension) == ("application/pdf", "pdf")
    assert (result.size, result.sha256) == (len(body), hashlib.sha256(body).hexdigest())


def test_pdf_javascript_and_embedded_file_fail():
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_js("app.alert('x')")
    writer.write(stream)
    with pytest.raises(BinaryValidationError, match="JavaScript"):
        validate_pdf(stream.getvalue())

    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_attachment("secret.txt", b"secret")
    writer.write(stream)
    with pytest.raises(BinaryValidationError, match="embedded"):
        validate_pdf(stream.getvalue())


def test_pdf_launch_action_is_rejected():
    def mutate(writer):
        writer.root_object[NameObject("/OpenAction")] = DictionaryObject(
            {
                NameObject("/S"): NameObject("/Launch"),
                NameObject("/F"): TextStringObject("calc.exe"),
            }
        )

    with pytest.raises(BinaryValidationError, match="launch"):
        validate_pdf(pdf_bytes(mutate=mutate))


def test_pdf_catalog_key_outside_the_allowlist_is_rejected():
    def mutate(writer):
        writer.root_object[NameObject("/AcroForm")] = DictionaryObject(
            {NameObject("/Fields"): ArrayObject()}
        )

    with pytest.raises(BinaryValidationError, match="catalog key"):
        validate_pdf(pdf_bytes(mutate=mutate))


def test_pdf_with_bytes_after_eof_is_rejected():
    with pytest.raises(BinaryValidationError, match="polyglot"):
        validate_pdf(pdf_bytes() + b"HOSTILE")


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"GIF89a%PDF-1.7\n%%EOF\n",
        png_bytes(),
        b"%PDF-9.9\n%%EOF\n",
    ],
)
def test_pdf_without_allowed_magic_or_version_is_rejected(body):
    with pytest.raises(BinaryValidationError):
        validate_pdf(body)


def test_encrypted_pdf_is_rejected():
    def mutate(writer):
        writer.encrypt("pw")

    with pytest.raises(BinaryValidationError, match="Encrypted"):
        validate_pdf(pdf_bytes(mutate=mutate))


def test_pdf_page_count_boundary():
    assert validate_pdf(pdf_bytes(pages=20)).extension == "pdf"
    with pytest.raises(BinaryValidationError, match="20 pages"):
        validate_pdf(pdf_bytes(pages=21))


def test_oversized_pdf_is_rejected_before_parsing():
    with pytest.raises(BinaryValidationError, match="10 MiB"):
        validate_pdf(b"%PDF-1.7" + b"0" * MAX_DOCUMENT_BYTES)


# --------------------------------------------------------------------------
# validate_zpl
# --------------------------------------------------------------------------


def test_zpl_allows_layout_but_rejects_config_and_tilde_commands():
    assert validate_zpl(b"^XA^FO20,20^FDParcel 42^FS^XZ").mime_type == (
        "application/zpl"
    )
    for body in (b"^XA^JUS^XZ", b"~JA", b"^XA^DFE:FORMAT.ZPL^XZ"):
        with pytest.raises(BinaryValidationError):
            validate_zpl(body)


def test_zpl_result_reports_hash_size_and_extension():
    result = validate_zpl(ZPL_LABEL)
    assert (result.size, result.sha256) == (
        len(ZPL_LABEL),
        hashlib.sha256(ZPL_LABEL).hexdigest(),
    )
    assert result.extension == "zpl"


@pytest.mark.parametrize(
    "body",
    [
        b"^XA^ju^XZ",  # Kleinschreibung: von einem findall-Filter nie erfasst
        b"^XA^Ju^XZ",
        b"^XA^ ^XZ",  # Caret ohne Kommando
        b"^XA^FDx^XZ~JA",  # Tilde nach dem Dokumentende
        b"^XA^FDx^FS^XZ^XA^JUS^XZ",  # zweites Dokument
        b"^XA^GB100,100,2^XZ",  # gueltiges ZPL, aber nicht auf der Allowlist
        b"^FDx^XZ",  # kein ^XA am Anfang
        b"^XA^FDx",  # kein ^XZ am Ende
        b"",
    ],
)
def test_zpl_rejects_everything_outside_the_command_allowlist(body):
    with pytest.raises(BinaryValidationError):
        validate_zpl(body)


def test_zpl_must_be_pure_ascii():
    with pytest.raises(BinaryValidationError, match="ASCII"):
        validate_zpl("^XA^FDPäckchen^FS^XZ".encode("utf-8"))


def test_zpl_rejects_control_characters_in_field_data():
    with pytest.raises(BinaryValidationError):
        validate_zpl(b"^XA^FDa\x00b^FS^XZ")


def test_oversized_zpl_is_rejected():
    with pytest.raises(BinaryValidationError, match="10 MiB"):
        validate_zpl(b"^XA" + b"A" * MAX_DOCUMENT_BYTES + b"^XZ")


# --------------------------------------------------------------------------
# validate_artifact (die EINE Guard-Kette, die die Route benutzt)
# --------------------------------------------------------------------------


def test_validate_artifact_dispatches_only_allowlisted_kinds():
    assert validate_artifact(
        "pdf", pdf_bytes(), declared_mime="application/pdf"
    ).extension == "pdf"
    assert validate_artifact(
        "zpl", ZPL_LABEL, declared_mime="application/zpl"
    ).extension == "zpl"
    for kind in ("PDF", "png", "exe", "", "pdf/../zpl"):
        with pytest.raises(BinaryValidationError, match="kind"):
            validate_artifact(kind, pdf_bytes(), declared_mime="application/pdf")


def test_validate_artifact_requires_the_declared_type_of_its_kind():
    with pytest.raises(BinaryValidationError, match="Declared MIME"):
        validate_artifact("pdf", pdf_bytes(), declared_mime="application/zpl")
    with pytest.raises(BinaryValidationError, match="Declared MIME"):
        validate_artifact("zpl", ZPL_LABEL, declared_mime="application/pdf")


def test_validate_artifact_rejects_content_that_is_not_its_kind():
    with pytest.raises(BinaryValidationError):
        validate_artifact("pdf", ZPL_LABEL, declared_mime="application/pdf")
    with pytest.raises(BinaryValidationError):
        validate_artifact("zpl", pdf_bytes(), declared_mime="application/zpl")


# --------------------------------------------------------------------------
# sanitize_filename
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("label.pdf", "label.pdf"),
        ("../../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\cmd.exe", "cmd.exe"),
        ("/absolute/path/x.png", "x.png"),
        ("..", "upload"),
        (".", "upload"),
        ("", "upload"),
        ("...", "upload"),
        ("....//....//x", "x"),
        ("a\x00b.pdf", "a_b.pdf"),
        ("a\nb\r.pdf", "a_b_.pdf"),
        ("Rechnung Nr. 5.pdf", "Rechnung_Nr._5.pdf"),
        # RIGHT-TO-LEFT OVERRIDE (U+202E): laesst "exe.jpg" im Dateimanager
        # wie "gpj.exe" aussehen. Muss verschwinden, nicht durchgereicht werden.
        ("\u202egpj.exe", "gpj.exe"),
        # Kyrillisches "e" (U+0435) statt ASCII "e" -- Homoglyph.
        ("еtc.pdf", "tc.pdf"),
        ("файл", "upload"),
    ],
)
def test_sanitize_filename_keeps_only_an_ascii_leaf(value, expected):
    assert sanitize_filename(value) == expected


def test_sanitize_filename_truncates_and_never_returns_separators():
    long_name = sanitize_filename("x" * 500 + ".pdf")
    assert len(long_name) <= 120
    for value in ("a/b", "a\\b", "a" * 500, "../x/../y"):
        result = sanitize_filename(value)
        assert "/" not in result and "\\" not in result
        assert result not in ("", ".", "..")


# ==========================================================================
# Regressionen aus dem Review (Runde 1)
# ==========================================================================


def flate_bomb_pdf(plain_megabytes: int = 200) -> bytes:
    """Ein syntaktisch einwandfreies einseitiges PDF, dessen Inhaltsstream
    komprimiert ~200 KB gross ist und dekomprimiert ~200 MB ergibt."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    deflated = zlib.compress(b"0" * (plain_megabytes * 1024 * 1024), 9)
    stream = StreamObject()
    stream[NameObject("/Filter")] = NameObject("/FlateDecode")
    stream[NameObject("/Length")] = NumberObject(len(deflated))
    stream._data = deflated
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_pdf_flate_decompression_bomb_is_rejected():
    """CRITICAL 1: die Pillow-Bombe war zu, die PDF-Bombe offen. Ein 200-KB-
    PDF darf sich nicht auf 200 MB entfalten duerfen."""
    body = flate_bomb_pdf()
    assert len(body) < 1024 * 1024
    with pytest.raises(BinaryValidationError, match="expands"):
        validate_pdf(body)


def test_pdf_within_the_expansion_budget_still_passes():
    """Gegenprobe: die Bomben-Sperre darf ein normales PDF mit komprimiertem
    Inhaltsstream nicht mitreissen."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    deflated = zlib.compress(b"BT /F1 12 Tf (hello) Tj ET\n" * 100, 9)
    stream = StreamObject()
    stream[NameObject("/Filter")] = NameObject("/FlateDecode")
    stream[NameObject("/Length")] = NumberObject(len(deflated))
    stream._data = deflated
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    assert validate_pdf(out.getvalue()).extension == "pdf"


def test_pdf_with_chained_filters_is_rejected():
    """Eine Filterkette laesst sich nicht gebunden dekodieren, ohne jede Stufe
    selbst zu implementieren. Genau ein Filter pro Stream ist erlaubt."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    stream = StreamObject()
    stream[NameObject("/Filter")] = ArrayObject(
        [NameObject("/ASCII85Decode"), NameObject("/FlateDecode")]
    )
    stream._data = b"whatever"
    stream[NameObject("/Length")] = NumberObject(8)
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    with pytest.raises(BinaryValidationError, match="filter"):
        validate_pdf(out.getvalue())


def test_pdf_polyglot_with_appended_second_eof_is_rejected():
    """CRITICAL 2: nur hinter dem LETZTEN %%EOF zu pruefen war wirkungslos --
    der Parser benutzt weiter die urspruengliche xref, der Anhang faehrt mit.
    Genau eine Revision, und hinter ihrem %%EOF nur Whitespace."""
    hostile = pdf_bytes() + b"<?php system($_GET[0]); ?>\n%%EOF\n"
    with pytest.raises(BinaryValidationError, match="polyglot"):
        validate_pdf(hostile)


def test_pdf_with_incremental_update_is_rejected():
    """Dieselbe Regel aus der anderen Richtung: mehrere Revisionen in einer
    Datei sind nicht erlaubt, weil dann nicht mehr eindeutig ist, welche
    Bytes der Leser tatsaechlich sieht."""
    body = pdf_bytes()
    with pytest.raises(BinaryValidationError, match="polyglot"):
        validate_pdf(body + body)


# ==========================================================================
# Regressionen aus dem Review (Runde 2)
# ==========================================================================


def image_codec_pdf(filter_name: str) -> bytes:
    """Ein PDF mit einem Stream, der einen Bildcodec deklariert und dabei
    1x1 Pixel behauptet -- die Codecdaten selbst koennen beliebig gross sein."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    stream = StreamObject()
    stream[NameObject("/Filter")] = NameObject(filter_name)
    stream[NameObject("/Width")] = NumberObject(1)
    stream[NameObject("/Height")] = NumberObject(1)
    stream._data = b"\xff\xd8\xff" + b"\x00" * 64
    stream[NameObject("/Length")] = NumberObject(67)
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.mark.parametrize("filter_name", ["/DCTDecode", "/CCITTFaxDecode"])
def test_pdf_image_codec_filters_are_not_allowed(filter_name):
    """FIX 2: diese beiden umgingen das Expansionsbudget vollstaendig und
    vertrauten allein den DEKLARIERTEN Bildmassen -- ein 1x1-Bild darf
    Codecdaten fuer ein riesiges tragen. Sie stehen jetzt, wie /LZWDecode und
    /RunLengthDecode zuvor, gar nicht mehr auf der Allowlist."""
    with pytest.raises(BinaryValidationError, match="filter"):
        validate_pdf(image_codec_pdf(filter_name))


def test_precheck_is_bounded_and_catches_the_cheap_rejections():
    """FIX 4: die billige Vorpruefung muss ohne Parser und ohne Inflation
    auskommen und trotzdem alles fangen, was an Magic, Groesse, deklariertem
    Typ oder ZPL-Kommandos scheitert."""
    for kind, body, declared in (
        ("pdf", png_bytes(), "application/pdf"),
        ("pdf", ZPL_LABEL, "application/pdf"),
        ("pdf", pdf_bytes() + b"HOSTILE", "application/pdf"),
        ("pdf", b"%PDF-1.7" + b"0" * MAX_DOCUMENT_BYTES, "application/pdf"),
        ("zpl", pdf_bytes(), "application/zpl"),
        ("zpl", b"^XA^JUS^XZ", "application/zpl"),
        ("zpl", b"^XA^ju^XZ", "application/zpl"),
        ("pdf", pdf_bytes(), "application/zpl"),
        ("png", pdf_bytes(), "application/pdf"),
    ):
        with pytest.raises(BinaryValidationError):
            precheck_artifact(kind, body, declared_mime=declared)


def test_precheck_passes_what_only_the_full_parse_can_reject():
    """Gegenprobe und zugleich die Begruendung fuer die Reihenfolge: was nur
    der teure Durchlauf erkennt, kommt hier durch -- deshalb sitzt die
    Nonce-Reservierung dazwischen."""
    for body in (pdf_bytes(pages=21), flate_bomb_pdf()):
        precheck_artifact("pdf", body, declared_mime="application/pdf")
        with pytest.raises(BinaryValidationError):
            validate_artifact("pdf", body, declared_mime="application/pdf")


def test_precheck_accepts_the_legitimate_artifacts():
    precheck_artifact("pdf", pdf_bytes(), declared_mime="application/pdf")
    precheck_artifact("zpl", ZPL_LABEL, declared_mime="application/zpl")
