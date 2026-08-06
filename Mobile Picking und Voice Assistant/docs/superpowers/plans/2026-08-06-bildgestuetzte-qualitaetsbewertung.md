# Bildgestützte Qualitätsbewertung — Umsetzungsplan

> **Für agentische Bearbeiter:** ERFORDERLICHE UNTER-SKILL: `superpowers:subagent-driven-development` (empfohlen) oder `superpowers:executing-plans`, um diesen Plan Aufgabe für Aufgabe abzuarbeiten. Die Schritte nutzen Kästchen (`- [ ]`) zur Nachverfolgung.

**Ziel:** Die Qualitätskette sieht das Foto an. Ein Hundefoto darf nicht mehr „verkaufbar" werden.

**Architektur:** Das Backend holt Meldefoto und Katalogbild selbst aus Odoo, lässt `qwen2.5vl:7b` zweimal darauf schauen (stimmt der Artikel? ist er beschädigt?) und gleicht das Ergebnis in reinem Python gegen das unveränderte Texturteil von `qwen2.5:7b` ab. n8n ruft weiterhin genau einen Endpunkt auf; Envelope, Signatur, Lease und Nonce bleiben unangetastet.

**Technik:** Python 3.12, FastAPI, Pydantic v2, Pillow 11, httpx, Odoo 19, n8n 2.13, Ollama.

**Entwurf:** `docs/superpowers/specs/2026-08-06-bildgestuetzte-qualitaetsbewertung-design.md`

## Globale Randbedingungen

- **Modelle:** `qwen2.5:7b` für den Text, `qwen2.5vl:7b` für die Bilder. `qwen2.5vl:3b` ist gemessen unbrauchbar, `qwen2.5vl:7b` beim Text gemessen schlechter — beide Zuordnungen sind nicht verhandelbar.
- **Voraussetzung:** `.wslconfig` muss auf `memory=20GB`, `processors=12` stehen, sonst passen die beiden Modelle nicht gleichzeitig in den Speicher. Vor Aufgabe 8 prüfen mit `free -g` (mindestens 18 GB gesamt) und `nproc` (mindestens 8).
- **Bildgröße:** Kandidatenbilder werden auf 512 px lange Kante verkleinert. Das 1920-px-Original läuft gegen Ollama in `HTTP 400`.
- **Prompttexte sind normativ.** Die Wortlaute in Aufgabe 3 stehen so im Entwurf, weil sie gemessen wurden: ohne den Satz über „ragged, torn or gouged" null von vier Prüfbildern richtig, mit ihm drei von vier ohne Fehlalarm. Sie dürfen nicht „verbessert" werden.
- **Schema-Reihenfolge ist normativ.** Erst beschreiben, dann urteilen. Wird zuerst nach der Disposition gefragt, antwortet das Modell aus dem Schema statt aus dem Bild.
- **fail-closed:** Fällt die Bildprüfung aus, bleibt das Texturteil stehen und der Grund wird im Klartext vermerkt. Nie ein erfundener Bildbefund.
- **Kein neues Envelope-Feld.** Wer den Envelope anfasst, verlässt diesen Plan.
- **MIME immer aus den Bytes**, nie aus dem gespeicherten Wert. `api_create_alert` schreibt hart `"image/jpeg"`, die Bytes sind PNG oder WebP.
- **Deutsche Kommentare und Meldungen**, wie im übrigen Bestand. Kommentare begründen Entscheidungen, sie beschreiben nicht, was der Code ohnehin sagt.
- **Tests laufen im Backend-Container:** `docker exec -e ODOO_INSTANCES_JSON= mobilepickingundvoiceassistant-backend-1 sh -c 'cd /app && python -m pytest <pfad> -q'`. `backend/app` ist als Volume eingehängt, Änderungen sind sofort wirksam. `backend/tests` ist **nicht** eingehängt — vor jedem Lauf `docker exec mobilepickingundvoiceassistant-backend-1 rm -rf /app/tests && docker cp backend/tests mobilepickingundvoiceassistant-backend-1:/app/tests`. Fehlt `pytest`: `docker exec mobilepickingundvoiceassistant-backend-1 pip install -q pytest pytest-asyncio`.
- **32 Tests sind im Container vorher schon rot** (fehlende Secret-Dateien, Registry-Pfad, Seed-Skript). Maßstab ist: keiner mehr als vorher.

---

## Dateiübersicht

| Datei | Zuständigkeit |
|---|---|
| `odoo/addons/quality_alert_custom/models/quality_alert.py` | **ändern** — Fassade `api_get_assessment_media`, `photo_analysis` schreiben |
| `odoo/addons/quality_alert_custom/views/quality_alert_views.xml` | **ändern** — Fotoanalyse sichtbar machen |
| `backend/app/services/assessment_media.py` | **neu** — Bytes prüfen, Typ erkennen, verkleinern |
| `backend/app/services/vision_client.py` | **neu** — die zwei Ollama-Bildaufrufe |
| `backend/app/services/assessment_reconciliation.py` | **neu** — Widerspruchstabelle, reines Python |
| `backend/app/services/llm_client.py` | **ändern** — die Zeile „keine Bildinhalte" streichen |
| `backend/app/models/events.py` | **ändern** — Antwortfelder |
| `backend/app/routers/n8n_v2.py` | **ändern** — die fünf Schritte verdrahten |
| `backend/app/config.py` | **ändern** — Modellname und Schalter fürs Bildmodell |
| `n8n/workflows/quality-assessment-v2.json` | **ändern** — Bedingung, Zeitgrenze, `photo_analysis` im Callback |
| `backend/tests/test_assessment_media.py` | **neu** |
| `backend/tests/test_vision_client.py` | **neu** |
| `backend/tests/test_assessment_reconciliation.py` | **neu** |

Die drei neuen Dienste sind bewusst getrennt: Bildaufbereitung, Modellaufruf und Entscheidung haben verschiedene Gründe sich zu ändern. Nur der letzte muss vollständig ohne Netz und ohne Modell testbar sein — er trägt die Regel.

---

## Aufgabe 1: Odoo-Fassade für die Bilder

**Dateien:**
- Ändern: `odoo/addons/quality_alert_custom/models/quality_alert.py`

**Schnittstellen:**
- Nutzt: `picking.assistant.integration.job._require_current_generation(generation, supplied_token)` aus `picking_assistant_integration/models/resources.py:211`
- Liefert: RPC-Methode `quality.alert.custom.api_get_assessment_media(job_id, delivery_generation, processing_lease_token)` → `dict` mit den Schlüsseln `photos` (Liste aus `{"filename": str, "data_b64": str}`), `photo_total` (int), `reference_image_b64` (str oder `False`), `product_label` (str)

Warum eine Fassade und kein direkter `ir.attachment`-Zugriff vom Backend: Odoo lehnt Methoden mit führendem `_` über RPC ab, und der Bestand führt jeden Zugriff über eine benannte `api_*`-Methode. Die Bindung an `job_id` statt an eine mitgeschickte Alert-Kennung ist der Punkt, an dem der Zugriff eng bleibt — der Aufrufer kann sich keinen fremden Alert aussuchen.

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

Neue Datei `odoo/addons/quality_alert_custom/tests/__init__.py`:

```python
from . import test_assessment_media
```

Neue Datei `odoo/addons/quality_alert_custom/tests/test_assessment_media.py`:

```python
"""Die Fassade, ueber die das Backend an Meldefoto und Katalogbild kommt.

Sie ist an den Job gebunden, nicht an eine mitgeschickte Alert-Kennung: wer
den Alert frei waehlen koennte, kaeme mit einer gueltigen Signatur an jedes
Foto im System.
"""
import base64

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


def _png_bytes():
    # 1x1 PNG, kleinstmoegliches gueltiges Bild.
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
        "IQAAAABJRU5ErkJggg=="
    )


class TestAssessmentMedia(TransactionCase):
    def setUp(self):
        super().setUp()
        self.product = self.env["product.product"].create({
            "name": "Pruefbaustein",
            "type": "consu",
        })
        self.product.product_tmpl_id.image_1920 = base64.b64encode(_png_bytes())
        self.alert = self.env["quality.alert.custom"].create({
            "description": "Testmeldung",
            "product_id": self.product.id,
        })
        self.env["ir.attachment"].create({
            "name": "foto.png",
            "type": "binary",
            "datas": base64.b64encode(_png_bytes()),
            "res_model": "quality.alert.custom",
            "res_id": self.alert.id,
            "mimetype": "image/jpeg",
        })

    def test_unknown_job_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env["quality.alert.custom"].api_get_assessment_media(
                "00000000-0000-4000-8000-000000000000", 1, "x" * 43
            )
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Ausführen:

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
docker exec mobilepickingundvoiceassistant-odoo-1 odoo \
  --no-http --stop-after-init -d masterfischer_o19 \
  --db_host db --db_user odoo --db_password "$POSTGRES_PASSWORD" \
  -u quality_alert_custom --test-tags /quality_alert_custom 2>&1 | tail -20
```

