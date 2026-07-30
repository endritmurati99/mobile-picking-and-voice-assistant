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
    IndirectObject,
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


# ==========================================================================
# Regression #9a: Inline-Bilder im Inhaltsstream (BI ... ID <data> EI)
# ==========================================================================


def _content_stream_pdf(content: bytes, *, compress: bool = False) -> bytes:
    """Einseitiges PDF mit GENAU diesem Inhaltsstream, roh oder Flate-gepackt.

    `compress=True` ist der eigentliche Punkt von #9a: der Inhaltsstream ist
    dann im Datei-Byte-Strom nicht mehr lesbar, ein reiner Rohbyte-Scan sieht
    das Inline-Bild also gar nicht.
    """
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    stream = StreamObject()
    data = zlib.compress(content, 9) if compress else content
    if compress:
        stream[NameObject("/Filter")] = NameObject("/FlateDecode")
    stream[NameObject("/Length")] = NumberObject(len(data))
    stream._data = data
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _inline_image_content(filter_abbreviation: bytes = b"") -> bytes:
    """Kleinster Inhaltsstrom, der ein Inline-Bild traegt.

    Inline-Bilder werden nie zu Stream-Objekten, der Objektgraph mit seiner
    Filter-Allowlist und seinem Expansionsbudget sieht sie deshalb nie. Die
    deklarierten /W und /H sind hier absichtlich absurd: sie zeigen, dass der
    Deklaration nicht zu trauen ist.
    """
    declared_filter = b"/F " + filter_abbreviation + b" " if filter_abbreviation else b""
    return (
        b"q\n"
        b"BI /W 65535 /H 65535 /CS /RGB /BPC 8 " + declared_filter + b"\n"
        b"ID \xff\xd8\xff\xe0 EI\n"
        b"Q\n"
    )


@pytest.mark.parametrize(
    "abbreviation", [b"/DCT", b"/CCF", b"/AHx", b"/A85", b"/RL", b"/LZW", b"/Fl"]
)
def test_inline_images_are_rejected_regardless_of_filter(abbreviation):
    body = _content_stream_pdf(_inline_image_content(abbreviation))
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(body)


def test_inline_image_without_a_filter_is_also_rejected():
    body = _content_stream_pdf(_inline_image_content())
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(body)


def test_the_cheap_phase_skips_stream_payloads_but_still_scans_the_rest():
    """Phase 1 ueberspringt Stream-Nutzdaten -- sie laeuft sonst ueber die
    komprimierten Bytes von Rasterbildern und lehnt gueltige Dokumente ab.
    Der Sicherheitspreis ist null: was sie ueberspringt, sieht Phase 3."""
    from app.services.binary_validation import _reject_inline_images_outside_streams

    inside = (
        b"%PDF-1.7\n1 0 obj<</Length 20>>stream\n"
        b"q BI /W 1 /H 1 ID x EI Q\nendstream endobj\n"
    )
    _reject_inline_images_outside_streams(inside)
    with pytest.raises(BinaryValidationError, match="inline image"):
        _reject_inline_images_outside_streams(inside + b"q BI /W 1\n")
    # Ohne "endstream" ist der Rest der Datei Nutzdaten -- und Phase 3 sieht
    # ihn trotzdem, denn ohne "endstream" gibt es kein parsbares PDF.
    _reject_inline_images_outside_streams(b"%PDF-1.7\n1 0 obj<<>>stream\nq BI /W 1\n")


def test_the_cheap_phase_hands_stream_payloads_to_the_expensive_pass():
    """Gegenprobe und zugleich der Nachweis, dass nichts verloren geht: was
    Phase 1 durchlaesst, weist der teure Durchlauf ab -- genau wie bei der
    Flate-Bombe und der Seitenzahl."""
    for compress in (False, True):
        body = _content_stream_pdf(_inline_image_content(b"/DCT"), compress=compress)
        precheck_artifact("pdf", body, declared_mime="application/pdf")
        with pytest.raises(BinaryValidationError, match="inline image"):
            validate_artifact("pdf", body, declared_mime="application/pdf")


def test_inline_image_inside_a_compressed_content_stream_is_rejected():
    """DER KERN von #9a: der Rohbyte-Scan allein genuegt nicht. Ein
    Inhaltsstream darf selbst Flate-komprimiert sein, das Inline-Bild steckt
    dann in den komprimierten Bytes. Der Test beweist zuerst, dass der
    Rohbyte-Pfad hier NICHTS sieht, und verlangt die Abweisung trotzdem."""
    from app.services.binary_validation import _reject_inline_images

    body = _content_stream_pdf(_inline_image_content(b"/DCT"), compress=True)
    # Beweis, dass hier wirklich der dekodierte Pfad greift und nicht der rohe:
    _reject_inline_images(body)
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(body)


def test_inline_image_straddling_an_inflate_chunk_boundary_is_rejected():
    """Der dekodierte Strom wird in 1-MiB-Schritten geprueft. Ein "BI", das
    genau auf der Schrittgrenze zerfaellt, darf nicht durchrutschen."""
    from app.services.binary_validation import _INFLATE_STEP_BYTES, _reject_inline_images

    content = b"\n" * (_INFLATE_STEP_BYTES - 1) + _inline_image_content(b"/DCT")
    body = _content_stream_pdf(content, compress=True)
    _reject_inline_images(body)
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(body)


def test_the_letters_bi_inside_ordinary_text_do_not_trip_the_check():
    """"BI" muss als OPERATOR erkannt werden, nicht als Teilzeichenkette: ein
    Lieferschein mit dem Wort "KABINE" ist kein Inline-Bild."""
    content = b"BT /F1 12 Tf (KABINE BID BIG ABI) Tj ET\n"
    assert validate_pdf(_content_stream_pdf(content)).extension == "pdf"
    assert validate_pdf(_content_stream_pdf(content, compress=True)).extension == "pdf"


def test_inline_image_operator_discriminates_operator_from_substring():
    from app.services.binary_validation import _reject_inline_images

    for harmless in (
        b"(KABINE) Tj",
        b"BID BIG ABI OBI",
        b"/BitsPerComponent 8",
        b"BI",
        b"xBI /W",
    ):
        _reject_inline_images(harmless)
    for hostile in (
        b"BI /W 1",
        b"q\nBI /W 1",
        b"] BI<</W 1>>",
        b"> BI [",
        b") BI\n",
    ):
        with pytest.raises(BinaryValidationError, match="inline image"):
            _reject_inline_images(hostile)


# --------------------------------------------------------------------------
# Review-Runde 1, C1: die Trennerklasse ist die der PDF-SPEZIFIKATION,
# nicht Pythons `\s`
# --------------------------------------------------------------------------

# ISO 32000-1, Tabelle 1. NUL gehoert dazu und fehlt in Pythons `\s`; VT
# (0x0B) steht in Pythons `\s` und ist hier KEIN Whitespace.
PDF_WHITESPACE_BYTES = [b"\x00", b"\t", b"\n", b"\x0c", b"\r", b" "]


@pytest.mark.parametrize("separator", PDF_WHITESPACE_BYTES)
@pytest.mark.parametrize("compress", [False, True])
def test_every_pdf_whitespace_byte_separates_the_bi_operator(separator, compress):
    """Jedes der sechs Whitespace-Bytes der PDF-Spezifikation trennt Tokens.
    NUL fehlte in Pythons `\\s` und machte `q\\x00BI /W 65535` unsichtbar --
    jeder konforme Renderer tokenisiert das wie `q BI`."""
    content = b"q" + separator + b"BI" + separator + b"/W 65535 /H 65535 /F /DCT\nID \xff\xd8 EI\nQ\n"
    body = _content_stream_pdf(content, compress=compress)
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(body)


