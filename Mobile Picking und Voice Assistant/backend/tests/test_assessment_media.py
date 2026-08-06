"""Bildaufbereitung vor dem Modellaufruf.

Zwei Dinge entscheiden hier ueber Funktionieren und Nichtfunktionieren, beide
gemessen:

* Der in Odoo gespeicherte MIME luegt. `api_create_alert` schrieb jedem Anhang
  hart `image/jpeg` an, auch wenn die Bytes PNG oder WebP sind. Wer ihn glaubt,
  laesst `validate_image` an jedem Bestandsanhang mit 422 scheitern.
* Ein 1920-px-Bild sprengt das Kontextfenster. Ein Bildmodell zaehlt jede
  28x28-Kachel als Token; 1920x1799 ergibt rund 4.400 davon, mehr als die 4096
  des Fensters. Gemessen: HTTP 400.
"""
import io

import pytest
from PIL import Image

from app.services.assessment_media import MAX_EDGE, MediaError, prepare_image, sniff_mime


def _image_bytes(fmt, size=(64, 64), colour=(255, 200, 0)):
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format=fmt)
    return buffer.getvalue()


def test_sniff_reads_the_bytes_not_the_label():
    assert sniff_mime(_image_bytes("PNG")) == "image/png"
    assert sniff_mime(_image_bytes("WEBP")) == "image/webp"
    assert sniff_mime(_image_bytes("JPEG")) == "image/jpeg"


def test_sniff_refuses_a_format_the_chain_cannot_handle():
    with pytest.raises(MediaError):
        sniff_mime(_image_bytes("GIF"))


def test_prepare_accepts_a_png_that_odoo_labelled_jpeg():
    """Genau der Bestandsfall: die Bytes sind PNG, in Odoo steht image/jpeg.
    `prepare_image` bekommt nur die Bytes und darf deshalb nicht stolpern."""
    out = prepare_image(_image_bytes("PNG"))
    assert sniff_mime(out) == "image/jpeg"


def test_prepare_accepts_webp():
    """Das Hundefoto aus QA/0014 ist WebP."""
    out = prepare_image(_image_bytes("WEBP"))
    assert sniff_mime(out) == "image/jpeg"


def test_prepare_shrinks_the_long_edge():
    out = prepare_image(_image_bytes("PNG", size=(1920, 1799)))
    with Image.open(io.BytesIO(out)) as image:
        assert max(image.size) == MAX_EDGE


def test_prepare_keeps_the_aspect_ratio():
    out = prepare_image(_image_bytes("PNG", size=(1000, 500)))
    with Image.open(io.BytesIO(out)) as image:
        assert image.size == (MAX_EDGE, MAX_EDGE // 2)


def test_prepare_leaves_small_images_alone():
    """Das Katalogbild ist 192x192. Hochskalieren erfindet nur Pixel."""
    out = prepare_image(_image_bytes("PNG", size=(192, 192)))
    with Image.open(io.BytesIO(out)) as image:
        assert image.size == (192, 192)


def test_prepare_refuses_what_is_not_an_image():
    with pytest.raises(MediaError):
        prepare_image(b"das ist kein Bild")


def test_prepare_refuses_an_empty_body():
    with pytest.raises(MediaError):
        prepare_image(b"")


def _transparent_png():
    """Halb durchsichtiges Bild: linke Haelfte deckend gelb, rechte leer."""
    image = Image.new("RGBA", (64, 64), (255, 200, 0, 255))
    for x in range(32, 64):
        for y in range(64):
            image.putpixel((x, y), (0, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_transparency_becomes_white_not_black():
    """JPEG kennt keine Transparenz. Ein blosses convert("RGB") macht
    durchsichtige Flaechen SCHWARZ -- und ein Schadensmodell sucht genau nach
    solchen Flaechen. Das Meldefoto von QA/0011 ist ein Palettenbild mit
    Transparenz; wir wuerden ihm den Schaden also selbst hineinmalen."""
    out = prepare_image(_transparent_png())
    with Image.open(io.BytesIO(out)) as image:
        r, g, b = image.convert("RGB").getpixel((60, 32))
    assert (r, g, b) > (240, 240, 240), f"erwartet weiss, bekommen {(r, g, b)}"