Erwartet: FEHLSCHLAG mit `AttributeError` oder `Object quality.alert.custom has no method api_get_assessment_media`.

Das Passwort steht in `~/.pwr-secrets`; auf dem Windows-Laufwerk ist `chmod` wirkungslos, deshalb liegt es dort und nicht im Repo.

- [ ] **Schritt 3: Die Fassade schreiben**

In `quality_alert.py`, neben `api_apply_assessment`, mit den Importen `base64` (falls nicht vorhanden) und `ValidationError` (bereits importiert):

```python
    # Mehr als drei Fotos zu pruefen kostet je Bild rund 21 Sekunden und
    # bringt selten mehr Erkenntnis. Die Zahl der uebergangenen steht im
    # Ergebnis, damit niemand glaubt, es sei alles angesehen worden.
    _MAX_ASSESSMENT_PHOTOS = 3

    def api_get_assessment_media(self, job_id, delivery_generation, processing_lease_token):
        """Liefert dem Bewertungsschritt Meldefoto und Katalogbild.

        Der Zugriff haengt am JOB, nicht an einer mitgeschickten Alert-Kennung:
        wer den Alert frei waehlen koennte, kaeme mit einer einzigen gueltigen
        Signatur an jedes Foto im System. Dieselbe Lease- und
        Generationspruefung wie bei `api_get_job_media` -- eine abgelaufene
        Bearbeitung darf nichts mehr lesen.

        Gelesen werden ausschliesslich Anhaenge mit `res_field = False`. Odoo
        legt je Foto ZWEI Zeilen an: die Ablage des Binaerfeldes `photo`
        (neu kodiert, nur eine, auch bei mehreren Fotos) und diese hier mit den
        urspruenglichen Bytes und dem urspruenglichen Dateinamen.

        Der gespeicherte `mimetype` wird bewusst NICHT mitgeliefert.
        `api_create_alert` schreibt dort hart "image/jpeg", auch fuer PNG und
        WebP. Der Typ wird auf der Leseseite aus den Bytes bestimmt.
        """
        job = self.env["picking.assistant.integration.job"].sudo().search(
            [("job_id", "=", job_id), ("aggregate_model", "=", self._name)],
            limit=1,
        )
        if not job:
            raise ValidationError(f"Unbekannter Job: {job_id!r}")
        job._require_current_generation(delivery_generation, processing_lease_token)

        alert = self.sudo().browse(job.aggregate_res_id).exists()
        if not alert:
            raise ValidationError(f"Zum Job {job_id!r} fehlt der Alert.")

        attachments = self.env["ir.attachment"].sudo()
        domain = [
            ("res_model", "=", self._name),
            ("res_id", "=", alert.id),
            ("res_field", "=", False),
        ]
        total = attachments.search_count(domain)
        photos = attachments.search(
            domain, order="id asc", limit=self._MAX_ASSESSMENT_PHOTOS
        )

        template = alert.product_id.product_tmpl_id
        reference = template.image_1920 if template else False
        label = alert.product_id.display_name if alert.product_id else ""

        return {
            "photos": [
                {
                    "filename": photo.name or "",
                    "data_b64": (photo.datas or b"").decode("ascii"),
                }
                for photo in photos
            ],
            "photo_total": total,
            "reference_image_b64": reference.decode("ascii") if reference else False,
            "product_label": label,
        }
```

- [ ] **Schritt 4: Den Test um den Erfolgsfall erweitern**

An `test_assessment_media.py` anhängen:

```python
    def _job_for_alert(self):
        """Legt einen Job an, wie `_enqueue_job_event` ihn anlegen wuerde."""
        return self.env["picking.assistant.integration.job"].create({
            "job_id": "11111111-1111-4111-8111-111111111111",
            "job_type": "quality_assessment",
            "aggregate_model": "quality.alert.custom",
            "aggregate_res_id": self.alert.id,
            "aggregate_revision": 1,
            "sequence": 1,
        })

    def test_media_is_returned_for_a_known_job(self):
        job = self._job_for_alert()
        with patch.object(type(job), "_require_current_generation", return_value=None):
            result = self.env["quality.alert.custom"].api_get_assessment_media(
                job.job_id, 1, "x" * 43
            )
        self.assertEqual(len(result["photos"]), 1)
        self.assertEqual(result["photos"][0]["filename"], "foto.png")
        self.assertEqual(result["photo_total"], 1)
        self.assertTrue(result["reference_image_b64"])
        self.assertIn("Pruefbaustein", result["product_label"])

    def test_field_attachments_are_not_returned(self):
        """Die Ablage des Binaerfeldes `photo` ist eine zweite, neu kodierte
        Kopie -- sie darf nicht als zweites Foto durchgehen."""
        job = self._job_for_alert()
        self.alert.photo = base64.b64encode(_png_bytes())
        with patch.object(type(job), "_require_current_generation", return_value=None):
            result = self.env["quality.alert.custom"].api_get_assessment_media(
                job.job_id, 1, "x" * 43
            )
        self.assertEqual(result["photo_total"], 1)
```

Import oben in der Testdatei ergänzen: `from unittest.mock import patch`.

Die Lease-Prüfung wird im Test **weggepatcht**, nicht im Produktivcode umgangen. Eine Umgehung über einen Kontextschlüssel wäre eine Hintertür in genau der Prüfung, die den Zugriff eng hält — die gehört nicht in ausgelieferten Code, auch nicht mit gutem Namen.

- [ ] **Schritt 5: Tests laufen lassen**

Ausführen: der Befehl aus Schritt 2.
Erwartet: drei Tests grün.

- [ ] **Schritt 6: Den hartkodierten MIME in `api_create_alert` korrigieren**

In `quality_alert.py`, in der Schleife, die die Anhänge anlegt, `"mimetype": "image/jpeg"` ersetzen durch:

```python
                # Der Typ kommt aus den Bytes, nicht aus einer Annahme. Vorher
                # stand hier hart "image/jpeg", auch fuer PNG und WebP -- die
                # zwoelf Bestandsanhaenge tragen deshalb einen falschen Typ.
                "mimetype": guess_mimetype(base64.b64decode(p["data_b64"])),
```

Import ergänzen: `from odoo.tools.mimetypes import guess_mimetype`.

Auf diesen Wert hängt nichts: die Leseseite bestimmt den Typ ohnehin selbst (Aufgabe 2). Die Korrektur steht trotzdem hier, weil ein falscher Wert in der Datenbank irgendwann jemanden in die Irre führt. Eine Migration der zwölf Bestandszeilen entfällt genau deshalb.

- [ ] **Schritt 7: Tests erneut laufen lassen**

Ausführen: der Befehl aus Schritt 2.
Erwartet: drei Tests weiter grün.

- [ ] **Schritt 8: Committen**

```bash
git add odoo/addons/quality_alert_custom/models/quality_alert.py \
        odoo/addons/quality_alert_custom/tests/
git commit -m "feat(odoo): Fassade api_get_assessment_media fuer die Bildbewertung"
```

---

## Aufgabe 2: Bilder aufbereiten

**Dateien:**
- Neu: `backend/app/services/assessment_media.py`
- Test: `backend/tests/test_assessment_media.py`

**Schnittstellen:**
- Nutzt: `app.services.binary_validation.validate_image(body, declared_mime=...)` → `ValidatedBinary` mit `.mime_type`, `.sha256`; wirft `BinaryValidationError`
- Liefert: `sniff_mime(body: bytes) -> str`, `prepare_image(body: bytes, *, max_edge: int = 512) -> bytes` (JPEG-Bytes), `MediaError` (Ausnahme)

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