@pytest.mark.parametrize("compress", [False, True])
def test_a_pdf_comment_after_bi_also_terminates_the_operator(compress):
    """`%` beendet ein Token ebenfalls: `BI%c\\n/W ...` ist ein Inline-Bild."""
    body = _content_stream_pdf(
        b"q\nBI%c\n/W 65535 /H 65535 /F /DCT\nID \xff\xd8 EI\nQ\n", compress=compress
    )
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(body)


def test_the_three_reported_nul_and_comment_bypasses_are_closed():
    """Die drei vom Review vorgefuehrten Umgehungen, roh UND Flate-gepackt."""
    from app.services.binary_validation import _reject_inline_images

    tail = b"/W 65535 /H 65535 /CS /RGB /BPC 8 /F /DCT\nID \xff\xd8\xff\xe0 EI\nQ\n"
    for content in (
        b"q\x00BI " + tail,
        b"q\nBI\x00" + tail,
        b"q\nBI%c\n" + tail,
    ):
        for compress in (False, True):
            body = _content_stream_pdf(content, compress=compress)
            if compress:
                # Beweis, dass hier der dekodierte Pfad greift, nicht der rohe.
                _reject_inline_images(body)
            with pytest.raises(BinaryValidationError, match="inline image"):
                validate_pdf(body)
            with pytest.raises(BinaryValidationError, match="inline image"):
                validate_artifact("pdf", body, declared_mime="application/pdf")


def test_vertical_tab_is_not_pdf_whitespace_but_is_still_refused():
    """VT (0x0B) ist in Pythons `\\s` und in PDF KEIN Whitespace. Es bleibt in
    der Klasse: die Pruefung darf mehr fangen als noetig, nie weniger."""
    from app.services.binary_validation import _reject_inline_images

    with pytest.raises(BinaryValidationError, match="inline image"):
        _reject_inline_images(b"q\x0bBI /W 1")


# --------------------------------------------------------------------------
# Review-Runde 1, I3: Inhaltsstrom vs. Rasterbild wird STRUKTURELL
# unterschieden, nicht am frei waehlbaren /Subtype
# --------------------------------------------------------------------------


def _pdf_with_image_xobject(image_payload: bytes, *, as_page_contents: bool) -> bytes:
    """Ein Flate-Strom mit /Subtype /Image -- einmal als Bild-XObject in
    /Resources, einmal als /Contents-Wert derselben Seite.

    Die Bytes sind identisch; nur die STRUKTURELLE POSITION unterscheidet
    sich. Genau daran, und nicht am /Subtype, muss die Pruefung haengen.
    """
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    deflated = zlib.compress(image_payload, 9)
    stream = StreamObject()
    stream[NameObject("/Type")] = NameObject("/XObject")
    stream[NameObject("/Subtype")] = NameObject("/Image")
    stream[NameObject("/Filter")] = NameObject("/FlateDecode")
    stream[NameObject("/Length")] = NumberObject(len(deflated))
    stream._data = deflated
    reference = writer._add_object(stream)
    if as_page_contents:
        page[NameObject("/Contents")] = reference
    else:
        xobjects = DictionaryObject()
        xobjects[NameObject("/Im0")] = reference
        resources = DictionaryObject()
        resources[NameObject("/XObject")] = xobjects
        page[NameObject("/Resources")] = resources
        content = StreamObject()
        content._data = b"q 100 0 0 100 0 0 cm /Im0 Do Q\n"
        content[NameObject("/Length")] = NumberObject(len(content._data))
        page[NameObject("/Contents")] = writer._add_object(content)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


# Bytes, die im Rasterrauschen zufaellig wie ein BI-Operator aussehen.
_LOOKS_LIKE_BI = b"\x91\x02 BI/\xff\x13\x7e" * 8


def test_a_raster_image_xobject_is_not_scanned_for_inline_images():
    """Ein /Subtype /Image-Strom, der NICHT von /Contents aus erreicht wird,
    wird per `Do` als Pixelraster gezeichnet -- ein "BI" darin ist Rauschen,
    kein Operator. Ihn zu scannen hiesse rund 1 von 264 gueltigen Dokumenten
    mit 200-KB-Raster grundlos abzulehnen."""
    body = _pdf_with_image_xobject(_LOOKS_LIKE_BI, as_page_contents=False)
    assert validate_pdf(body).extension == "pdf"


def test_claiming_subtype_image_on_a_content_stream_does_not_buy_an_exemption():
    """Der Gegentest, und der eigentliche Grund fuer die strukturelle
    Bestimmung: dieselben Bytes, dasselbe /Subtype /Image -- aber als
    /Contents der Seite. Der Renderer fuehrt sie aus, also wird gescannt."""
    body = _pdf_with_image_xobject(
        b"q\nBI /W 65535 /H 65535 /F /DCT\nID \xff\xd8 EI\nQ\n", as_page_contents=True
    )
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(body)