`backend/tests/test_assessment_media.py`:

```python
"""Bildaufbereitung vor dem Modellaufruf.

Zwei Dinge entscheiden hier ueber Funktionieren oder Nichtfunktionieren, und
beide wurden gemessen: der gespeicherte MIME luegt (api_create_alert schreibt
hart image/jpeg), und ein 1920-px-Bild sprengt das Kontextfenster von Ollama
mit HTTP 400.
"""
import io

import pytest
from PIL import Image

from app.services.assessment_media import MediaError, prepare_image, sniff_mime


def _image_bytes(fmt, size=(64, 64), colour=(255, 200, 0)):
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format=fmt)
    return buffer.getvalue()


def test_sniff_reads_the_bytes_not_the_label():
    assert sniff_mime(_image_bytes("PNG")) == "image/png"
    assert sniff_mime(_image_bytes("WEBP")) == "image/webp"
    assert sniff_mime(_image_bytes("JPEG")) == "image/jpeg"


def test_prepare_accepts_a_png_that_odoo_labelled_jpeg():
    # Genau der Bestandsfall: die Bytes sind PNG, in Odoo steht image/jpeg.
    out = prepare_image(_image_bytes("PNG"))
    assert sniff_mime(out) == "image/jpeg"


def test_prepare_shrinks_the_long_edge():
    out = prepare_image(_image_bytes("PNG", size=(1920, 1799)))
    with Image.open(io.BytesIO(out)) as image:
        assert max(image.size) == 512


def test_prepare_leaves_small_images_alone():
    out = prepare_image(_image_bytes("PNG", size=(192, 192)))
    with Image.open(io.BytesIO(out)) as image:
        assert image.size == (192, 192)


def test_prepare_refuses_what_is_not_an_image():
    with pytest.raises(MediaError):
        prepare_image(b"das ist kein Bild")
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
docker exec mobilepickingundvoiceassistant-backend-1 rm -rf /app/tests
docker cp backend/tests mobilepickingundvoiceassistant-backend-1:/app/tests
docker exec -e ODOO_INSTANCES_JSON= mobilepickingundvoiceassistant-backend-1 \
  sh -c 'cd /app && python -m pytest tests/test_assessment_media.py -q'
```

Erwartet: FEHLSCHLAG mit `ModuleNotFoundError: No module named 'app.services.assessment_media'`.

- [ ] **Schritt 3: Den Dienst schreiben**

`backend/app/services/assessment_media.py`:

```python
"""Bilder fuer die Bewertung aufbereiten.

Zwischen Odoo und dem Bildmodell liegen zwei Fallen, beide gemessen:

1. Der in Odoo gespeicherte MIME luegt. `api_create_alert` schreibt jedem
   Anhang hart `image/jpeg`, auch wenn die Bytes PNG oder WebP sind. Wer ihn
   glaubt, laesst `validate_image` an jedem Bestandsanhang scheitern. Der Typ
   wird deshalb aus den Bytes bestimmt -- derselbe Grundsatz, nach dem auf den
   signierten Routen ein deklarierter Content-Type nie als Beweis gilt.
2. Ein 1920-px-Bild sprengt das Kontextfenster: Ollama antwortet mit HTTP 400.
   512 px lange Kante ist keine Sparmassnahme, sondern Voraussetzung.
"""
from __future__ import annotations

import io

from PIL import Image

from app.services.binary_validation import BinaryValidationError, validate_image

MAX_EDGE = 512
_JPEG_QUALITY = 88


class MediaError(Exception):
    """Das Bild ist unbrauchbar. Der Aufrufer vermerkt den Grund und macht
    ohne Bildbefund weiter -- er erfindet keinen."""


def sniff_mime(body: bytes) -> str:
    """MIME aus den Bytes, nicht aus dem, was jemand behauptet."""
    try:
        with Image.open(io.BytesIO(body)) as image:
            fmt = (image.format or "").upper()
    except Exception as exc:  # noqa: BLE001 - jedes Leseproblem ist dasselbe
        raise MediaError(f"Bild nicht lesbar: {exc}") from exc
    mapping = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
    if fmt not in mapping:
        raise MediaError(f"Nicht unterstuetztes Bildformat: {fmt or 'unbekannt'}")
    return mapping[fmt]


def prepare_image(body: bytes, *, max_edge: int = MAX_EDGE) -> bytes:
    """Prueft das Bild und gibt ein verkleinertes JPEG zurueck.

    Die Pruefung laeuft ueber `validate_image` und damit ueber dieselben
    Grenzen wie die signierten Binaerrouten -- Groesse, Format-Allowlist,
    Pixel- und Frame-Grenzen. Erst danach wird verkleinert.
    """
    declared = sniff_mime(body)
    try:
        validate_image(body, declared_mime=declared)
    except BinaryValidationError as exc:
        raise MediaError(str(exc)) from exc

    with Image.open(io.BytesIO(body)) as image:
        image = image.convert("RGB")
        if max(image.size) > max_edge:
            image.thumbnail((max_edge, max_edge), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
    return buffer.getvalue()
```

- [ ] **Schritt 4: Tests laufen lassen**

Ausführen: der Befehl aus Schritt 2.
Erwartet: fünf Tests grün.

- [ ] **Schritt 5: Committen**

```bash
git add backend/app/services/assessment_media.py backend/tests/test_assessment_media.py
git commit -m "feat(backend): Bildaufbereitung fuer die Bewertung"
```

---

## Aufgabe 3: Der Bild-Client

**Dateien:**
- Neu: `backend/app/services/vision_client.py`
- Ändern: `backend/app/config.py`
- Test: `backend/tests/test_vision_client.py`

**Schnittstellen:**
- Liefert: `VisionClient(endpoint, model, timeout_ms, transport=None)` mit `await compare_article(reference: bytes, candidate: bytes) -> ArticleMatch` und `await inspect_damage(candidate: bytes) -> DamageCheck`
- `ArticleMatch`: `ok: bool`, `same_article: bool | None`, `reason: str | None`, `candidate_description: str | None`
- `DamageCheck`: `ok: bool`, `damaged: bool | None`, `anomalies: tuple[str, ...]`, `description: str | None`

Zwei Aufrufe statt einem, weil einer gemessen schlechter ist: im Zwei-Bild-Aufruf stufte das Modell einen Bruch als „decorative element" ein und setzte `damaged: false`; im Einzelbild-Aufruf mit geschärftem Prompt erkannte es ihn als „torn".

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

`backend/tests/test_vision_client.py`:

```python
"""Der Bild-Client.

Geprueft wird nicht, ob das Modell richtig liegt -- das ist eine Frage der
Abnahme -, sondern dass genau die zwei gemessenen Prompts abgeschickt werden,
dass zwei Bilder im richtigen Sinn ankommen, und dass jeder Fehler in einem
leeren Befund endet statt in einer Vermutung.
"""
import json

import httpx
import pytest

from app.services.vision_client import VisionClient

REFERENCE = b"\xff\xd8referenz"
CANDIDATE = b"\xff\xd8kandidat"


def _client(handler):
    return VisionClient(
        endpoint="http://ollama:11434",
        model="qwen2.5vl:7b",
        timeout_ms=5000,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.anyio
async def test_compare_article_sends_reference_first():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        answer = json.dumps({
            "image1_shows": "gelber Baustein",
            "image2_shows": "ein Hund am Strand",
            "same_article": False,
            "same_article_reason": "Image 2 shows an animal, not a product.",
        })
        return httpx.Response(200, json={"response": answer})

    result = await _client(handler).compare_article(REFERENCE, CANDIDATE)

    assert len(captured["body"]["images"]) == 2
    assert captured["body"]["format"] == "json"
    assert captured["body"]["options"]["temperature"] == 0
    assert "IMAGE 1 is the official catalogue photo" in captured["body"]["prompt"]
    assert result.ok is True
    assert result.same_article is False
    assert "animal" in result.reason


@pytest.mark.anyio
async def test_inspect_damage_sends_one_image_and_the_decisive_rule():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        answer = json.dumps({
            "surface_description": "eine aufgerissene Zone",
            "anomalies": ["torn"],
            "damaged": True,
            "confidence": 0.95,
        })
        return httpx.Response(200, json={"response": answer})

    result = await _client(handler).inspect_damage(CANDIDATE)

    assert len(captured["body"]["images"]) == 1
    assert "never decoration or a design feature" in captured["body"]["prompt"]
    assert result.ok is True
    assert result.damaged is True
    assert result.anomalies == ("torn",)


@pytest.mark.anyio
async def test_http_error_yields_an_empty_finding_not_a_guess():
    def handler(request):
        return httpx.Response(500, text="kaputt")

    result = await _client(handler).inspect_damage(CANDIDATE)

    assert result.ok is False
    assert result.damaged is None
    assert result.anomalies == ()


@pytest.mark.anyio
async def test_unparsable_answer_yields_an_empty_finding():
    def handler(request):
        return httpx.Response(200, json={"response": "kein JSON"})

    result = await _client(handler).compare_article(REFERENCE, CANDIDATE)

    assert result.ok is False
    assert result.same_article is None
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

```bash
docker exec mobilepickingundvoiceassistant-backend-1 rm -rf /app/tests
docker cp backend/tests mobilepickingundvoiceassistant-backend-1:/app/tests
docker exec -e ODOO_INSTANCES_JSON= mobilepickingundvoiceassistant-backend-1 \
  sh -c 'cd /app && python -m pytest tests/test_vision_client.py -q'
```

Erwartet: FEHLSCHLAG mit `ModuleNotFoundError: No module named 'app.services.vision_client'`.

- [ ] **Schritt 3: Den Client schreiben**

`backend/app/services/vision_client.py`:

```python
"""Bildbefunde von einem lokalen Vision-Modell (Ollama).

Zwei getrennte Aufrufe, und das ist keine Geschmacksfrage: im Zwei-Bild-
Aufruf hat das Modell einen sichtbaren Bruch als "decorative element"
abgetan und `damaged: false` gesetzt; derselbe Bruch wurde im Einzelbild-
Aufruf mit geschaerftem Prompt als "torn" erkannt. Der Vergleich lenkt die
Aufmerksamkeit auf Unterschiede, die Schadenspruefung auf die Oberflaeche.

Die Reihenfolge der JSON-Schluessel ist normativ: erst beschreiben, dann
urteilen. Wird zuerst nach dem Urteil gefragt, antwortet das Modell aus dem
Schema statt aus dem Bild -- am 2026-08-05 gemessen, in beiden Sprachen.

Jeder Fehler endet in `ok=False` mit leeren Feldern. Ein halber Befund waere
die Einladung, doch etwas daraus zu schliessen.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

ARTICLE_PROMPT = (
    "You receive two images.\n"
    "IMAGE 1 is the official catalogue photo of the article that SHOULD be in "
    "the box.\n"
    "IMAGE 2 is the photo a warehouse worker just took of the item in front of "
    "them.\n\n"
    "Answer strictly as JSON with these keys, in this order:\n"
    '  "image1_shows": short factual description of image 1,\n'
    '  "image2_shows": short factual description of image 2,\n'
    '  "same_article": true or false - is image 2 the same kind of article as '
    "image 1?,\n"
    '  "same_article_reason": one short sentence\n\n'
    "Rules: describe before you judge. Do not guess. If image 2 shows something "
    "that is not a product at all (a person, an animal, a room), set "
    "same_article false and say so."
)

DAMAGE_PROMPT = (
    "You inspect a moulded plastic part before shipping.\n"
    "Answer strictly as JSON with these keys, in this order:\n"
    '  "surface_description": describe the surface: is it smooth and continuous '
    "everywhere, or is there a region that looks torn, split, gouged, ragged or "
    "broken open?,\n"
    '  "anomalies": array of short strings for every region that breaks the '
    "smooth surface. Empty array if the surface is continuous everywhere.,\n"
    '  "damaged": true or false,\n'
    '  "confidence": number 0.0 to 1.0\n\n'
    "Decisive rule: a ragged, torn or gouged area on an otherwise smooth moulded "
    "surface is DAMAGE, never decoration or a design feature. Printed logos, "
    "smooth colour changes and reflections are NOT damage. "
    "An item whose surface is continuous everywhere must get damaged false."
)


@dataclass(frozen=True)
class ArticleMatch:
    ok: bool
    same_article: bool | None = None
    reason: str | None = None
    candidate_description: str | None = None


@dataclass(frozen=True)
class DamageCheck:
    ok: bool
    damaged: bool | None = None
    anomalies: tuple[str, ...] = field(default_factory=tuple)
    description: str | None = None


class VisionClient:
    PROVIDER = "ollama-local"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        timeout_ms: int = 180000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        seconds = max(1.0, timeout_ms / 1000.0)
        self._timeout = httpx.Timeout(connect=5.0, read=seconds, write=30.0, pool=5.0)
        self._transport = transport

    async def _ask(self, prompt: str, images: list[bytes]) -> dict | None:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "images": [base64.b64encode(image).decode("ascii") for image in images],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_ctx": 8192},
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._endpoint}/api/generate", json=payload
                )
            response.raise_for_status()
            parsed = json.loads(response.json().get("response") or "")
        except Exception as exc:  # noqa: BLE001 - jeder Fehler heisst: kein Befund
            logger.warning(json.dumps({
                "event_type": "vision_probe_failed",
                "model": self._model,
                "error": str(exc),
            }))
            return None
        return parsed if isinstance(parsed, dict) else None

    async def compare_article(self, reference: bytes, candidate: bytes) -> ArticleMatch:
        parsed = await self._ask(ARTICLE_PROMPT, [reference, candidate])
        if parsed is None or not isinstance(parsed.get("same_article"), bool):
            return ArticleMatch(ok=False)
        return ArticleMatch(
            ok=True,
            same_article=parsed["same_article"],
            reason=str(parsed.get("same_article_reason") or "").strip() or None,
            candidate_description=str(parsed.get("image2_shows") or "").strip() or None,
        )

    async def inspect_damage(self, candidate: bytes) -> DamageCheck:
        parsed = await self._ask(DAMAGE_PROMPT, [candidate])
        if parsed is None or not isinstance(parsed.get("damaged"), bool):
            return DamageCheck(ok=False)
        raw = parsed.get("anomalies")
        anomalies = tuple(
            str(item).strip() for item in raw if str(item).strip()
        ) if isinstance(raw, list) else ()
        return DamageCheck(
            ok=True,
            damaged=parsed["damaged"],
            anomalies=anomalies,
            description=str(parsed.get("surface_description") or "").strip() or None,
        )
```

- [ ] **Schritt 4: Die Einstellungen ergänzen**

In `backend/app/config.py`, direkt unter `llm_voice_model`:

```python
    # Getrenntes Modell fuer die Bilder. Ein Modell fuer beides scheidet aus:
    # qwen2.5vl:7b stufte "Verpackung defekt" als scrap ein ("Verpackungsdefekt
    # deutet auf Totalschaden hin"), wo qwen2.5:7b korrekt sellable sagt.
    # Beide gleichzeitig resident zu halten verlangt >= 18 GB in der WSL.
    vision_model: str = "qwen2.5vl:7b"
    vision_enabled: bool = True
    vision_timeout_ms: int = 180000
```

`vision_enabled` ist der Notausgang: steht es auf `false`, verhaelt sich die Kette wie vor diesem Umbau, ohne dass jemand Code zurueckdrehen muss.

- [ ] **Schritt 5: Tests laufen lassen**

Ausführen: der Befehl aus Schritt 2.
Erwartet: vier Tests grün.

- [ ] **Schritt 6: Committen**

```bash
git add backend/app/services/vision_client.py backend/app/config.py \
        backend/tests/test_vision_client.py
git commit -m "feat(backend): Bild-Client mit den zwei gemessenen Prompts"
```

---

## Aufgabe 4: Die Widerspruchstabelle

**Dateien:**
- Neu: `backend/app/services/assessment_reconciliation.py`
- Test: `backend/tests/test_assessment_reconciliation.py`

**Schnittstellen:**
- Nutzt: `ArticleMatch`, `DamageCheck` aus Aufgabe 3
- Liefert: `PhotoFinding` (Datenklasse mit `article: str`, `damage: str`, `note: str`) und `reconcile(*, disposition: str | None, finding: PhotoFinding) -> Reconciled` mit `Reconciled.contradiction: bool` und `Reconciled.photo_analysis: str`

Das ist das Herz und die einzige Stelle, die vollständig ohne Netz und ohne Modell entscheidet. Ein Modell, das sich aus einem Widerspruch herausreden kann, wäre keine Prüfung.

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

`backend/tests/test_assessment_reconciliation.py`:

```python
"""Ein Test je Zeile der Widerspruchstabelle aus dem Entwurf.