def test_subtype_image_inside_a_contents_array_is_still_scanned():
    """/Contents darf ein ARRAY sein. Auch dann ist jedes Element
    Inhaltsstrom -- die Elemente des Arrays muessen mitgezaehlt werden."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    hostile = zlib.compress(b"q\nBI /W 65535 /H 65535 /F /DCT\nID \xff\xd8 EI\nQ\n", 9)
    stream = StreamObject()
    stream[NameObject("/Subtype")] = NameObject("/Image")
    stream[NameObject("/Filter")] = NameObject("/FlateDecode")
    stream[NameObject("/Length")] = NumberObject(len(hostile))
    stream._data = hostile
    page[NameObject("/Contents")] = ArrayObject([writer._add_object(stream)])
    out = BytesIO()
    writer.write(out)
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(out.getvalue())


# --------------------------------------------------------------------------
# Review-Runde 2, C1-Rest: die DELIMITER-Tabelle (ISO 32000-1 Tabelle 2)
# --------------------------------------------------------------------------

# ISO 32000-1, Tabelle 2.
PDF_DELIMITER_BYTES = b"()<>[]{}/%"
# Delimiter, nach denen "BI" noch ein Operator sein kann. `{` und `}` sind
# Lexer-Delimiter des Inhaltsstroms: `q}BI /W ...` zerfaellt in q, }, BI.
PDF_DELIMITERS_THAT_CAN_PRECEDE_AN_OPERATOR = b")>]{}"


def test_the_module_spells_out_both_spec_tables():
    from app.services.binary_validation import _PDF_DELIMITERS, _PDF_WHITESPACE

    assert _PDF_WHITESPACE == b"".join(PDF_WHITESPACE_BYTES)
    assert _PDF_DELIMITERS == PDF_DELIMITER_BYTES


def test_the_prefix_class_is_exactly_the_documented_set():
    """Vollstaendiger 0x00-0xFF-Durchlauf statt Stichproben. Genau daran ist
    die vorige Fassung zweimal gescheitert: erst fehlte NUL (Tabelle 1), dann
    fehlten { und } (Tabelle 2)."""
    from app.services.binary_validation import _INLINE_IMAGE_OPERATOR

    tripping = {
        byte
        for byte in range(256)
        if _INLINE_IMAGE_OPERATOR.search(bytes([byte]) + b"BI /W 1")
    }
    expected = (
        set(b"".join(PDF_WHITESPACE_BYTES))
        | set(PDF_DELIMITERS_THAT_CAN_PRECEDE_AN_OPERATOR)
        | {0x0B}  # VT: kein PDF-Whitespace, bewusst mitgefangen
    )
    assert tripping == expected


@pytest.mark.parametrize("delimiter", [b"{", b"}"])
@pytest.mark.parametrize("compress", [False, True])
def test_curly_brace_delimiters_before_bi_are_an_inline_image(delimiter, compress):
    """`q}BI /W 65535 ...` wird vom Lexer in q, }, BI zerlegt und ausgefuehrt.
    Beide Klammern fehlten in der ersten Fassung der Delimiterklasse."""
    content = b"q" + delimiter + b"BI /W 65535 /H 65535 /F /DCT\nID \xff\xd8 EI\nQ\n"
    body = _content_stream_pdf(content, compress=compress)
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(body)


@pytest.mark.parametrize("delimiter", [b"%", b"(", b"/", b"<", b"["])
def test_the_five_text_opening_delimiters_are_deliberately_not_in_the_class(delimiter):
    """Nach % ( / < [ ist "BI" Kommentartext, Zeichenkettentext, Namensrest,
    Hex-String oder Array-Element -- nie ein Operator. Sie aufzunehmen wuerde
    einen Lieferschein mit dem Text "(BI 42)" ablehnen."""
    from app.services.binary_validation import _reject_inline_images

    _reject_inline_images(delimiter + b"BI /W 1")


def test_a_delivery_note_containing_the_token_bi_in_a_string_is_still_a_document():
    body = _content_stream_pdf(b"BT /F1 12 Tf (Lager (BI 42) Regal 7) Tj ET\n")
    assert validate_pdf(body).extension == "pdf"


# --------------------------------------------------------------------------
# Review-Runde 2, I3: befreit wird nur, was NACHWEISLICH kein Inhalt ist
# --------------------------------------------------------------------------

HOSTILE_CONTENT = b"q\nBI /W 65535 /H 65535 /CS /RGB /BPC 8 /F /DCT\nID \xff\xd8\xff\xe0 EI\nQ\n"


def _flate_stream(writer, payload: bytes, extra: dict):
    deflated = zlib.compress(payload, 9)
    stream = StreamObject()
    for key, value in extra.items():
        stream[NameObject(key)] = value
    stream[NameObject("/Filter")] = NameObject("/FlateDecode")
    stream[NameObject("/Length")] = NumberObject(len(deflated))
    stream._data = deflated
    return writer._add_object(stream)


@pytest.mark.parametrize("claim_image", [False, True])
def test_a_page_without_type_still_has_its_content_stream_scanned(claim_image):
    """Angriff 1: `/Type` weglassen. pypdf meldet die Seite trotzdem und
    liefert ihre Bytes aus -- eine Regel, die auf `/Type == "/Page"` keyt,
    verwandelt das fehlende Feld in eine Befreiung."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    extra = {"/Subtype": NameObject("/Image")} if claim_image else {}
    page[NameObject("/Contents")] = _flate_stream(writer, HOSTILE_CONTENT, extra)
    del page[NameObject("/Type")]
    out = BytesIO()
    writer.write(out)
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(out.getvalue())


@pytest.mark.parametrize("claim_image", [False, True])
def test_a_tiling_pattern_stream_is_scanned(claim_image):
    """Angriff 2: ein konformes Kachelmuster. Ausgefuehrt wird es wegen
    /PatternType 1, nicht wegen /Subtype -- ein angeklebtes /Subtype /Image
    ist bedeutungslos und darf nicht befreien."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    extra = {
        "/Type": NameObject("/Pattern"),
        "/PatternType": NumberObject(1),
        "/PaintType": NumberObject(1),
        "/TilingType": NumberObject(1),
        "/BBox": ArrayObject([NumberObject(0), NumberObject(0), NumberObject(10), NumberObject(10)]),
        "/XStep": NumberObject(10),
        "/YStep": NumberObject(10),
        "/Resources": DictionaryObject(),
    }
    if claim_image:
        extra["/Subtype"] = NameObject("/Image")
    patterns = DictionaryObject()
    patterns[NameObject("/P0")] = _flate_stream(writer, HOSTILE_CONTENT, extra)
    resources = DictionaryObject()
    resources[NameObject("/Pattern")] = patterns
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = _flate_stream(
        writer, b"/Pattern cs /P0 scn 0 0 100 100 re f\n", {}
    )
    out = BytesIO()
    writer.write(out)
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(out.getvalue())


@pytest.mark.parametrize("claim_image", [False, True])
def test_a_type3_charproc_glyph_stream_is_scanned(claim_image):
    """Angriff 3: ein Typ-3-Glyph. /CharProcs-Werte sind Inhaltsstroeme und
    werden unabhaengig von /Subtype ausgefuehrt."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    extra = {"/Subtype": NameObject("/Image")} if claim_image else {}
    procs = DictionaryObject()
    procs[NameObject("/a")] = _flate_stream(writer, HOSTILE_CONTENT, extra)
    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type3")
    font[NameObject("/CharProcs")] = writer._add_object(procs)
    font[NameObject("/FirstChar")] = NumberObject(97)
    font[NameObject("/LastChar")] = NumberObject(97)
    font[NameObject("/Widths")] = ArrayObject([NumberObject(1000)])
    fonts = DictionaryObject()
    fonts[NameObject("/F0")] = writer._add_object(font)
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = _flate_stream(writer, b"BT /F0 12 Tf (a) Tj ET\n", {})
    out = BytesIO()
    writer.write(out)
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(out.getvalue())


def test_a_stream_reachable_both_as_raster_and_as_content_is_scanned():
    """Die Befreiung gilt nur AUSSCHLIESSLICH eingehaengten Rasterbildern.
    Dasselbe Objekt zusaetzlich als /Contents zu verlinken hebt sie auf."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    reference = _flate_stream(
        writer,
        HOSTILE_CONTENT,
        {"/Type": NameObject("/XObject"), "/Subtype": NameObject("/Image")},
    )
    xobjects = DictionaryObject()
    xobjects[NameObject("/Im0")] = reference
    resources = DictionaryObject()
    resources[NameObject("/XObject")] = xobjects
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = reference
    out = BytesIO()
    writer.write(out)
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(out.getvalue())


def test_a_properly_typed_raster_xobject_is_still_exempt():
    """Gegenprobe: das eine, was nachweislich kein Inhalt ist, bleibt vom
    Scan befreit -- sonst kehrt der Fehlalarm auf Rasterbildern zurueck."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    reference = _flate_stream(
        writer,
        _LOOKS_LIKE_BI,
        {
            "/Type": NameObject("/XObject"),
            "/Subtype": NameObject("/Image"),
            "/Width": NumberObject(4),
            "/Height": NumberObject(4),
        },
    )
    xobjects = DictionaryObject()
    xobjects[NameObject("/Im0")] = reference
    resources = DictionaryObject()
    resources[NameObject("/XObject")] = xobjects
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = _flate_stream(
        writer, b"q 100 0 0 100 0 0 cm /Im0 Do Q\n", {}
    )
    out = BytesIO()
    writer.write(out)
    assert validate_pdf(out.getvalue()).extension == "pdf"


def test_a_page_without_type_does_not_escape_the_page_key_allowlist():
    """Dieselbe Wurzel an einer zweiten Stelle: `_check_pdf_shape` keyte
    ebenfalls nur auf /Type, ein /Type-loses Seiten-Dictionary umging damit
    die ganze Schluessel-Allowlist."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    page[NameObject("/Contents")] = _flate_stream(writer, b"q Q\n", {})
    page[NameObject("/AA")] = DictionaryObject()
    del page[NameObject("/Type")]
    out = BytesIO()
    writer.write(out)
    with pytest.raises(BinaryValidationError, match="page key is not allowed"):
        validate_pdf(out.getvalue())


# --------------------------------------------------------------------------
# Review-Runde 3, Critical: die Befreiung entschuldigte ALIASIERTE
# Dictionaries. Ein Dictionary, das gleichzeitig das /Resources -> /XObject-
# Dictionary und etwas anderes ist, stellte seinen ganzen Inhalt frei.
# --------------------------------------------------------------------------

RASTER_KEYS = {"/Type": NameObject("/XObject"), "/Subtype": NameObject("/Image")}


def _stream(writer, payload: bytes, extra: dict, *, compress: bool = True):
    """Ein Stream-Objekt, roh oder Flate-gepackt, als indirekter Verweis."""
    if compress:
        return _flate_stream(writer, payload, extra)
    stream = StreamObject()
    for key, value in extra.items():
        stream[NameObject(key)] = value
    stream[NameObject("/Length")] = NumberObject(len(payload))
    stream._data = payload
    return writer._add_object(stream)


def _a1_charprocs_is_the_xobject_dict(*, compress: bool = True) -> bytes:
    """A1: das /CharProcs eines Typ-3-Fonts IST das /XObject-Dictionary.

    Vollstaendig konformer Typ-3-Font. Der Glyphenstrom traegt /Type /XObject
    und /Subtype /Image, ist aber ein INHALTSSTROM -- ein Interpreter fuehrt
    ihn beim Zeichnen von "a" aus. Die vorige Befreiung uebersprang beim
    Gegenzaehlen alle Verweise des /XObject-Dictionarys, und weil dieses
    Dictionary hier das /CharProcs IST, galt der Glyphenverweis als "kein
    weiterer Verweis".
    """
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    glyph = _stream(writer, HOSTILE_CONTENT, dict(RASTER_KEYS), compress=compress)
    procs = DictionaryObject()
    procs[NameObject("/a")] = glyph
    procs_ref = writer._add_object(procs)

    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type3")
    font[NameObject("/FontBBox")] = ArrayObject(
        [NumberObject(0), NumberObject(0), NumberObject(10), NumberObject(10)]
    )
    font[NameObject("/FontMatrix")] = ArrayObject(
        [
            NumberObject(1), NumberObject(0), NumberObject(0),
            NumberObject(1), NumberObject(0), NumberObject(0),
        ]
    )
    font[NameObject("/CharProcs")] = procs_ref
    font[NameObject("/Encoding")] = DictionaryObject()
    font[NameObject("/FirstChar")] = NumberObject(97)
    font[NameObject("/LastChar")] = NumberObject(97)
    font[NameObject("/Widths")] = ArrayObject([NumberObject(1000)])

    fonts = DictionaryObject()
    fonts[NameObject("/F0")] = writer._add_object(font)
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts
    # DER ALIAS: dasselbe Dictionary ist /CharProcs UND /XObject-Dictionary.
    resources[NameObject("/XObject")] = procs_ref
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = _flate_stream(writer, b"BT /F0 12 Tf (a) Tj ET\n", {})
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _a2_page_is_the_xobject_dict(*, compress: bool = True) -> bytes:
    """A2: das Seiten-Dictionary selbst haengt als /Resources -> /XObject.

    Damit zaehlt sein eigenes /Contents nicht mehr als "weiterer Verweis" --
    der Inhaltsstrom der Seite wurde vom Scan befreit. `compress=False` ist
    zugleich der Nachweis, dass Phase 1 hier nichts abfaengt: sie ueberspringt
    Stream-Nutzdaten, dieser Fall war also in BEIDEN Phasen unsichtbar.
    """
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    page[NameObject("/Contents")] = _stream(
        writer, HOSTILE_CONTENT, dict(RASTER_KEYS), compress=compress
    )
    resources = DictionaryObject()
    # DER ALIAS.
    resources[NameObject("/XObject")] = page.indirect_reference
    page[NameObject("/Resources")] = resources
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _a3_pattern_is_the_xobject_dict(*, compress: bool = True) -> bytes:
    """A3: ein /Pattern-Dictionary IST das /XObject-Dictionary."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    extra = dict(RASTER_KEYS)
    extra.update(
        {
            "/PatternType": NumberObject(1),
            "/PaintType": NumberObject(1),
            "/TilingType": NumberObject(1),
            "/BBox": ArrayObject(
                [NumberObject(0), NumberObject(0), NumberObject(10), NumberObject(10)]
            ),
            "/XStep": NumberObject(10),
            "/YStep": NumberObject(10),
            "/Resources": DictionaryObject(),
        }
    )
    patterns = DictionaryObject()
    patterns[NameObject("/P0")] = _stream(writer, HOSTILE_CONTENT, extra, compress=compress)
    patterns_ref = writer._add_object(patterns)
    resources = DictionaryObject()
    resources[NameObject("/Pattern")] = patterns_ref
    # DER ALIAS.
    resources[NameObject("/XObject")] = patterns_ref
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = _flate_stream(
        writer, b"/Pattern cs /P0 scn 0 0 100 100 re f\n", {}
    )
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _a4_xobject_dict_on_a_non_resources_parent(*, compress: bool = True) -> bytes:
    """A4: das /XObject-Dictionary haengt an etwas, das kein /Resources ist.

    Kein Alias, sondern die zweite Haelfte derselben Regel: die Befreiung darf
    nur ein ECHTER /Resources -> /XObject-Platz erteilen. Ohne diese Klausel
    genuegt es, den Schluessel /XObject an ein beliebiges Dictionary zu haengen.
    """
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    holder = DictionaryObject()
    holder[NameObject("/Im0")] = _stream(
        writer, HOSTILE_CONTENT, dict(RASTER_KEYS), compress=compress
    )
    carrier = DictionaryObject()
    carrier[NameObject("/Type")] = NameObject("/Font")
    carrier[NameObject("/Subtype")] = NameObject("/Type1")
    carrier[NameObject("/BaseFont")] = NameObject("/Helvetica")
    carrier[NameObject("/XObject")] = writer._add_object(holder)
    fonts = DictionaryObject()
    fonts[NameObject("/F0")] = writer._add_object(carrier)
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = _flate_stream(writer, b"BT /F0 12 Tf (x) Tj ET\n", {})
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


ALIASED_SLOT_ATTACKS = {
    "a1-charprocs-is-the-xobject-dict": _a1_charprocs_is_the_xobject_dict,
    "a2-page-is-the-xobject-dict": _a2_page_is_the_xobject_dict,
    "a3-pattern-is-the-xobject-dict": _a3_pattern_is_the_xobject_dict,
    "a4-xobject-dict-on-a-non-resources-parent": _a4_xobject_dict_on_a_non_resources_parent,
}


@pytest.mark.parametrize("attack", sorted(ALIASED_SLOT_ATTACKS))
@pytest.mark.parametrize("compress", [False, True])
def test_an_aliased_raster_slot_earns_no_exemption(attack, compress):
    """Alle vier Formen wurden von `validate_pdf` bei 879037f AKZEPTIERT."""
    body = ALIASED_SLOT_ATTACKS[attack](compress=compress)
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(body)


@pytest.mark.parametrize("attack", sorted(ALIASED_SLOT_ATTACKS))
def test_the_exemption_set_is_empty_for_every_aliased_slot(attack):
    """Dieselbe Aussage eine Ebene tiefer, damit ein spaeterer Umbau nicht aus
    Versehen an einer anderen Stelle abweist und die Befreiung still oeffnet:
    fuer diese Dokumente darf `_exempt_raster_idnums` NICHTS befreien."""
    from pypdf import PdfReader

    from app.services.binary_validation import _exempt_raster_idnums

    reader = PdfReader(BytesIO(ALIASED_SLOT_ATTACKS[attack]()), strict=True)
    catalog = reader.trailer["/Root"].get_object()
    assert _exempt_raster_idnums(catalog) == set()


def test_the_alias_is_only_visible_because_edges_key_on_the_object_number():
    """Warum die Kantenbuchhaltung auf der OBJEKTNUMMER keyt und nicht auf
    `id()`: zwei Vorkommen von "6 0 R" in der Datei sind zwei verschiedene
    Python-Objekte. Mit `id()` bleiben ihre Etiketten getrennt, das Dictionary
    sieht an jeder Stelle unaliast aus -- und genau diese Vermischung war der
    Bruch der Moduldisziplin, den die vorige Fassung begangen hat."""
    from pypdf import PdfReader

    from app.services.binary_validation import (
        _node_identity,
        _pdf_reference_map,
    )
    import app.services.binary_validation as module

    reader = PdfReader(BytesIO(_a1_charprocs_is_the_xobject_dict()), strict=True)
    catalog = reader.trailer["/Root"].get_object()

    labels, _, _ = _pdf_reference_map(catalog)
    assert {"/CharProcs", "/XObject"} in [set(value) for value in labels.values()]

    original = module._node_identity
    try:
        module._node_identity = lambda value: ("id", id(value))
        blind, _, _ = _pdf_reference_map(catalog)
    finally:
        module._node_identity = original
    assert all(len(value) == 1 for value in blind.values())

    # Und die Eigenschaft selbst, direkt behauptet: zwei verschiedene
    # IndirectObject-Instanzen auf dasselbe Objekt sind EIN Knoten.
    first = ArrayObject()
    reference_a = reader.pages[0].raw_get("/Contents")
    reference_b = IndirectObject(reference_a.idnum, reference_a.generation, reader)
    assert reference_a is not reference_b
    assert _node_identity(reference_a) == _node_identity(reference_b)
    assert _node_identity(reference_a) == ("idnum", reference_a.idnum)
    assert _node_identity(first) != _node_identity(ArrayObject())


def test_an_array_element_inside_an_xobject_dictionary_earns_no_exemption():
    """Ein Array-Element ist kein Bildplatz. Es als solchen zu zaehlen waere
    wieder ein Beweisloch, das zur Befreiung wird."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    xobjects = DictionaryObject()
    xobjects[NameObject("/Im0")] = ArrayObject(
        [_flate_stream(writer, HOSTILE_CONTENT, dict(RASTER_KEYS))]
    )
    resources = DictionaryObject()
    resources[NameObject("/XObject")] = xobjects
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = _flate_stream(writer, b"q Q\n", {})
    out = BytesIO()
    writer.write(out)
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(out.getvalue())


def test_one_raster_shared_by_two_pages_is_still_exempt():
    """Gegenprobe zur strengeren Regel: ein Rasterbild, das ZWEI Seiten
    benutzen, wird ueber zwei verschiedene /Resources -> /XObject-Plaetze
    erreicht. Beide Plaetze sind unaliast, die Befreiung bleibt -- sonst waere
    aus der Verscharfung ein Fehlalarm auf voellig gueltigen Dokumenten
    geworden."""
    writer = PdfWriter()
    reference = _flate_stream(
        writer,
        _LOOKS_LIKE_BI,
        {
            "/Type": NameObject("/XObject"),
            "/Subtype": NameObject("/Image"),
            "/Width": NumberObject(4),
            "/Height": NumberObject(4),
        },
    )
    for _ in range(2):
        page = writer.add_blank_page(width=100, height=100)
        xobjects = DictionaryObject()
        xobjects[NameObject("/Im0")] = reference
        resources = DictionaryObject()
        resources[NameObject("/XObject")] = xobjects
        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = _flate_stream(
            writer, b"q 100 0 0 100 0 0 cm /Im0 Do Q\n", {}
        )
    out = BytesIO()
    writer.write(out)
    assert validate_pdf(out.getvalue()).extension == "pdf"


# --------------------------------------------------------------------------
# Review-Runde 4, Critical (FINDING 1): die Kantenbuchhaltung lief nicht ueber
# ARRAYS. Abgeleitet wird hier nicht aus der gemeldeten Form, sondern aus dem
# Objektmodell von ISO 32000-1, 7.3: es gibt genau zwei Container, in denen
# eine Referenz stecken kann (Array 7.3.6, Dictionary/Stream 7.3.7/7.3.8), und
# Referenzen (7.3.10) koennen darin beliebig tief und selbst indirekt liegen.
# Jede Kombination davon ist unten ein Dokument.
# --------------------------------------------------------------------------


def _raw_pdf(objects: list[bytes]) -> bytes:
    """Ein PDF mit korrekter xref-Tabelle aus fertigen Objektkoerpern.

    Fuer Formen, die pypdfs Writer nicht schreiben KANN -- ein indirektes
    Objekt, dessen Wert selbst eine Referenz ist, faltet der Writer zusammen.
    """
    body = b"%PDF-1.7\n"
    offsets = []
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % index + payload + b"\nendobj\n"
    start = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        body += b"%010d 00000 n \n" % offset
    return body + b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        start,
    )


def _hostile_raster_stream_body(compress: bool) -> bytes:
    payload = zlib.compress(HOSTILE_CONTENT, 9) if compress else HOSTILE_CONTENT
    return (
        b"<</Type/XObject/Subtype/Image"
        + (b"/Filter/FlateDecode" if compress else b"")
        + b"/Length %d>>stream\n" % len(payload)
        + payload
        + b"\nendstream"
    )


def _raster_slot(page, reference) -> None:
    xobjects = DictionaryObject()
    xobjects[NameObject("/Im0")] = reference
    resources = DictionaryObject()
    resources[NameObject("/XObject")] = xobjects
    page[NameObject("/Resources")] = resources


def _c1_indirect_contents_array(*, compress: bool = True) -> bytes:
    """A5, die gemeldete Form: /Contents ist eine indirekte Referenz auf ein
    ARRAY. ISO 32000-1, Tabelle 30: /Contents darf ein Stream, ein Array von
    Streams oder eine indirekte Referenz auf beides sein. Die Kante war
    unsichtbar, weil die Karte bei jedem aufgeloesten Nicht-Dictionary abbrach
    -- der Strom sah aus, als haenge er nur im Bildplatz."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    hostile = _stream(writer, HOSTILE_CONTENT, dict(RASTER_KEYS), compress=compress)
    page[NameObject("/Contents")] = writer._add_object(ArrayObject([hostile]))
    _raster_slot(page, hostile)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _c2_nested_indirect_arrays(*, compress: bool = True) -> bytes:
    """Array im Array, beide indirekt (7.3.6: Arrays duerfen Arrays enthalten)."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    hostile = _stream(writer, HOSTILE_CONTENT, dict(RASTER_KEYS), compress=compress)
    inner = writer._add_object(ArrayObject([hostile]))
    page[NameObject("/Contents")] = writer._add_object(ArrayObject([inner]))
    _raster_slot(page, hostile)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _c3_direct_array_holding_an_indirect_array(*, compress: bool = True) -> bytes:
    """Direktes Array, dessen Element ein INDIREKTES Array ist -- die Mischform,
    die eine Regel "nur direkte Arrays durchlaufen" genau verpasst."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    hostile = _stream(writer, HOSTILE_CONTENT, dict(RASTER_KEYS), compress=compress)
    inner = writer._add_object(ArrayObject([hostile]))
    page[NameObject("/Contents")] = ArrayObject([inner])
    _raster_slot(page, hostile)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _c4_page_only_reachable_through_an_indirect_kids_array(
    *, compress: bool = True
) -> bytes:
    """Ein DICTIONARY, das nur ueber ein indirektes Array erreichbar ist.

    /Kids ist eine indirekte Referenz auf das Array; die zweite Seite darin
    fuehrt den Strom als Inhalt aus. Bei 0e58053 verlor die Karte an dieser
    Kante den GESAMTEN Seitenbaum -- der Strom wurde damals zufaellig
    gescannt, weil ohne Seitenbaum auch kein /XObject-Platz sichtbar war. Die
    Karte war also nicht streng, sondern blind; das ist der Unterschied, den
    der Obermengen-Test unten festhaelt."""
    writer = PdfWriter()
    host = writer.add_blank_page(width=100, height=100)
    hostile = _stream(writer, HOSTILE_CONTENT, dict(RASTER_KEYS), compress=compress)
    _raster_slot(host, hostile)
    host[NameObject("/Contents")] = _flate_stream(
        writer, b"q 100 0 0 100 0 0 cm /Im0 Do Q\n", {}
    )
    pages = writer._root_object["/Pages"]
    victim = DictionaryObject()
    victim[NameObject("/Type")] = NameObject("/Page")
    victim[NameObject("/MediaBox")] = ArrayObject(
        [NumberObject(0), NumberObject(0), NumberObject(100), NumberObject(100)]
    )
    victim[NameObject("/Parent")] = pages.indirect_reference
    victim[NameObject("/Contents")] = hostile
    kids = ArrayObject(list(pages["/Kids"]) + [writer._add_object(victim)])
    pages[NameObject("/Kids")] = writer._add_object(kids)
    pages[NameObject("/Count")] = NumberObject(2)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _c5_indirect_array_inside_the_xobject_dictionary(*, compress: bool = True) -> bytes:
    """Wie der Array-Element-Fall aus Runde 3, aber das Array ist indirekt --
    das Sentinel-Etikett muss auch dann greifen."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    hostile = _stream(writer, HOSTILE_CONTENT, dict(RASTER_KEYS), compress=compress)
    xobjects = DictionaryObject()
    xobjects[NameObject("/Im0")] = writer._add_object(ArrayObject([hostile]))
    resources = DictionaryObject()
    resources[NameObject("/XObject")] = xobjects
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = _flate_stream(writer, b"q Q\n", {})
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _c6_self_referential_indirect_array(*, compress: bool = True) -> bytes:
    """Ein indirektes Array, das SICH SELBST enthaelt, und daneben den Strom.

    Kein Angriff auf die Befreiung, sondern auf den Durchlauf: ohne
    Zyklenschutz im Array-Zweig laeuft der Validator endlos. Der Strom haengt
    zugleich im Bildplatz, damit der Fall trotzdem eine Aussage ueber die
    Befreiung macht."""
    return _raw_pdf(
        [
            b"<</Type/Catalog/Pages 2 0 R>>",
            b"<</Type/Pages/Count 1/Kids[3 0 R]>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]"
            b"/Resources<</XObject<</Im0 5 0 R>>>>/Contents 4 0 R>>",
            b"[4 0 R 5 0 R]",
            _hostile_raster_stream_body(compress),
        ]
    )


CONTAINER_ATTACKS = {
    "c1-indirect-contents-array": _c1_indirect_contents_array,
    "c2-nested-indirect-arrays": _c2_nested_indirect_arrays,
    "c3-direct-array-holding-an-indirect-array": _c3_direct_array_holding_an_indirect_array,
    "c4-page-only-behind-an-indirect-kids-array": (
        _c4_page_only_reachable_through_an_indirect_kids_array
    ),
    "c5-indirect-array-inside-the-xobject-dictionary": (
        _c5_indirect_array_inside_the_xobject_dictionary
    ),
    "c6-self-referential-indirect-array": _c6_self_referential_indirect_array,
}


@pytest.mark.parametrize("attack", sorted(CONTAINER_ATTACKS))
@pytest.mark.parametrize("compress", [False, True])
def test_no_container_can_hide_the_edge_that_makes_a_stream_content(attack, compress):
    """c1, c2 und c3 wurden bei 0e58053 AKZEPTIERT (679/724/683 B roh)."""
    body = CONTAINER_ATTACKS[attack](compress=compress)
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_pdf(body)


@pytest.mark.parametrize("attack", sorted(CONTAINER_ATTACKS))
def test_the_exemption_set_is_empty_for_every_container_attack(attack):
    """Dieselbe Aussage eine Ebene tiefer -- damit ein spaeterer Umbau nicht
    aus einem anderen Grund abweist und die Befreiung still wieder oeffnet."""
    from pypdf import PdfReader

    from app.services.binary_validation import _exempt_raster_idnums

    reader = PdfReader(BytesIO(CONTAINER_ATTACKS[attack]()), strict=True)
    assert _exempt_raster_idnums(reader.trailer["/Root"].get_object()) == set()


def test_a_legitimate_indirect_contents_array_keeps_its_raster_exemption():
    """Gegenprobe, und die wichtigste: /Contents als indirektes Array von zwei
    Inhaltsstroemen ist voellig gewoehnliches PDF. Das Rasterbild daneben muss
    befreit BLEIBEN -- sonst waere aus dem Schliessen der Luecke ein Fehlalarm
    auf echten Dokumenten geworden."""
    writer = PdfWriter()
    raster = _flate_stream(
        writer,
        _LOOKS_LIKE_BI,
        {
            "/Type": NameObject("/XObject"),
            "/Subtype": NameObject("/Image"),
            "/Width": NumberObject(4),
            "/Height": NumberObject(4),
        },
    )
    for _ in range(2):
        page = writer.add_blank_page(width=100, height=100)
        _raster_slot(page, raster)
        parts = ArrayObject(
            [
                _flate_stream(writer, b"q 100 0 0 100 0 0 cm /Im0 Do Q\n", {}),
                _flate_stream(writer, b"q 1 0 0 1 10 10 cm 0 0 5 5 re f Q\n", {}),
            ]
        )
        page[NameObject("/Contents")] = writer._add_object(parts)
    out = BytesIO()
    writer.write(out)
    body = out.getvalue()
    assert validate_pdf(body).extension == "pdf"

    from pypdf import PdfReader

    from app.services.binary_validation import _exempt_raster_idnums

    reader = PdfReader(BytesIO(body), strict=True)
    assert _exempt_raster_idnums(reader.trailer["/Root"].get_object()) == {
        raster.idnum
    }


# --------------------------------------------------------------------------
# Review-Runde 4, der eigentliche Ertrag: die Erreichbarkeit der
# Kantenbuchhaltung MUSS eine Obermenge der Knotenliste sein. Dreimal wurde
# eine einzelne Form geschlossen und die Beziehung blieb ungeprueft; hier wird
# die Beziehung selbst behauptet.
# --------------------------------------------------------------------------


class _FakeDocument:
    """Minimaler Ersatz fuer einen Reader: loest Objektnummern aus einer Tabelle
    auf. Damit sind Formen pruefbar, die pypdf gar nicht parst."""

    def __init__(self, objects: dict):
        self._objects = objects

    def get_object(self, reference):
        return self._objects[reference.idnum]


def _iso_container_cases():
    """Jeder Container aus ISO 32000-1, 7.3, in dem eine Referenz stecken kann.

    Erwartet wird jeweils die Etikettenmenge, die `_labelled_children` fuer das
    Ziel-Dictionary aufspannen MUSS. Die Tabelle ist die Ableitung selbst -- wer
    einen Containertyp streicht, streicht hier eine Zeile und sieht ROT.
    """
    target = DictionaryObject()
    target[NameObject("/Marker")] = NameObject("/Target")
    docs = {}

    def indirect(number, value):
        docs[number] = value
        return IndirectObject(number, 0, _FakeDocument(docs))

    reference = indirect(1, target)
    cases = [
        ("7.3.7 direct dictionary value", target, {"/Contents"}),
        ("7.3.10 indirect dictionary value", reference, {"/Contents"}),
        ("7.3.6 direct array", ArrayObject([reference]), {"<array element>"}),
        (
            "7.3.6 nested direct arrays",
            ArrayObject([ArrayObject([ArrayObject([reference])])]),
            {"<array element>"},
        ),
        ("7.3.6+7.3.10 indirect array", indirect(2, ArrayObject([reference])), {"<array element>"}),
        (
            "7.3.6+7.3.10 indirect array of indirect arrays",
            indirect(3, ArrayObject([indirect(4, ArrayObject([reference]))])),
            {"<array element>"},
        ),
        (
            "7.3.6 direct array holding an indirect array",
            ArrayObject([indirect(5, ArrayObject([reference]))]),
            {"<array element>"},
        ),
        (
            "7.3.10 reference chain to a dictionary",
            indirect(6, IndirectObject(1, 0, _FakeDocument(docs))),
            {"/Contents"},
        ),
        (
            "7.3.10 reference chain to an array",
            indirect(7, IndirectObject(2, 0, _FakeDocument(docs))),
            {"<array element>"},
        ),
        # Nicht-Container: 7.3.2 Boolean, 7.3.3 Zahl, 7.3.4 String, 7.3.5 Name,
        # 7.3.9 Null koennen keine Referenz enthalten.
        ("7.3.3 number", NumberObject(42), set()),
        ("7.3.5 name", NameObject("/Nothing"), set()),
        ("7.3.4 string", TextStringObject("nothing"), set()),
    ]
    return [(name, value, expected, target) for name, value, expected in cases]


@pytest.mark.parametrize(
    "case", _iso_container_cases(), ids=[case[0] for case in _iso_container_cases()]
)
def test_every_iso_container_that_can_hide_a_reference_spans_an_edge(case):
    _, value, expected, target = case
    from app.services.binary_validation import _labelled_children

    edges = list(_labelled_children("/Contents", value))
    found = {
        label
        for label, link in edges
        if (link is target or getattr(link, "idnum", None) == 1)
    }
    assert found == expected


def _graph_corpus() -> dict:
    """Alles, was dieses Modul an Dokumenten bauen kann -- feindlich und echt."""
    corpus = {
        "minimal": pdf_bytes(),
        "content-stream": _content_stream_pdf(b"q Q\n", compress=True),
        "raster-xobject": _pdf_with_image_xobject(_LOOKS_LIKE_BI, as_page_contents=False),
    }
    for name, builder in ALIASED_SLOT_ATTACKS.items():
        corpus[name] = builder()
    for name, builder in CONTAINER_ATTACKS.items():
        corpus[name] = builder()
    return corpus


GRAPH_CORPUS = _graph_corpus()


@pytest.mark.parametrize("document", sorted(GRAPH_CORPUS))
def test_the_reference_map_reaches_every_node_the_node_walk_reaches(document):
    """DIE Invariante dieser Runde. Drei Runden lang wurde eine gemeldete Form
    geschlossen und die Beziehung zwischen den beiden Durchlaeufen blieb
    unbehauptet -- jedes Mal fand die naechste Runde eine Form, die der eine
    Durchlauf sah und der andere nicht. Was `_pdf_nodes` erreicht, MUSS die
    Kantenbuchhaltung auch erreichen; andernfalls wird eine Befreiung auf einem
    unvollstaendigen Graphen erteilt, und der Interpreter widerlegt sie."""
    from pypdf import PdfReader

    from app.services.binary_validation import _pdf_nodes, _pdf_reference_map

    reader = PdfReader(BytesIO(GRAPH_CORPUS[document]), strict=True)
    catalog = reader.trailer["/Root"].get_object()
    _, _, dictionaries = _pdf_reference_map(catalog)

    walked = set()
    for node, idnum in _pdf_nodes(catalog):
        key = ("idnum", idnum) if idnum is not None else ("direct", id(node))
        assert key in dictionaries, (
            f"{document}: {key} ({node.get('/Type', '<no /Type>')}) is reachable for "
            "the node walk but invisible to the edge accounting"
        )
        walked.add(key)
    # Und in die andere Richtung, damit die Obermenge keine echte Obermenge
    # wird: beide Sichten kommen aus DEMSELBEN Durchlauf.
    assert set(dictionaries) == walked


def test_both_traversals_are_views_of_the_same_walk():
    """Warum die Invariante oben nicht bloss zufaellig gilt: es gibt nur EINEN
    Durchlauf. Wird `_pdf_walk` manipuliert, muessen BEIDE Konsumenten das
    sehen. Wer einem von ihnen wieder einen eigenen Durchlauf gibt, faellt hier
    durch -- und nicht erst in der naechsten Review-Runde."""
    from pypdf import PdfReader

    import app.services.binary_validation as module

    reader = PdfReader(BytesIO(GRAPH_CORPUS["raster-xobject"]), strict=True)
    catalog = reader.trailer["/Root"].get_object()
    complete = {
        record[1] for record in module._pdf_walk(catalog) if record[0] == module._PDF_NODE
    }
    assert len(complete) > 2

    original = module._pdf_walk
    dropped = sorted(complete, key=str)[-1]

    def crippled(root):
        for record in original(root):
            if record[0] == module._PDF_NODE and record[1] == dropped:
                continue
            yield record

    try:
        module._pdf_walk = crippled
        nodes = {
            ("idnum", idnum) if idnum is not None else ("direct", id(node))
            for node, idnum in module._pdf_nodes(catalog)
        }
        _, _, dictionaries = module._pdf_reference_map(catalog)
    finally:
        module._pdf_walk = original

    assert dropped not in nodes
    assert dropped not in dictionaries
    assert nodes == set(dictionaries)


def test_a_reference_chain_is_followed_to_its_last_indirect_link():
    """ISO 32000-1, 7.3.10: der Wert eines indirekten Objekts darf selbst eine
    Referenz sein. Die Kante muss am LETZTEN Glied haengen, sonst steht ein
    Zwischenglied als eigener Knoten zwischen Kante und Ziel und schluckt
    dessen Etiketten."""
    from app.services.binary_validation import _node_identity, _resolve_reference

    target = DictionaryObject()
    docs: dict = {}
    document = _FakeDocument(docs)
    docs[3] = target
    docs[2] = IndirectObject(3, 0, document)
    docs[1] = IndirectObject(2, 0, document)

    link, resolved = _resolve_reference(IndirectObject(1, 0, document), lambda: None)
    assert resolved is target
    assert _node_identity(link) == ("idnum", 3)

    # Eine Kette im Kreis liefert kein Ziel -- die strenge Richtung: ohne Ziel
    # gibt es keinen Knoten, der eine Befreiung bekommen koennte.
    docs[9] = IndirectObject(9, 0, document)
    assert _resolve_reference(IndirectObject(9, 0, document), lambda: None) == (None, None)


def test_pypdf_refuses_an_indirect_object_whose_value_is_a_reference():
    """Dokumentiert, warum die Kette oben nur als Unit-Test auftaucht: pypdf
    5.9 kann sie nicht aufloesen und `validate_pdf` weist sie deshalb schon am
    Parser ab. Das ist fail-closed, aber KEIN Verlass -- `_resolve_reference`
    folgt der Kette trotzdem, damit ein tolerantere Parser keine Luecke
    aufmacht. Sollte diese Erwartung eines Tages kippen, sagt der Test es."""
    body = _raw_pdf(
        [
            b"<</Type/Catalog/Pages 2 0 R>>",
            b"<</Type/Pages/Count 1/Kids[3 0 R]>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]"
            b"/Resources<</XObject<</Im0 5 0 R>>>>/Contents 4 0 R>>",
            b"5 0 R",
            _hostile_raster_stream_body(False),
        ]
    )
    with pytest.raises(BinaryValidationError):
        validate_pdf(body)


def test_the_graph_step_budget_stops_an_indirect_array_cross_product():
    """`MAX_PDF_OBJECTS` deckelt nur Dictionaries. Ohne den zweiten Deckel
    genuegen 96 KB, um 400 Dictionaries auf dieselbe Kette von 1200 indirekten
    Arrays zeigen zu lassen: 480.000 Schritte ohne einen einzigen zusaetzlichen
    Knoten. Gemessen: mit Deckel 0,24 s, ohne Deckel 20 s bei 10 Mio. Schritten
    -- ein CPU-Verbrauchsangriff auf den Validator selbst."""
    from app.services.binary_validation import MAX_PDF_GRAPH_STEPS

    carriers, chain = 400, 1200
    first_chain = 4 + carriers
    annots = b"[" + b" ".join(b"%d 0 R" % (4 + i) for i in range(carriers)) + b"]"
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Count 1/Kids[3 0 R]>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 10 10]/Annots" + annots + b">>",
    ]
    objects += [
        b"<</Subtype/Link/Rect[0 0 1 1]/QuadPoints %d 0 R>>" % first_chain
    ] * carriers
    objects += [
        b"[%d 0 R]" % (first_chain + index + 1) if index < chain - 1 else b"[0 0 1 1]"
        for index in range(chain)
    ]
    assert carriers * chain > MAX_PDF_GRAPH_STEPS
    with pytest.raises(BinaryValidationError, match="object graph is too large"):
        validate_pdf(_raw_pdf(objects))


def _independent_reachability(root) -> dict:
    """Erreichbarkeit, hier im TEST nachgebaut und bewusst naiv.

    Warum das noetig ist: seit `_pdf_nodes` und `_pdf_reference_map` beide auf
    `_pdf_walk` sitzen, ist "die Kanten erreichen mindestens die Knoten"
    zwischen ihnen per Konstruktion wahr -- ein Loch IM gemeinsamen Durchlauf
    wuerde beide Sichten gleichzeitig verkleinern und faellt zwischen ihnen
    nicht auf. Dieses Orakel ist deshalb vom Modul unabhaengig und direkt aus
    ISO 32000-1, 7.3 geschrieben: Dictionary-Werte, Array-Elemente (beliebig
    tief, direkt wie indirekt) und Referenzketten. Es kennt keine Deckel und
    keine Befreiung -- es sagt nur, welche Dictionaries eine konforme
    Anwendung erreichen kann.
    """
    found: dict = {}

    def key_of(value):
        if isinstance(value, IndirectObject):
            return ("idnum", value.idnum)
        return ("direct", id(value))

    def visit(value, open_arrays: frozenset) -> None:
        link = value
        guard: set = set()
        while isinstance(link, IndirectObject):
            if link.idnum in guard:
                return
            guard.add(link.idnum)
            resolved = link.get_object()
            if isinstance(resolved, IndirectObject):
                link = resolved
                continue
            target = resolved
            break
        else:
            target = link
        key = key_of(link)
        if isinstance(target, DictionaryObject):
            if key in found:
                return
            found[key] = target
            for child in target.values():
                visit(child, open_arrays)
        elif isinstance(target, (list, tuple)):
            if key in open_arrays:
                return
            for element in target:
                visit(element, open_arrays | {key})

    visit(root, frozenset())
    return found


@pytest.mark.parametrize("document", sorted(GRAPH_CORPUS))
def test_the_reference_map_reaches_everything_an_independent_walk_reaches(document):
    """Der Obermengen-Test mit Zaehnen: gegen ein Orakel, das nicht aus dem
    Modul kommt. Genau hier waere jede der drei vorigen Runden aufgeflogen."""
    from pypdf import PdfReader

    from app.services.binary_validation import _pdf_reference_map

    reader = PdfReader(BytesIO(GRAPH_CORPUS[document]), strict=True)
    catalog = reader.trailer["/Root"].get_object()
    oracle = _independent_reachability(catalog)
    _, _, dictionaries = _pdf_reference_map(catalog)
    missing = {
        key: str(node.get("/Type", "<no /Type>")) for key, node in oracle.items()
        if key not in dictionaries
    }
    assert not missing, (
        f"{document}: reachable for a conforming interpreter, invisible to the "
        f"edge accounting: {missing}"
    )


def _independent_edges(root) -> list:
    """Dieselbe naive Erreichbarkeit wie oben, aber als KANTENLISTE.

    Dient dem Nachweis der Vorbedingung, die der Phase-1-Hebel in seinem
    eigenen Docstring behauptet: "ein Strom, den Phase 3 nicht scannt, ist
    nachweislich kein Inhalt". Der Nachweis darf nicht aus derselben
    Kantenbuchhaltung stammen, die die Befreiung erteilt -- sonst prueft die
    Regel sich selbst.
    """
    edges: list = []
    expanded: set = set()

    def key_of(value):
        if isinstance(value, IndirectObject):
            return ("idnum", value.idnum)
        return ("direct", id(value))

    def visit(parent, label, value, open_arrays: frozenset) -> None:
        link = value
        guard: set = set()
        while isinstance(link, IndirectObject):
            if link.idnum in guard:
                return
            guard.add(link.idnum)
            resolved = link.get_object()
            if isinstance(resolved, IndirectObject):
                link = resolved
                continue
            target = resolved
            break
        else:
            target = link
        key = key_of(link)
        if isinstance(target, DictionaryObject):
            edges.append((parent, label, key))
            if key in expanded:
                return
            expanded.add(key)
            for name, child in target.items():
                visit(key, str(name), child, frozenset())
        elif isinstance(target, (list, tuple)):
            if key in open_arrays:
                return
            for element in target:
                visit(parent, "<array element>", element, open_arrays | {key})

    visit(None, "<root>", root, frozenset())
    return edges


@pytest.mark.parametrize("document", sorted(GRAPH_CORPUS))
def test_every_stream_phase_three_skips_is_provably_not_content(document):
    """FINDING 3, die Vorbedingung des Phase-1-Hebels, unabhaengig nachgerechnet.

    Der Hebel darf Stream-Nutzdaten in Phase 1 ueberspringen, WEIL Phase 3
    jeden Strom scannt, der Inhalt sein koennte. Bei 0e58053 war das falsch:
    ein befreiter Strom mit unkomprimiertem Inhalt war in beiden Phasen
    unsichtbar. Hier wird fuer jedes Dokument des Korpus geprueft, dass jeder
    von Phase 3 uebersprungene Strom AUF DER UNABHAENGIGEN Kantenliste nur
    ueber /Resources -> /XObject erreichbar ist -- also nur per `Do` als
    Pixelraster gezeichnet und nie als Inhalt ausgefuehrt werden kann."""
    from pypdf import PdfReader

    from app.services.binary_validation import _exempt_raster_idnums

    reader = PdfReader(BytesIO(GRAPH_CORPUS[document]), strict=True)
    catalog = reader.trailer["/Root"].get_object()
    edges = _independent_edges(catalog)

    def labels_of(key):
        return {label for _, label, child in edges if child == key}

    def parents_of(key):
        return {parent for parent, _, child in edges if child == key}

    for idnum in _exempt_raster_idnums(catalog):
        key = ("idnum", idnum)
        incoming = labels_of(key)
        assert incoming, f"{document}: exempt stream {idnum} has no incoming edge"
        assert all(label.startswith("/") for label in incoming), (
            f"{document}: exempt stream {idnum} is reached as {incoming}"
        )
        assert not incoming & {"/Contents", "/CharProcs", "/Pattern"}
        for holder in parents_of(key):
            assert labels_of(holder) == {"/XObject"}, (
                f"{document}: exempt stream {idnum} hangs in {labels_of(holder)}"
            )
            for owner in parents_of(holder):
                assert labels_of(owner) == {"/Resources"}


def test_the_exemption_is_not_vacuously_empty_across_the_corpus():
    """Gegenprobe zum Test darueber: waere die Befreiung ueberall leer, waere
    seine Aussage wertlos (und der Scan-Fehlalarm auf Rastern zurueck)."""
    from pypdf import PdfReader

    from app.services.binary_validation import _exempt_raster_idnums

    reader = PdfReader(BytesIO(GRAPH_CORPUS["raster-xobject"]), strict=True)
    assert _exempt_raster_idnums(reader.trailer["/Root"].get_object())


@pytest.mark.parametrize("attack", sorted(CONTAINER_ATTACKS))
def test_the_container_attacks_are_a_phase_three_catch_not_a_phase_one_one(attack):
    """Der Vertrag der Phasenteilung, an genau den Formen, die ihn brachen: die
    unkomprimierte Variante darf Phase 1 passieren (sie ueberspringt
    Stream-Nutzdaten) und MUSS in Phase 3 auffallen."""
    body = CONTAINER_ATTACKS[attack](compress=False)
    precheck_artifact("pdf", body, declared_mime="application/pdf")
    with pytest.raises(BinaryValidationError, match="inline image"):
        validate_artifact("pdf", body, declared_mime="application/pdf")