Kein Modellaufruf, kein Netz: die Regel muss ohne beides pruefbar sein, sonst
ist sie keine Regel.
"""
from app.services.assessment_reconciliation import PhotoFinding, reconcile


def _finding(article="match", damage="intact", note="Bildbefund."):
    return PhotoFinding(article=article, damage=damage, note=note)


def test_wrong_article_always_goes_to_a_human():
    for disposition in ("scrap", "rework", "quarantine", "sellable"):
        result = reconcile(
            disposition=disposition,
            finding=_finding(article="mismatch", note="Foto zeigt einen Hund."),
        )
        assert result.contradiction is True, disposition
        assert "Hund" in result.photo_analysis


def test_damage_seen_and_damage_reported_confirms():
    for disposition in ("scrap", "rework"):
        result = reconcile(disposition=disposition, finding=_finding(damage="damaged"))
        assert result.contradiction is False


def test_damage_seen_but_reported_sellable_goes_to_a_human():
    result = reconcile(disposition="sellable", finding=_finding(damage="damaged"))
    assert result.contradiction is True
    assert "verkaufsfaehig" in result.photo_analysis


def test_nothing_seen_and_nothing_reported_confirms():
    result = reconcile(disposition="sellable", finding=_finding(damage="intact"))
    assert result.contradiction is False


def test_damage_reported_but_nothing_seen_is_noted_not_blocked():
    """Die eine bewusst entschiedene Zeile: der Kommissionierer hatte den
    Artikel in der Hand, das Modell nur ein 512-px-Foto -- und es hat einen
    sichtbaren Riss uebersehen. Das Texturteil bleibt, die Abweichung wird
    sichtbar."""
    for disposition in ("scrap", "rework"):
        result = reconcile(disposition=disposition, finding=_finding(damage="intact"))
        assert result.contradiction is False, disposition
        assert "keinen sichtbaren Schaden" in result.photo_analysis


def test_quarantine_is_never_contradicted():
    """quarantine trifft keine Aussage ueber den Artikel, sondern verlangt
    ohnehin einen Menschen."""
    for damage in ("damaged", "intact"):
        result = reconcile(disposition="quarantine", finding=_finding(damage=damage))
        assert result.contradiction is False


def test_missing_reference_image_only_drops_the_article_check():
    result = reconcile(
        disposition="scrap",
        finding=_finding(article="unavailable", damage="damaged"),
    )
    assert result.contradiction is False
    assert "kein Katalogbild" in result.photo_analysis


def test_failed_photo_check_leaves_the_text_verdict_standing():
    result = reconcile(
        disposition="scrap",
        finding=PhotoFinding(
            article="unavailable",
            damage="unavailable",
            note="Bildpruefung nicht moeglich: Zeitueberschreitung.",
        ),
    )
    assert result.contradiction is False
    assert "nicht moeglich" in result.photo_analysis


def test_no_text_verdict_never_contradicts():
    """Ohne Texturteil gibt es nichts zu widersprechen -- der Workflow meldet
    dann ohnehin review_required."""
    result = reconcile(disposition=None, finding=_finding(damage="damaged"))
    assert result.contradiction is False
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

```bash
docker exec mobilepickingundvoiceassistant-backend-1 rm -rf /app/tests
docker cp backend/tests mobilepickingundvoiceassistant-backend-1:/app/tests
docker exec -e ODOO_INSTANCES_JSON= mobilepickingundvoiceassistant-backend-1 \
  sh -c 'cd /app && python -m pytest tests/test_assessment_reconciliation.py -q'
```

Erwartet: FEHLSCHLAG mit `ModuleNotFoundError: No module named 'app.services.assessment_reconciliation'`.

- [ ] **Schritt 3: Die Tabelle schreiben**

`backend/app/services/assessment_reconciliation.py`:

```python
"""Bildbefund gegen Texturteil -- die Entscheidung, ohne Modell.

Das Bild PRUEFT das Texturteil, es ersetzt es nicht. Der Text liefert
weiterhin die Einstufung; das Bild kann sie bestaetigen, ihr widersprechen
oder eine Abweichung vermerken.

Warum ein Widerspruch nicht immer blockiert: der Kommissionierer hatte den
Artikel in der Hand, das Modell hat ein 512-px-Foto -- und es hat einen
sichtbaren Riss uebersehen. Meldet der Mensch Schaden und sieht das Modell
keinen, bleibt das Texturteil stehen und die Abweichung wird sichtbar
vermerkt. Umgekehrt gilt das NICHT: sieht das Modell Schaden, wo die Meldung
"verkaufsfaehig" sagt, geht die Meldung an einen Menschen.

Modellkonfidenz kommt hier bewusst nicht vor. Beim uebersehenen Riss war das
Modell zu 95 % sicher; eine Schwelle darauf waere Scheinsicherheit.
"""
from __future__ import annotations

from dataclasses import dataclass

# Dispositionen, die eine Aussage ueber den ARTIKEL treffen. `quarantine`
# fehlt mit Absicht: es sagt "sperren und pruefen" und damit nichts, dem ein
# Bild widersprechen koennte.
_CLAIMS_DAMAGE = frozenset({"scrap", "rework"})
_CLAIMS_SOUND = frozenset({"sellable"})


@dataclass(frozen=True)
class PhotoFinding:
    """Was die Bilder ergeben haben.

    `article`: "match" | "mismatch" | "unavailable"
    `damage`:  "damaged" | "intact" | "unavailable"
    `note`: Klartext fuer den Menschen, bereits fertig formuliert.
    """

    article: str
    damage: str
    note: str


@dataclass(frozen=True)
class Reconciled:
    contradiction: bool
    photo_analysis: str


def reconcile(*, disposition: str | None, finding: PhotoFinding) -> Reconciled:
    if finding.article == "mismatch":
        return Reconciled(
            contradiction=True,
            photo_analysis=finding.note,
        )

    if disposition in _CLAIMS_SOUND and finding.damage == "damaged":
        return Reconciled(
            contradiction=True,
            photo_analysis=(
                f"{finding.note}\n"
                "Das Foto zeigt einen Schaden, die Meldung stuft die Ware als "
                "verkaufsfaehig ein."
            ),
        )

    if disposition in _CLAIMS_DAMAGE and finding.damage == "intact":
        return Reconciled(
            contradiction=False,
            photo_analysis=(
                f"{finding.note}\n"
                "Das Foto zeigt keinen sichtbaren Schaden, die Meldung nennt "
                "einen. Bitte stichprobenartig pruefen."
            ),
        )

    return Reconciled(contradiction=False, photo_analysis=finding.note)
```

- [ ] **Schritt 4: Tests laufen lassen**

Ausführen: der Befehl aus Schritt 2.
Erwartet: neun Tests grün.

- [ ] **Schritt 5: Committen**

```bash
git add backend/app/services/assessment_reconciliation.py \
        backend/tests/test_assessment_reconciliation.py
git commit -m "feat(backend): Widerspruchstabelle Bild gegen Text"
```

---

## Aufgabe 5: Die Bewertungsroute verdrahten

**Dateien:**
- Ändern: `backend/app/routers/n8n_v2.py` (Funktion `assess_quality`)
- Ändern: `backend/app/models/events.py` (`QualityAssessmentV2Response`)
- Ändern: `backend/app/services/llm_client.py:85`
- Ändern: `backend/app/dependencies.py` (Bereitstellung des `VisionClient`)
- Test: `backend/tests/test_n8n_v2_assessment_route.py`

**Schnittstellen:**
- Nutzt: `api_get_assessment_media` (Aufgabe 1), `prepare_image` (Aufgabe 2), `VisionClient` (Aufgabe 3), `reconcile` (Aufgabe 4)
- Liefert: `QualityAssessmentV2Response` zusätzlich mit `photo_checked: bool`, `contradiction: bool`, `photo_analysis: str | None`

- [ ] **Schritt 1: Die Lüge aus dem Textprompt streichen**

In `backend/app/services/llm_client.py`, Zeile 85, diese Zeile **entfernen**:

```python
        lines.append("Wichtig: Es stehen keine Bildinhalte zur Verfuegung, nur der Text.")
```

Ersatzlos. Das Textmodell bekommt weiterhin **keinen** Bildbefund — es bleibt eine reine Textbewertung, genau deshalb lässt sie sich prüfen. Es soll nur nicht mehr belogen werden; bei QA/0011 begründete ein Modell sein Urteil bereits mit „keine Bilder verfügbar, daher als Totalschaden eingestuft".

- [ ] **Schritt 2: Die Antwortfelder ergänzen**

In `backend/app/models/events.py`, in `QualityAssessmentV2Response`, unter `model: str`:

```python
    # Der Bildbefund reist als eigene Felder mit, nicht im Urteil: n8n
    # verzweigt allein auf `contradiction`, und `photo_analysis` geht
    # unveraendert nach Odoo durch.
    photo_checked: bool = False
    contradiction: bool = False
    photo_analysis: str | None = None
```

`StrictModel` verbietet unbekannte Felder (`events.py:19-21`) — ohne diesen Schritt wird jede Antwort mit Bildbefund abgelehnt.

- [ ] **Schritt 3: Den fehlschlagenden Test schreiben**

An `backend/tests/test_n8n_v2_assessment_route.py` anhängen. Die Datei bringt alles Nötige schon mit: `post(assess_body())`, die Fixture `llm_ok` (liefert `scrap`), `install_llm(...)` und die Fixture `signed_env` aus `test_n8n_v2_routes`, die je Instanz ein `FakeOdoo` mit setzbarem `.response` bereitstellt. Die Anfrage nennt `odoo_instance: "o19-a"` — dieses `FakeOdoo` liefert die Bilder.

```python
import base64
import io

from PIL import Image

from app.services.vision_client import ArticleMatch, DamageCheck


def _tiny_jpeg_b64():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (255, 200, 0)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


MEDIA_RESPONSE = {
    "photos": [{"filename": "hund.webp", "data_b64": _tiny_jpeg_b64()}],
    "photo_total": 1,
    "reference_image_b64": _tiny_jpeg_b64(),
    "product_label": "[6023350] Brick 2x2x2 R=15 gelb",
}


class FakeVision:
    def __init__(self, match, damage):
        self._match = match
        self._damage = damage

    async def compare_article(self, reference, candidate):
        return self._match

    async def inspect_damage(self, candidate):
        return self._damage


def install_vision(match, damage):
    fake = FakeVision(match, damage)
    app.dependency_overrides[dependencies.get_vision_client] = lambda: fake
    return fake


def test_a_dog_photo_contradicts_a_sellable_verdict(signed_env):
    """Der Fall, der diesen Umbau ausgeloest hat: QA/0014, Text
    'Verpackung defekt' -> sellable, Foto ein Hund."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    install_llm(
        LlmDispositionResult(
            ok=True,
            model="qwen2.5:7b",
            disposition="sellable",
            confidence=0.9,
            summary="Defekte Verpackung, Produkt unbeeintraechtigt.",
            recommended_action="Sichtpruefung.",
        )
    )
    install_vision(
        ArticleMatch(
            ok=True,
            same_article=False,
            reason="Image 2 shows an animal, not a product.",
            candidate_description="a dog on a beach",
        ),
        DamageCheck(ok=True, damaged=False, anomalies=()),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_llm_client, None)
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["photo_checked"] is True
    assert body["contradiction"] is True
    assert "nicht den gemeldeten Artikel" in body["photo_analysis"]


def test_vision_failure_leaves_the_text_verdict_standing(llm_ok, signed_env):
    signed_env["o19-a"].response = MEDIA_RESPONSE
    install_vision(ArticleMatch(ok=False), DamageCheck(ok=False))
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    body = response.json()
    assert body["llm_ok"] is True
    assert body["disposition"] == "scrap"
    assert body["contradiction"] is False
    assert "nicht moeglich" in body["photo_analysis"]
```

**Der vorhandene Test `test_route_never_writes_to_odoo` muss umgeschrieben werden.** Er behauptet heute, die Route rühre Odoo überhaupt nicht an (`assert all(client.calls == [] ...)`) — und genau das ändert sich. Die Zusage wird enger gefasst statt aufgegeben:

```python
def test_route_reads_media_but_never_writes(llm_ok, signed_env):
    """Die Route liest jetzt Bilder aus Odoo. Sie entscheidet und aendert
    weiterhin nichts -- ueber Wirkung entscheidet ausschliesslich der
    Callback. Geprueft wird deshalb, WAS sie ruft, nicht mehr OB."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    install_vision(
        ArticleMatch(ok=True, same_article=True, reason="passt"),
        DamageCheck(ok=True, damaged=False, anomalies=()),
    )
    try:
        post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    assert [(model, method) for model, method, _ in signed_env["o19-a"].calls] == [
        ("quality.alert.custom", "api_get_assessment_media")
    ]
    # Keine andere Instanz wird angefasst.
    assert signed_env["local"].calls == []
    assert signed_env["o19-b"].calls == []
```

Der alte Test wird dabei ersetzt, nicht daneben gestellt: zwei Tests mit gegensätzlicher Behauptung über dieselbe Route sind schlimmer als keiner.


- [ ] **Schritt 4: Test laufen lassen, Fehlschlag bestätigen**

```bash
docker exec mobilepickingundvoiceassistant-backend-1 rm -rf /app/tests
docker cp backend/tests mobilepickingundvoiceassistant-backend-1:/app/tests
docker exec -e ODOO_INSTANCES_JSON= mobilepickingundvoiceassistant-backend-1 \
  sh -c 'cd /app && python -m pytest tests/test_n8n_v2_assessment_route.py -q -k contradiction'
```

Erwartet: FEHLSCHLAG, weil `photo_checked` in der Antwort fehlt oder `contradiction` immer `False` ist.

- [ ] **Schritt 5: Den `VisionClient` bereitstellen**

In `backend/app/dependencies.py`, neben `get_llm_client`, nach demselben Muster:

```python
def get_vision_client() -> VisionClient | None:
    """`None`, wenn die Bildpruefung abgeschaltet ist.

    Der Schalter sitzt hier und nicht im Router: so kennt die Route nur
    "Client da oder nicht" und muss keine Einstellungen lesen. `None` ist
    dabei kein Sonderfall, sondern derselbe Weg wie ein Ausfall des
    Bildmodells -- die Kette verhaelt sich wie vor diesem Umbau.
    """
    if not settings.vision_enabled:
        return None
    return VisionClient(
        endpoint=settings.llm_endpoint,
        model=settings.vision_model,
        timeout_ms=settings.vision_timeout_ms,
    )
```

Import ergänzen: `from app.services.vision_client import VisionClient`.

Dieser Schritt kommt **vor** dem Umbau der Route: dazwischen wäre die Anwendung nicht startfähig, weil `Depends(get_vision_client)` auf etwas zeigte, das es noch nicht gibt.

- [ ] **Schritt 6: Die Bildbeschaffung als eigene Funktion schreiben**

In `backend/app/routers/n8n_v2.py`, oberhalb von `assess_quality`:

```python
async def _collect_photo_finding(odoo, vision, body) -> tuple[PhotoFinding, bool]:
    """Holt die Bilder und laesst das Bildmodell zweimal darauf schauen.

    Gibt `(Befund, geprueft)` zurueck. `geprueft` ist False, sobald irgendetwas
    schiefging -- dann steht der Grund im Befund und das Texturteil bleibt
    allein stehen. Ein halber Bildbefund entsteht hier nie.
    """
    try:
        media = await odoo.execute_kw(
            "quality.alert.custom",
            "api_get_assessment_media",
            [
                str(body.job_id),
                body.delivery_generation,
                body.processing_lease_token,
            ],
        )
    except Exception as exc:  # noqa: BLE001 - jeder Fehler heisst: kein Bildbefund
        return PhotoFinding(
            article="unavailable",
            damage="unavailable",
            note=f"Bildpruefung nicht moeglich: {exc}",
        ), False

    photos = media.get("photos") or []
    if not photos:
        return PhotoFinding(
            article="unavailable",
            damage="unavailable",
            note="Ohne Bildpruefung: der Meldung liegt kein Foto bei.",
        ), False

    try:
        candidates = [
            prepare_image(base64.b64decode(photo["data_b64"])) for photo in photos
        ]
    except (MediaError, ValueError) as exc:
        return PhotoFinding(
            article="unavailable",
            damage="unavailable",
            note=f"Bildpruefung nicht moeglich: {exc}",
        ), False

    lines: list[str] = []

    article = "unavailable"
    reference_b64 = media.get("reference_image_b64")
    if reference_b64:
        try:
            reference = prepare_image(base64.b64decode(reference_b64))
        except (MediaError, ValueError) as exc:
            lines.append(f"Artikelabgleich nicht moeglich: {exc}")
            reference = None
        if reference is not None:
            match = await vision.compare_article(reference, candidates[0])
            if not match.ok:
                lines.append("Artikelabgleich nicht moeglich: Bildmodell antwortet nicht.")
            elif match.same_article:
                article = "match"
                lines.append("Artikelabgleich: stimmt mit Katalogbild ueberein.")
            else:
                article = "mismatch"
                label = media.get("product_label") or "dem gemeldeten Artikel"
                seen = match.candidate_description or match.reason or "etwas anderes"
                lines.append(
                    f"Foto zeigt nicht den gemeldeten Artikel: {seen} statt {label}."
                )
    else:
        lines.append("Artikelabgleich entfaellt: kein Katalogbild hinterlegt.")

    damage = "unavailable"
    findings: list[str] = []
    for candidate in candidates:
        check = await vision.inspect_damage(candidate)
        if not check.ok:
            continue
        damage = "damaged" if check.damaged else ("intact" if damage != "damaged" else damage)
        if check.damaged and check.anomalies:
            findings.extend(check.anomalies)
    if damage == "unavailable":
        lines.append("Schadenspruefung nicht moeglich: Bildmodell antwortet nicht.")
    elif damage == "damaged":
        lines.append("Schadenspruefung: " + ", ".join(findings or ["Schaden sichtbar"]) + ".")
    else:
        lines.append("Schadenspruefung: keine Auffaelligkeit sichtbar.")

    skipped = int(media.get("photo_total") or len(photos)) - len(photos)
    if skipped > 0:
        lines.append(f"{skipped} weitere Foto(s) ungeprueft.")

    checked = article != "unavailable" or damage != "unavailable"
    return PhotoFinding(article=article, damage=damage, note="\n".join(lines)), checked
```

Nötige Importe oben in der Datei ergänzen:

```python
import base64

from app.services.assessment_media import MediaError, prepare_image
from app.services.assessment_reconciliation import PhotoFinding, reconcile
```

- [ ] **Schritt 7: `assess_quality` umbauen**

Die bisherige Funktion behält Signatur und Rumpfanfang; nach dem Aufruf von `classify_disposition` kommt der Bildteil dazu:

```python
async def assess_quality(
    verified: VerifiedInternalRequest = Depends(verify_n8n_to_backend_request),
    llm: LlmClient = Depends(get_llm_client),
    vision: VisionClient | None = Depends(get_vision_client),
    runtime: RuntimeServices = Depends(get_runtime),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Bewertung durch die lokalen Modelle.

    Neu gegenueber Task 10: die Route LIEST aus Odoo, um an Meldefoto und
    Katalogbild zu kommen. Sie entscheidet und aendert weiterhin nichts --
    ueber Wirkung entscheidet ausschliesslich der Callback. Der Lesezugriff
    haengt an `job_id`, nie an einer mitgeschickten Alert-Kennung, und laeuft
    durch dieselbe Lease- und Generationspruefung wie die Medienroute.
    """
    body = _verified_body(
        QualityAssessmentV2Request, verified, idempotency_key, "event_id"
    )
    result = await llm.classify_disposition(
        description=body.description,
        priority=body.priority,
        photo_count=body.photo_count,
        product_id=body.product_id,
        location_id=body.location_id,
    )

    if vision is None:
        finding = PhotoFinding(
            article="unavailable",
            damage="unavailable",
            note="Bildpruefung abgeschaltet.",
        )
        checked = False
    else:
        odoo = get_callback_odoo_client(runtime, body.odoo_instance)
        finding, checked = await _collect_photo_finding(odoo, vision, body)

    reconciled = reconcile(
        disposition=result.disposition if result.ok else None,
        finding=finding,
    )

    return QualityAssessmentV2Response(
        llm_ok=result.ok,
        disposition=result.disposition if result.ok else None,
        confidence=result.confidence if result.ok else None,
        summary=result.summary if result.ok else None,
        recommended_action=result.recommended_action if result.ok else None,
        provider=LlmClient.PROVIDER,
        model=result.model,
        photo_checked=checked,
        contradiction=reconciled.contradiction,
        photo_analysis=reconciled.photo_analysis,
    )
```

- [ ] **Schritt 8: Tests laufen lassen**

```bash
docker exec mobilepickingundvoiceassistant-backend-1 rm -rf /app/tests
docker cp backend/tests mobilepickingundvoiceassistant-backend-1:/app/tests
docker exec -e ODOO_INSTANCES_JSON= mobilepickingundvoiceassistant-backend-1 \
  sh -c 'cd /app && python -m pytest tests/test_n8n_v2_assessment_route.py tests/test_llm_client.py -q'
```

Erwartet: alle grün, darunter `test_route_reads_media_but_never_writes` aus Schritt 3. `test_route_never_writes_to_odoo` existiert dann nicht mehr — er wurde ersetzt, nicht gelöscht: die Zusage ist enger gefasst, nicht aufgegeben.

Zusätzlich der Gesamtlauf, um zu belegen, dass nichts anderes gebrochen ist:

```bash
docker exec -e ODOO_INSTANCES_JSON= mobilepickingundvoiceassistant-backend-1 \
  sh -c 'cd /app && python -m pytest tests -q --ignore=tests/test_export_telemetry_stats.py --ignore=tests/live' \
  2>&1 | tail -3
```

Erwartet: nicht mehr als die 32 Fehlschläge, die im Container schon vorher rot waren.

- [ ] **Schritt 9: Committen**

```bash
git add backend/app/routers/n8n_v2.py backend/app/models/events.py \
        backend/app/services/llm_client.py backend/app/dependencies.py \
        backend/tests/test_n8n_v2_assessment_route.py
git commit -m "feat(backend): Bildbefund in die Bewertung verdrahten"
```

---

## Aufgabe 6: Fotoanalyse nach Odoo schreiben und zeigen

**Dateien:**
- Ändern: `odoo/addons/quality_alert_custom/models/quality_alert.py` (`api_apply_assessment`)
- Ändern: `odoo/addons/quality_alert_custom/views/quality_alert_views.xml:88-101`

**Schnittstellen:**
- Nutzt: den Schlüssel `photo_analysis` im `result`-Wörterbuch des Callbacks

- [ ] **Schritt 1: Den fehlschlagenden Test schreiben**

An `odoo/addons/quality_alert_custom/tests/test_assessment_media.py` anhängen:

```python
    def test_photo_analysis_is_stored_on_success(self):
        self.alert.api_apply_assessment(
            "succeeded",
            {
                "disposition": "scrap",
                "confidence": 0.9,
                "summary": "Kurzbegruendung.",
                "recommended_action": "Sperren.",
                "provider": "ollama-local",
                "model": "qwen2.5:7b",
                "photo_analysis": "Schadenspruefung: aufgerissene Zone.",
            },
            {},
        )
        self.assertIn("aufgerissene Zone", self.alert.ai_photo_analysis)

    def test_photo_analysis_is_stored_on_review_required(self):
        """Beim Hundefoto IST review_required das Ergebnis -- und der Grund
        dafuer ist der wertvollste Teil des Vorgangs. Das Urteil bleibt
        trotzdem leer: eine Beobachtung ist kein Urteil."""
        self.alert.api_apply_assessment(
            "review_required",
            {"photo_analysis": "Foto zeigt nicht den gemeldeten Artikel."},
            {},
        )
        self.assertIn("nicht den gemeldeten Artikel", self.alert.ai_photo_analysis)
        self.assertFalse(self.alert.ai_disposition)
```

- [ ] **Schritt 2: Test laufen lassen, Fehlschlag bestätigen**

Ausführen: der Odoo-Testbefehl aus Aufgabe 1 Schritt 2.
Erwartet: FEHLSCHLAG, `ai_photo_analysis` ist leer (`False`).

- [ ] **Schritt 3: Den Schreibpfad öffnen**

In `api_apply_assessment`, im `values`-Wörterbuch **vor** dem `if mapped == "completed"`:

```python
        values = {
            "ai_evaluation_status": mapped,
            "ai_last_analyzed_at": fields.Datetime.now(),
            "ai_failure_reason": error.get("message") or False,
            # Die Fotoanalyse wird bei JEDEM Status geschrieben, auch bei
            # review_required. Die Regel darunter -- nur `succeeded` darf
            # schreiben -- verhindert, dass ein URTEIL ohne Modell entsteht.
            # Eine Beobachtung ist kein Urteil, und beim Hundefoto ist
            # review_required das Ergebnis und die Beobachtung der Grund dafuer.
            "ai_photo_analysis": result.get("photo_analysis") or False,
        }
```

`ai_disposition` bleibt unangetastet und damit bei `review_required` weiterhin leer.

- [ ] **Schritt 4: Das Feld sichtbar machen**

In `quality_alert_views.xml`: `<field name="ai_photo_analysis"/>` aus der Gruppe mit `invisible="True"` (Zeile 98-101) entfernen und direkt nach dem Feld `ai_recommended_action` einfügen:

```xml
                            <field name="ai_photo_analysis"
                                   invisible="not ai_photo_analysis"/>
```

- [ ] **Schritt 5: Tests laufen lassen**

Ausführen: der Odoo-Testbefehl aus Aufgabe 1 Schritt 2.
Erwartet: fünf Tests grün.

- [ ] **Schritt 6: Committen**

```bash
git add odoo/addons/quality_alert_custom/models/quality_alert.py \
        odoo/addons/quality_alert_custom/views/quality_alert_views.xml \
        odoo/addons/quality_alert_custom/tests/test_assessment_media.py
git commit -m "feat(odoo): Fotoanalyse speichern und im Formular zeigen"
```

---

## Aufgabe 7: Den n8n-Workflow anpassen

**Dateien:**
- Ändern: `n8n/workflows/quality-assessment-v2.json`

Drei Änderungen, kein neuer Knoten. **Abweichung vom Entwurf, bewusst:** dort stand „ein neuer `If`-Knoten". Die Bedingung des vorhandenen `If Assessment OK` zu erweitern erreicht dasselbe mit weniger Fläche — der Workflow-Prüfer lässt hinter der Annahme ohnehin nur `pwrSignedHttpRequest`, `set`, `if` und `wait` zu, und ein Knoten weniger ist ein Knoten weniger.

- [ ] **Schritt 1: Die Zeitgrenze anheben**

Im Knoten `PWR Signed Assessment`, Parameter `timeoutMs`: `120000` → `180000`.

Bei drei Fotos sind es vier Bildaufrufe zu je rund 21 Sekunden, dazu das Texturteil. 120 Sekunden sind zu knapp. Der Kommissionierer wartet nicht — n8n hat nach `Accepted Response` längst mit 202 geantwortet.

- [ ] **Schritt 2: Die Verzweigung auf den Widerspruch ausweiten**

Im Knoten `If Assessment OK`, `conditions.boolean[0].value1`:

```
={{ $json.llm_ok && !$json.contradiction }}
```

Damit läuft ein Widerspruch in den bereits vorhandenen `Build Review Callback`. Der vermerkte Widerspruch aus Aufgabe 4 setzt `contradiction` ausdrücklich **nicht** und geht deshalb weiter über den Erfolgszweig.

- [ ] **Schritt 3: Die Fotoanalyse in beide Callbacks aufnehmen**

In `Build Success Callback`, im Ausdruck `callback_body`, im `result`-Objekt hinter `model: $json.model` ergänzen:

```
, photo_analysis: $json.photo_analysis
```

In `Build Review Callback` genauso. Dort ist `status` `review_required`, das Urteil bleibt leer, die Beobachtung reist mit.

- [ ] **Schritt 4: Prüfen und einspielen**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
python3 -c "import json; json.load(open('n8n/workflows/quality-assessment-v2.json')); print('JSON gueltig')"
bash infrastructure/scripts/import-workflows.sh
```

Danach im Browser auf `http://localhost:5678` den Workflow öffnen und bestätigen, dass er aktiv ist.

- [ ] **Schritt 5: Committen**

```bash
git add n8n/workflows/quality-assessment-v2.json
git commit -m "feat(n8n): Widerspruch verzweigt in den Review-Zweig"
```

---

## Aufgabe 8: Abnahme von Hand

**Dateien:** keine. Diese Aufgabe erzeugt Belege, keinen Code.

- [ ] **Schritt 1: Die Voraussetzung prüfen**

```bash
free -g | head -2   # gesamt >= 18 GB
nproc               # >= 8
```

Stimmt das nicht, ist `.wslconfig` nicht angepasst (`memory=20GB`, `processors=12`, danach `wsl --shutdown` in PowerShell). Ohne das laufen die Bildaufrufe in die Auslagerung und reißen die Zeitgrenze.

- [ ] **Schritt 2: Beide Modelle warmlaufen lassen**

```bash
docker exec mobilepickingundvoiceassistant-ollama-1 ollama run qwen2.5:7b "ok" --keepalive 24h
docker exec mobilepickingundvoiceassistant-ollama-1 ollama run qwen2.5vl:7b "ok" --keepalive 24h
docker exec mobilepickingundvoiceassistant-ollama-1 ollama ps
```

Erwartet: beide Modelle gleichzeitig in der Liste, zusammen rund 11 GB.

- [ ] **Schritt 3: Die vier Meldungen über die PWA absetzen**

Auf `https://localhost` anmelden, einen Auftrag beanspruchen, „Problem melden" und je einmal absenden:

| Foto | Beschreibung | Erwartetes Ergebnis |
|---|---|---|
| Hund | Verpackung defekt | Analyse-Status **In Prüfung**, Fotoanalyse nennt „nicht den gemeldeten Artikel" |
| makelloses LEGO | Artikel beschädigt | Einstufung **Totalschaden**, Fotoanalyse: „keinen sichtbaren Schaden … stichprobenartig prüfen" |
| gerissener Baustein | Artikel beschädigt | Einstufung **Totalschaden**, Fotoanalyse nennt die Auffälligkeit |
| heiler Baustein | Verpackung defekt | Einstufung **Verkaufbar**, Fotoanalyse: „keine Auffälligkeit sichtbar" |

- [ ] **Schritt 4: Das Ergebnis in der Datenbank nachlesen**

```bash
docker exec mobilepickingundvoiceassistant-db-1 psql -U odoo -d masterfischer_o19 -x -c \
 "select name, description, ai_evaluation_status, ai_disposition, ai_photo_analysis
    from quality_alert_custom order by id desc limit 4"
```

- [ ] **Schritt 5: Die Laufzeit belegen**

```bash
docker exec mobilepickingundvoiceassistant-db-1 psql -U odoo -d n8n -c \
 "select id, status, \"stoppedAt\" - \"startedAt\" as dauer
    from execution_entity order by id desc limit 4"
```

Erwartet: unter 180 Sekunden je Ausführung, Status `success`.

- [ ] **Schritt 6: Das Ergebnis festhalten**

Die vier Zeilen aus Schritt 4 und die Laufzeiten aus Schritt 5 als Abschnitt „Abnahme" an den Entwurf anhängen (`docs/superpowers/specs/2026-08-06-bildgestuetzte-qualitaetsbewertung-design.md`) und committen:

```bash
git add docs/superpowers/specs/2026-08-06-bildgestuetzte-qualitaetsbewertung-design.md
git commit -m "docs: Abnahme der bildgestuetzten Bewertung"
```

---

## Was dieser Plan nicht tut

- Kein Bindeweg für `pwr_media_ref`; die Medienroute bleibt ungenutzt und unangetastet.
- Keine neuen Odoo-Felder für `same_article` und `damaged`; der Klartext reicht.
- Keine besseren Katalogbilder; 192 × 192 genügt für den Artikelabgleich.
- Nichts für die 23 Produkte ohne Katalogbild außer dem Vermerk.
- Keine Änderung am Envelope, an der Signatur, an Lease oder Nonce.
