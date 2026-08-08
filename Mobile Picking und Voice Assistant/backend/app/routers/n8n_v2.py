"""Signierte v2-Routen fuer den n8n -> Backend Rueckweg.

Zwei Endpunkte, ein Sicherheitsmodell:

1. `verify_n8n_to_backend_request` prueft die HMAC-Signatur des ROHEN Requests
   als FastAPI-Dependency, also bevor der Handler-Body ueberhaupt laeuft. Der
   Handler bekommt den Body nur als `VerifiedInternalRequest.raw_body` -- es
   gibt keinen Pfad, auf dem ein unverifizierter Body geparst oder an Odoo
   weitergegeben wird.
2. Danach laufen fuer BEIDE Routen dieselben Guards in derselben Reihenfolge,
   zentral in `_verified_body()`, damit eine Verteidigung nicht in einer Route
   sitzt und in der anderen fehlt: Schema (strict, `extra=forbid`) ->
   Idempotency-Key == Identifier im signierten Body -> signierte
   Delivery-Generation == Generation im signierten Body.
3. Erst danach wird die Ziel-Instanz aufgeloest, und zwar ausschliesslich aus
   `odoo_instance` im SIGNIERTEN Body via `get_callback_odoo_client` (Allowlist
   gegen das serverseitige Register). `X-Odoo-Instance`, Query-Parameter und ein
   `local`-Fallback existieren hier bewusst nicht.

Absichtlich NICHT vorhanden: `get_odoo_client`, `WriteRequestContext`,
`X-N8N-Callback-Secret`, Session/CSRF/Grace-Mode. Der Legacy-Router
`n8n_internal.py` bleibt unveraendert v1 und nur im internen Netz erreichbar,
bis seine Workflows migriert sind.

Task 11 haengt zwei weitere Routen an denselben Wachposten:
`GET  /instances/{i}/jobs/{j}/leases/{t}/media/{m}` und
`POST /instances/{i}/jobs/{j}/leases/{t}/events/{e}/artifacts/{k}`. Sie tragen
Job, Quell-Event und Artefaktart im PFAD statt im Body -- der Pfad ist Teil der
kanonischen Signatureingabe, ist also genauso gebunden wie ein signiertes
Body-Feld. Deshalb wurde der Router-Prefix auf `/internal` verkuerzt und die
v2-Routen tragen ihren Pfad selbst; die vollstaendigen URLs der Task-10-Routen
bleiben dabei Byte-fuer-Byte dieselben (`/api/internal/n8n/v2/...`), und
`main.py` (Task 9) musste nicht angefasst werden. Das `/leases/{t}`-Segment
kam in Fix-Runde 1 (#5b) dazu, aus demselben Grund: der Processing-Lease-Token
ist ab da ebenfalls Teil des PFADs statt eines JSON-Koerpers.

Fuer die Binaerrouten gilt zusaetzlich: rohe Bytes rein, rohe Bytes raus.
Base64 existiert ausschliesslich auf dem internen JSON-RPC-Hop zu Odoo und
taucht in keiner HTTP-Antwort, keinem Log und keinem Event auf.

Replay-Schutz und Zustandslogik liegen in Odoo (Task 8): `api_accept_event`
und `api_apply_callback` reservieren die Nonce im Store
`picking.assistant.webhook.nonce` in derselben Transaktion wie die
Zustandsaenderung. Jeder Odoo-Konflikt (Replay, Lease-Mismatch, unbekannter
Job, Generation) wird hier auf ein generisches 409 abgebildet -- die
Odoo-Meldung wird nie an den Aufrufer durchgereicht, damit die Antwort nicht
verraet, ob ein Job, ein Event oder ein Receipt existiert.
"""
import asyncio
import base64
import binascii
import hashlib
import logging
import re
import time
from hmac import compare_digest
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.dependencies import (
    VerifiedInternalRequest,
    get_callback_odoo_client,
    get_llm_client,
    get_runtime,
    get_vision_client,
    verify_n8n_to_backend_request,
)
from app.models.events import (
    CallbackApplyResponse,
    CallbackEnvelopeV2,
    EventAcceptanceRequest,
    EventAcceptanceResponse,
    QualityAssessmentV2Request,
    QualityAssessmentV2Response,
)
from app.config import settings
from app.services.llm_client import LlmClient
from app.services.vision_client import DamageCheck, VisionClient
from app.services.assessment_media import DAMAGE_MAX_EDGE, MediaError, prepare_image
from app.services.assessment_reconciliation import PhotoFinding, reconcile
from app.services.binary_validation import (
    ARTIFACT_KINDS,
    BinaryValidationError,
    ValidatedBinary,
    precheck_artifact,
    sanitize_filename,
    validate_artifact,
    validate_image,
)
from app.runtime import RuntimeServices
from app.services.odoo_client import OdooAPIError

router = APIRouter(prefix="/internal")

V2 = "/n8n/v2"

logger = logging.getLogger(__name__)

# EINE Bewertung zur Zeit. n8n laesst drei Ausfuehrungen parallel zu und der
# Dispatcher reiht nur die ZUSTELLUNG auf -- der Webhook antwortet sofort, die
# Modellarbeit laeuft danach. Zwei Bewertungen trafen sich so in Ollama, und
# ein Rechner ohne GPU haelt ein 7B-Text- und ein 7B-Bildmodell nicht
# gleichzeitig aus: gemessen wurden 1m30 bis 3m20 statt 8 s und zwei HTTP 500.
#
# Die Sperre gilt in DIESEM Prozess. Das reicht, solange das Backend mit einem
# uvicorn-Worker laeuft (siehe docker-compose). Mehrere Worker oder Repliken
# brauchen eine Sperre in Ollama oder davor -- eine Semaphore im Speicher
# waere dann eine Sperre, die nicht sperrt.
_ASSESSMENT_GATE = asyncio.Semaphore(1)


def _parse(model, raw_body: bytes):
    try:
        return model.model_validate_json(raw_body)
    except ValidationError as exc:
        # Ohne `input`/`ctx`: der 422-Body benennt nur Feld und Fehlerart und
        # spiegelt keine eingesandten Werte zurueck (die sonst in Proxy-Logs
        # landen wuerden).
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_url=False, include_context=False, include_input=False),
        ) from exc


def _verified_body(model, verified: VerifiedInternalRequest, idempotency_key: str | None,
                   identifier_field: str):
    """Die EINE Guard-Kette beider v2-Routen (siehe Modul-Docstring, Punkt 2).

    Der `Idempotency-Key`-Header ist selbst nicht signiert; er muss deshalb
    exakt dem Identifier im signierten Body entsprechen, sonst wird abgelehnt
    (auch wenn er fehlt). Die Delivery-Generation ist Teil der kanonischen
    Signatureingabe -- weicht sie vom signierten Body ab, ist das ein Konflikt,
    kein 200.
    """
    body = _parse(model, verified.raw_body)
    expected_identifier = str(getattr(body, identifier_field))
    if not idempotency_key or idempotency_key != expected_identifier:
        raise HTTPException(status_code=409, detail="Idempotency key mismatch.")
    if verified.signature.delivery_generation != body.delivery_generation:
        raise HTTPException(status_code=409, detail="Delivery generation mismatch.")
    return body


def _required(result: Any, key: str) -> Any:
    """Fehlende oder unerwartet geformte Odoo-Antworten sind ein Konflikt, kein
    500 und kein stillschweigendes `None`."""
    if not isinstance(result, dict) or key not in result:
        raise HTTPException(status_code=409, detail="Unexpected receipt result.")
    return result[key]


def _require_job_match(result: Any, job_id) -> Any:
    if str(_required(result, "job_id")) != str(job_id):
        raise HTTPException(status_code=409, detail="Receipt job mismatch.")
    return result


def _require_bool(result: Any, key: str) -> bool:
    """`process` entscheidet, ob n8n den Job tatsaechlich ausfuehrt. Deshalb
    kein `bool(...)`-Cast: ein truthy String (z. B. "false") duerfte sonst
    stillschweigend zu `True` werden."""
    value = _required(result, key)
    if not isinstance(value, bool):
        raise HTTPException(status_code=409, detail="Unexpected receipt result.")
    return value


def _receipt_response(model, **values):
    """Baut die Antwort BEIDER Routen. Eine schemawidrige Odoo-Antwort ist ein
    Konflikt, kein 500 -- und weil beide Routen durch diese Funktion gehen,
    kann die Absicherung nicht in einer Route fehlen."""
    try:
        return model(**values)
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail="Unexpected receipt result.") from exc


@router.post(V2 + "/events/accept", response_model=EventAcceptanceResponse)
async def accept_event(
    verified: VerifiedInternalRequest = Depends(verify_n8n_to_backend_request),
    runtime: RuntimeServices = Depends(get_runtime),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    body = _verified_body(
        EventAcceptanceRequest, verified, idempotency_key, "event_id"
    )
    odoo = get_callback_odoo_client(runtime, body.odoo_instance)
    try:
        result = await odoo.execute_kw(
            "picking.assistant.event.receipt",
            "api_accept_event",
            [
                str(body.event_id),
                str(body.job_id),
                body.payload_fingerprint,
                body.ingress_key_id,
                str(body.ingress_nonce),
                body.delivery_generation,
                verified.signature.key_id,
                verified.signature.nonce,
            ],
        )
    except OdooAPIError as exc:
        raise HTTPException(status_code=409, detail="Event acceptance conflict.") from exc
    _require_job_match(result, body.job_id)
    return _receipt_response(
        EventAcceptanceResponse,
        accepted=True,
        event_id=body.event_id,
        process=_require_bool(result, "process"),
        processing_lease_token=result.get("processing_lease_token") or None,
    )


@router.post(V2 + "/callbacks/status", response_model=CallbackApplyResponse)
async def apply_callback(
    verified: VerifiedInternalRequest = Depends(verify_n8n_to_backend_request),
    runtime: RuntimeServices = Depends(get_runtime),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    body = _verified_body(
        CallbackEnvelopeV2, verified, idempotency_key, "callback_id"
    )
    odoo = get_callback_odoo_client(runtime, body.odoo_instance)
    try:
        result = await odoo.execute_kw(
            "picking.assistant.callback.receipt",
            "api_apply_callback",
            [
                body.model_dump(mode="json"),
                verified.signature.fingerprint,
                verified.signature.key_id,
                verified.signature.nonce,
            ],
        )
    except OdooAPIError as exc:
        raise HTTPException(status_code=409, detail="Callback state conflict.") from exc
    _require_job_match(result, body.job_id)
    # Explizit aus benannten Feldern gebaut statt `model_validate(result)`:
    # `api_apply_callback` liefert zusaetzlich `callback_id` und `job_state`,
    # und `CallbackApplyResponse` ist ein StrictModel (`extra=forbid`). Ein
    # unbekannter `status` ist ein Konflikt, kein 500.
    return _receipt_response(
        CallbackApplyResponse,
        status=_required(result, "status"),
        job_id=_required(result, "job_id"),
        sequence=_required(result, "sequence"),
    )


async def _collect_photo_finding(
    odoo, vision: VisionClient, llm: LlmClient, body
) -> tuple[PhotoFinding, bool]:
    """Holt die Bilder und laesst das Bildmodell darauf schauen.

    Gibt `(Befund, geprueft)` zurueck. `geprueft` ist False, sobald gar nichts
    zu sehen war -- dann steht der Grund im Klartext und das Texturteil bleibt
    allein stehen. Ein halber Bildbefund entsteht hier nie: jeder Fehlerpfad
    endet in "unavailable", nicht in einer Vermutung.
    """
    try:
        media = await odoo.execute_kw(
            "quality.alert.custom",
            "api_get_assessment_media",
            [str(body.job_id), body.delivery_generation, body.processing_lease_token],
        )
    except Exception as exc:  # noqa: BLE001 - jeder Fehler heisst: kein Bildbefund
        return _no_finding(f"Bildpruefung nicht moeglich: {exc}"), False

    photos = (media or {}).get("photos") or []
    if not photos:
        return _no_finding("Ohne Bildpruefung: der Meldung liegt kein Foto bei."), False

    # JEDES Foto fuer sich aufbereiten. Vorher lag die ganze Liste in einem
    # try: ein unlesbarer Anhang loeschte damit den Befund aller anderen --
    # und der erste Anhang ist der einzige, den der Artikelabgleich ueberhaupt
    # ansieht. Ein Foto, das nicht durchkommt, wird gezaehlt und genannt.
    #
    # Zwei Aufbereitungen desselben Fotos, weil die beiden Fragen
    # unterschiedlich viel Aufloesung vertragen: der Artikelabgleich bleibt
    # klein, die Schadenspruefung sieht nur ein Bild und darf groesser sein.
    # Bei 512 px verschwanden zwei von drei gemessenen Rissen (siehe
    # `assessment_media`).
    candidates: list[bytes] = []
    damage_candidates: list[bytes] = []
    unlesbar = 0
    for photo in photos:
        try:
            raw = base64.b64decode(photo["data_b64"])
            candidates.append(prepare_image(raw))
            damage_candidates.append(prepare_image(raw, max_edge=DAMAGE_MAX_EDGE))
        except (MediaError, KeyError, ValueError, binascii.Error):
            unlesbar += 1
    if not candidates:
        return _no_finding("Bildpruefung nicht moeglich: kein lesbares Foto."), False

    # Dasselbe Katalogbild in der zweiten Aufloesung, aus demselben Grund wie
    # oben beim Meldefoto: der Artikelabgleich fragt "welches Teil?" und kommt
    # mit 512 px aus, der Zustandsvergleich fragt "welcher Zustand?" und braucht
    # dieselben 768 px wie das Foto, gegen das er gestellt wird. Fehlt oder
    # bricht es, bleibt es None und die Schadenspruefung arbeitet wie bisher
    # allein auf dem Meldefoto.
    reference_damage: bytes | None = None
    reference_b64 = media.get("reference_image_b64")
    if reference_b64:
        try:
            reference_damage = prepare_image(
                base64.b64decode(reference_b64), max_edge=DAMAGE_MAX_EDGE
            )
        except (MediaError, ValueError, binascii.Error):
            reference_damage = None

    lines: list[str] = []
    deadline = time.monotonic() + max(0.0, settings.vision_budget_ms / 1000.0)
    article = await _check_article(vision, llm, media, candidates[0], lines, deadline)
    # Lief der Artikelabgleich, sind seine Bildaufrufe verbraucht und die
    # Schadenspruefung haengt vollstaendig am Budget. Fiel er aus (kein
    # Katalogbild), muss sie den einen garantierten Aufruf tragen.
    damage, ungeprueft = await _check_damage(
        vision,
        llm,
        damage_candidates,
        lines,
        deadline,
        garantiert=article == "unavailable",
        # Bei `mismatch` KEIN Zustandsvergleich. Er stellt das Foto gegen das
        # Katalogbild des BESTELLTEN Artikels -- zeigt das Foto ein anderes
        # Teil, vergleicht er zwei verschiedene Dinge und die Aussage ist
        # wertlos. Gemessen am 2026-08-08 (QA/0229): gegen ein Hundefoto kam
        # "keine Abweichung vom Neuzustand" heraus und stand so im Odoo-Formular.
        # `reconcile` behandelt `mismatch` ohnehin als vorrangig; die Zeile
        # widerspricht ihm nur. Die Schadenspruefung selbst laeuft weiter --
        # dass am falschen Teil etwas gebrochen ist, will man trotzdem wissen.
        reference=None if article == "mismatch" else reference_damage,
        product_label=media.get("product_label") or "",
    )

    if unlesbar:
        lines.append(f"{unlesbar} Foto(s) nicht lesbar.")
    skipped = int(media.get("photo_total") or len(photos)) - len(photos) + ungeprueft
    if skipped > 0:
        lines.append(f"{skipped} weitere Foto(s) ungeprueft.")

    checked = article != "unavailable" or damage != "unavailable"
    return PhotoFinding(article=article, damage=damage, note="\n".join(lines)), checked


def _no_finding(note: str) -> PhotoFinding:
    return PhotoFinding(article="unavailable", damage="unavailable", note=note)


async def _check_article(
    vision, llm, media, candidate: bytes, lines: list[str], deadline: float
) -> str:
    """Artikelabgleich gegen das Katalogbild. Nur auf dem ersten Foto.

    Drei Aufrufe statt einem: das Bildmodell beschreibt Katalogbild und
    Meldefoto EINZELN, das Textmodell vergleicht die zwei Beschreibungen. Mit
    beiden Bildern in einem Aufruf beschrieb das Bildmodell aehnliche Bilder
    gleich und haette einen verwechselten Artikel durchgewinkt -- gemessen am
    2026-08-07, Einzelheiten in `vision_client.DESCRIBE_PROMPT`.

    Das MELDEFOTO wird zuerst beschrieben. Reisst danach das Budget, steht
    wenigstens im Klartext, was auf dem Foto zu sehen war; umgekehrt haette man
    eine Beschreibung des Katalogbilds, die niemand braucht.
    """
    reference_b64 = media.get("reference_image_b64")
    if not reference_b64:
        lines.append("Artikelabgleich entfaellt: kein Katalogbild hinterlegt.")
        return "unavailable"
    try:
        reference = prepare_image(base64.b64decode(reference_b64))
    except (MediaError, ValueError, binascii.Error) as exc:
        lines.append(f"Artikelabgleich nicht moeglich: {exc}")
        return "unavailable"

    candidate_seen = await vision.describe(candidate)
    if not candidate_seen.ok:
        lines.append("Artikelabgleich nicht moeglich: Bildmodell antwortet nicht.")
        return "unavailable"
    if time.monotonic() >= deadline:
        lines.append(
            f"Foto zeigt: {candidate_seen.text}. Artikelabgleich nicht "
            "abgeschlossen: Zeitbudget erschoepft."
        )
        return "unavailable"

    reference_seen = await vision.describe(reference)
    if not reference_seen.ok:
        lines.append(
            f"Foto zeigt: {candidate_seen.text}. Artikelabgleich nicht "
            "moeglich: Katalogbild nicht auswertbar."
        )
        return "unavailable"

    label = media.get("product_label") or ""
    verdict = await llm.compare_articles(
        reference_text=reference_seen.text,
        candidate_text=candidate_seen.text,
        # Ohne die interne Nummer: Odoo liefert "[6023350] Brick 2x2x2 R=15
        # gelb", und an einer Zahl, die auf keinem Foto steht, hat ein Modell
        # nichts zu pruefen. Im Klartext fuer den Menschen bleibt sie stehen --
        # dort identifiziert sie den Artikel.
        product_label=_ohne_artikelnummer(label),
    )
    if not verdict.ok:
        lines.append("Artikelabgleich nicht moeglich: Textmodell antwortet nicht.")
        return "unavailable"
    if verdict.same_article:
        lines.append("Artikelabgleich: stimmt mit Katalogbild ueberein.")
        return "match"
    lines.append(
        "Foto zeigt nicht den gemeldeten Artikel: "
        f"{candidate_seen.text} statt {label or 'dem gemeldeten Artikel'}."
    )
    return "mismatch"


def _ohne_artikelnummer(label: str) -> str:
    """"[6023350] Brick 2x2x2 R=15 gelb" -> "Brick 2x2x2 R=15 gelb"."""
    gekuerzt = re.sub(r"^\s*\[[^\]]*\]\s*", "", label)
    return gekuerzt.strip()


async def _check_damage(
    vision,
    llm,
    candidates: list[bytes],
    lines: list[str],
    deadline: float,
    garantiert: bool,
    reference: bytes | None = None,
    product_label: str = "",
) -> tuple[str, int]:
    """Schadenspruefung auf JEDEM Foto. Ein einziger Fund genuegt.

    Getrennt vom Artikelabgleich, weil beides zusammen gemessen schlechter
    ist: im Zwei-Bild-Aufruf wurde ein sichtbarer Bruch als "decorative
    element" abgetan.

    Zwei Stufen. Zuerst schaut das Bildmodell jedes Foto FUER SICH an und
    beantwortet die absolute Frage: bricht hier etwas die glatte Oberflaeche?
    Liegt ein Katalogbild vor, folgt der Soll/Ist-Vergleich des Zustands
    (`_zustandsvergleich`) und darf den Befund NUR VERSCHAERFEN. Die absolute
    Frage allein reicht nicht: ein sauber abgebrochenes Eck laesst sie durch,
    weil eine glatte Bruchflaeche keine ausgefranste Stelle ist. Umgekehrt darf
    der Vergleich nichts zuruecknehmen -- am 2026-08-08 (QA/0223) hat er einen
    gefundenen Riss wegerklaert; die Begruendung steht in `_zustandsvergleich`.

    `deadline` begrenzt die Reihe als Ganzes. `garantiert` erzwingt das erste
    Foto auch bei abgelaufenem Budget -- ein Budget, das gar keinen Bildaufruf
    zulaesst, waere dasselbe wie eine abgeschaltete Bildpruefung, nur
    unausgesprochen. Gesetzt wird es nur, wenn der Artikelabgleich ausfiel;
    sonst hat der den garantierten Aufruf schon getragen. Liefert neben dem
    Befund die Zahl der Fotos, die dafuer liegen blieben.
    """
    damage = "unavailable"
    seen: list[str] = []
    befunde: list[DamageCheck] = []
    ungeprueft = 0
    budget_gerissen = False
    for index, candidate in enumerate(candidates):
        if not (garantiert and index == 0) and time.monotonic() >= deadline:
            ungeprueft += len(candidates) - index
            budget_gerissen = True
            break
        check = await vision.inspect_damage(candidate)
        if not check.ok:
            # Ein Foto ohne Antwort ist ein UNGEPRUEFTES Foto. Vorher wurde es
            # uebersprungen und nirgends gezaehlt: bei drei Fotos, von denen
            # nur das erste antwortete, stand am Ende "keine Auffaelligkeit
            # sichtbar" -- eine Aussage ueber zwei Bilder, die niemand
            # angesehen hat.
            ungeprueft += 1
            continue
        befunde.append(check)
        if check.damaged:
            damage = "damaged"
            seen.extend(check.anomalies)
        elif damage != "damaged":
            damage = "intact"

    # VOR dem Klartext, damit Satz und Befund nicht auseinanderlaufen: der
    # Vergleich darf `damage` noch drehen, und die Zeile darunter beschreibt
    # dann den gedrehten Stand. Seine eigene Zeile kommt danach.
    zustandszeile: str | None = None
    if damage != "unavailable" and reference is not None:
        damage, zustandszeile = await _zustandsvergleich(
            vision=vision,
            llm=llm,
            reference=reference,
            befunde=befunde,
            damage=damage,
            deadline=deadline,
            product_label=product_label,
        )

    if damage == "unavailable":
        lines.append(
            "Schadenspruefung nicht moeglich: Zeitbudget erschoepft."
            if budget_gerissen and not seen
            else "Schadenspruefung nicht moeglich: Bildmodell antwortet nicht."
        )
    elif damage == "damaged":
        # Der Befund steht vorn, die Worte des Modells dahinter in Klammern.
        # Sie sind englisch und manchmal schief -- am Rissfoto aus QA/0011 kam
        # "feather" zurueck. Als ganze Zeile ("Schadenspruefung: feather.")
        # liest das im Lager niemand als Schaden; hinter der Aussage ist es ein
        # Hinweis, wo man hinschauen soll.
        detail = ", ".join(seen)
        lines.append(
            "Schadenspruefung: Schaden sichtbar"
            + (f" ({detail})" if detail else "")
            + "."
        )
    elif ungeprueft:
        # "Keine Auffaelligkeit sichtbar" waere hier eine Aussage ueber Fotos,
        # die niemand angesehen hat. Der Satz nennt deshalb, wieviel er deckt.
        geprueft = len(candidates) - ungeprueft
        lines.append(
            f"Schadenspruefung: {geprueft} von {len(candidates)} Foto(s) "
            "geprueft, dabei keine Auffaelligkeit sichtbar."
        )
    else:
        lines.append("Schadenspruefung: keine Auffaelligkeit sichtbar.")
    if zustandszeile:
        lines.append(zustandszeile)
    return damage, ungeprueft


# Der Zustandsbefund eines Katalogbilds haengt nur am Katalogbild. Das ist je
# Artikel dasselbe Byte fuer Byte, also ist es auch sein Befund. Ohne diesen
# Speicher kostete der Vergleich JEDE Meldung einen zusaetzlichen Bildaufruf --
# auf CPU 20 bis 100 Sekunden, gegen einen n8n-Knoten, der bei 270 Sekunden
# hart abschneidet. Er lebt im Prozess und ist nach einem Neustart des Backends
# wieder leer; das kostet dann einmal je Artikel, nicht je Meldung.
_SOLL_BEFUNDE: dict[str, DamageCheck] = {}


async def _soll_befund(vision, reference: bytes) -> DamageCheck:
    """Zustandsbefund des Katalogbilds. Einmal je Artikel, danach aus dem Speicher.

    Gespeichert wird nur ein Befund, der zustande kam. Ein gescheiterter Aufruf
    darf sich nicht als "kein Schaden im Neuzustand" festsetzen -- er ist keine
    Aussage ueber das Bild, sondern ueber das Modell.
    """
    schluessel = hashlib.sha256(reference).hexdigest()
    gespeichert = _SOLL_BEFUNDE.get(schluessel)
    if gespeichert is not None:
        return gespeichert
    befund = await vision.inspect_damage(reference)
    if befund.ok:
        _SOLL_BEFUNDE[schluessel] = befund
    return befund


async def _zustandsvergleich(
    *,
    vision,
    llm,
    reference: bytes,
    befunde: list[DamageCheck],
    damage: str,
    deadline: float,
    product_label: str,
) -> tuple[str, str | None]:
    """Soll/Ist des ZUSTANDS: Katalogbild gegen Meldefoto.

    Dasselbe Verfahren wie beim Artikelabgleich und aus demselben gemessenen
    Grund: jedes Bild wird EINZELN beschrieben, verglichen wird im Text. Nur
    die Frage ist eine andere -- dort "welches Teil?", hier "welcher Zustand?".

    Der Vergleich darf NUR ESKALIEREN. Er hebt "intact" auf "damaged", aber er
    macht aus "damaged" nie wieder "intact". Dieselbe Asymmetrie wie in
    `assessment_reconciliation` und aus demselben Grund: die Stufe, die etwas
    gesehen hat, darf nicht von der Stufe ueberstimmt werden, die nur
    Beschreibungen vergleicht.

    Gemessen am 2026-08-08, QA/0223: das Rissfoto aus QA/0011, Artikel
    [6023350]. Die absolute Pruefung fand die Stelle ("feather"), der Vergleich
    erklaerte sie weg -- "Die Beschreibungen stimmen in Bezug auf glatte
    Oberflaeche ueberein." Beide Zustandsbeschreibungen enthalten das Wort
    "smooth", und daran haengt sich das Textmodell auf. Es ist derselbe Fehler,
    an dem der Zwei-Bild-Aufruf gescheitert ist, nur eine Ebene hoeher: was
    beide Bilder gemeinsam haben, uebertoent den Unterschied.

    Was bleibt, ist die Richtung, in der die absolute Pruefung nichts hat: ein
    sauber abgebrochenes Eck hinterlaesst keine ausgefranste Stelle. Sie sieht
    eine glatte Oberflaeche und laesst es durch; erst gegen den Neuzustand
    faellt auf, dass etwas fehlt.

    Ausgewertet wird der Befund des Fotos, das Schaden zeigte -- sonst der erste
    lesbare. Jeder Fehlerpfad gibt `damage` unveraendert zurueck und sagt im
    Klartext, warum: ein ausgefallener Vergleich ist kein Freispruch.
    """
    ist = next((befund for befund in befunde if befund.damaged), None)
    if ist is None:
        ist = befunde[0] if befunde else None
    if ist is None or not ist.description:
        return damage, None
    if time.monotonic() >= deadline:
        return damage, "Zustandsvergleich nicht durchgefuehrt: Zeitbudget erschoepft."

    soll = await _soll_befund(vision, reference)
    if not soll.ok or not soll.description:
        return damage, "Zustandsvergleich nicht moeglich: Katalogbild nicht auswertbar."

    urteil = await llm.compare_condition(
        reference_text=soll.description,
        candidate_text=ist.description,
        product_label=_ohne_artikelnummer(product_label),
    )
    if not urteil.ok:
        return damage, "Zustandsvergleich nicht moeglich: Textmodell antwortet nicht."

    grund = f" ({urteil.reason})" if urteil.reason else ""
    if not urteil.new_damage:
        # KEIN Freispruch, auch wenn er sich so liest. Sieht die absolute
        # Pruefung einen Schaden, bleibt er stehen; der Vergleich vermerkt nur,
        # dass er ihn im Abgleich nicht wiederfindet. Das ist eine Aussage
        # ueber den Vergleich, nicht ueber die Ware.
        if damage == "damaged":
            return damage, (
                "Zustandsvergleich gegen Katalogbild findet die Auffaelligkeit "
                f"nicht wieder{grund}. Der Befund der Schadenspruefung bleibt stehen."
            )
        return damage, (
            "Zustandsvergleich gegen Katalogbild: keine Abweichung vom "
            f"Neuzustand{grund}."
        )
    if damage == "damaged":
        return damage, (
            f"Zustandsvergleich gegen Katalogbild bestaetigt den Befund{grund}."
        )
    return "damaged", (
        "Zustandsvergleich gegen Katalogbild: Abweichung vom Neuzustand, die "
        f"der Schadenspruefung entgangen ist{grund}."
    )


@router.post(V2 + "/assessments/quality", response_model=QualityAssessmentV2Response)
async def assess_quality(
    verified: VerifiedInternalRequest = Depends(verify_n8n_to_backend_request),
    llm: LlmClient = Depends(get_llm_client),
    vision: VisionClient | None = Depends(get_vision_client),
    runtime: RuntimeServices = Depends(get_runtime),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Bewertung durch die lokalen Modelle -- lesend auf Odoo, nie schreibend.

    Sie ersetzt das geloeschte `/api/internal/llm/quality-disposition`, das
    auf `X-N8N-Callback-Secret` bestand -- einen Header, den ein v2-Workflow
    gar nicht mitschicken kann, weil `PwrSignedHttpRequest` nur
    `pwrOutboundHmac` kennt und seine Header selbst baut.

    **Geaendert gegenueber Task 10:** die Route LIEST aus Odoo, um an Meldefoto
    und Katalogbild zu kommen. Sie entscheidet und aendert weiterhin nichts --
    ueber Wirkung entscheidet ausschliesslich der Callback. Der Lesezugriff
    haengt an `job_id`, nie an einer mitgeschickten Alert-Kennung, und laeuft
    in Odoo durch dieselbe Lease- und Generationspruefung wie die Medienroute.

    Der Ablauf dahinter: Bilder holen, Artikel abgleichen, Schaden pruefen,
    Text bewerten, abgleichen. Das Textmodell bekommt den Bildbefund NICHT --
    nur deshalb laesst sich sein Urteil anschliessend daran pruefen.
    """
    body = _verified_body(
        QualityAssessmentV2Request, verified, idempotency_key, "event_id"
    )

    # Ab hier laufen die Modelle, und ab hier nur EINE Bewertung gleichzeitig.
    try:
        await asyncio.wait_for(
            _ASSESSMENT_GATE.acquire(),
            timeout=max(0.0, settings.assessment_wait_ms / 1000.0),
        )
    except asyncio.TimeoutError:
        logger.warning(
            '{"event_type": "assessment_busy", "event_id": "%s"}', body.event_id
        )
        return _busy_response()
    try:
        return await _assess(llm, vision, runtime, body)
    finally:
        _ASSESSMENT_GATE.release()


def _busy_response() -> QualityAssessmentV2Response:
    """Kein Urteil, aber ein Grund. Die Meldung geht an einen Menschen.

    Die Alternative waere, trotzdem loszulaufen -- und genau das hat am
    2026-08-07 zwei Bewertungen auf einmal zerlegt.
    """
    return QualityAssessmentV2Response(
        llm_ok=False,
        disposition=None,
        confidence=None,
        summary=None,
        recommended_action=None,
        provider=LlmClient.PROVIDER,
        # Das Modell, das gelaufen WAERE. `model` ist im Vertrag Pflicht, und
        # ein erfundener Platzhalter waere schlimmer als der wahre Name: bei
        # `llm_ok=False` bleibt ohnehin jedes Urteilsfeld leer.
        model=settings.llm_model,
        photo_checked=False,
        contradiction=False,
        photo_analysis=(
            "Keine Bewertung: eine andere Meldung wurde zur selben Zeit "
            "bewertet, und die Modelle laufen nur nacheinander."
        ),
    )


async def _assess(llm, vision, runtime, body) -> QualityAssessmentV2Response:
    result = await llm.classify_disposition(
        description=body.description,
        priority=body.priority,
        photo_count=body.photo_count,
        product_id=body.product_id,
        location_id=body.location_id,
    )

    if vision is None:
        finding = _no_finding("Bildpruefung abgeschaltet.")
        checked = False
    else:
        odoo = get_callback_odoo_client(runtime, body.odoo_instance)
        finding, checked = await _collect_photo_finding(odoo, vision, llm, body)

    reconciled = reconcile(
        disposition=result.disposition if result.ok else None,
        finding=finding,
    )

    # Bei `ok=False` bleibt JEDES Urteilsfeld leer. Ein halb gefuelltes
    # Ergebnis waere die Einladung, im Workflow doch daraus zu schliessen.
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


# ===========================================================================
# Task 11: job-gebundene Medien und Artefakte
# ===========================================================================
#
# Beide Routen laufen durch dieselbe Wache wie die Routen oben und danach
# durch EINE gemeinsame Reihenfolge, damit keine Verteidigung in der einen
# Route sitzt und in der anderen fehlt:
#
#   1. Pfadform (UUID / Lease-Token / Allowlist-Referenz / Allowlist-Artefaktart)
#   2. Idempotency-Key (nur POST -- GET veraendert nichts)
#   3. Zielinstanz aus dem Pfad, Allowlist gegen das Instanzregister
#   4. billige Inhaltsvorpruefung (nur POST): Groesse, Magic, deklarierter
#      Typ, ZPL-Kommandoscan -- linear, ohne Parser und ohne Dekompression
#   5. Nonce-Reservierung in Odoo -- job-, generations- UND (Fix-Runde 1)
#      lease-token-gebunden
#   6. teure Inhaltsvalidierung (nur POST): PDF-Objektgraph, Expansionsbudget
#   7. Odoo-Zugriff auf die Ressource
#
# Die Dreiteilung 4/5/6 ist die Aufloesung eines Zielkonflikts, dessen beide
# Seiten im Review vorgefuehrt wurden (Details in `precheck_artifact`):
# reserviert man die Nonce zuerst, verbrennt jede ungueltige Nutzlast eine;
# validiert man zuerst vollstaendig, erzwingt dieselbe wiedervorgelegte
# Anfrage jedes Mal den vollen Parser- und Inflationsaufwand. Billig zuerst,
# dann das Replay-Gate, dann teuer -- WER DIESE REIHENFOLGE AENDERT, MACHT
# EINEN DER BEIDEN ANGRIFFE WIEDER AUF.
#
# Die Generation stammt IMMER aus der verifizierten Signatur, nie aus Pfad,
# Query oder Body -- eine veraltete Generation kann damit weder lesen noch
# anhaengen, und Odoo prueft sie unter Sperre ein zweites Mal. Das
# Lease-Token (Fix-Runde 1, #5b) stammt aus dem PFAD -- wie `job_id`,
# `media_ref`, `source_event_id` und `artifact_kind` bereits -- und ist damit
# Teil des signierten `target`, ohne die JSON-Koerper-freie Bauart dieser
# beiden Routen (Task 11: "rohe Bytes rein, rohe Bytes raus") oder die
# gemeinsame HMAC-Kanonisierung anderer v2-Routen anzufassen.

# Fix-round-1 (#5b, Odoo half was Task 8): the lease token travels as a PATH
# segment, not a JSON body field. `get_job_media` is a bodyless GET and
# `store_job_artifact`'s body is the raw artifact bytes ("rohe Bytes rein,
# rohe Bytes raus", Task 11) -- neither route has a JSON envelope to add a
# field to without breaking that invariant, and the shared HMAC canonical
# signature (`hmac_signing.py`) is consumed by every v2 route including
# events/accept and callbacks/status, so extending IT would be a much larger,
# separately-reviewed change. A path segment needs neither: `job_id`,
# `media_ref`, `source_event_id` and `artifact_kind` are already path
# segments and are therefore already part of the signed `target`
# (`hmac_signing.py:117`, verified byte-for-byte against `raw_path` in
# `dependencies.py::verify_n8n_to_backend_request` -- percent-encoding tricks
# don't bypass it either, same as the existing path segments). Tampering the
# token after signing changes the signed target and therefore invalidates the
# signature (401), which is what makes it "part of the signed bytes" without
# a second mechanism.
_LEASE_TOKEN = re.compile(r"[A-Za-z0-9_-]{16,128}", re.ASCII)
_MEDIA_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", re.ASCII)
# RFC-9110-Feldwert ohne Whitespace: druckbares ASCII, 1..128 Zeichen. Damit
# sind Zeilenumbrueche (Header-/Log-Injection) und alles Nicht-ASCII raus.
_IDEMPOTENCY_KEY = re.compile(r"[\x21-\x7e]{1,128}", re.ASCII)


def _require_canonical_uuid(value: str, label: str) -> str:
    """Nur die kanonische Kleinschreibung mit Bindestrichen wird akzeptiert.

    `UUID()` allein wuerde auch "4DDB2442E58A..." schlucken; zwei
    Schreibweisen derselben UUID waeren aber zwei verschiedene signierte
    Ziele und in Odoo zwei verschiedene Suchbegriffe.
    """
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Malformed {label}.") from exc
    if str(parsed) != value:
        raise HTTPException(status_code=400, detail=f"Malformed {label}.")
    return value


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key or not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        raise HTTPException(status_code=400, detail="Idempotency-Key is required.")
    return idempotency_key


def _declared_media_type(content_type: str | None) -> str:
    """Nur der Medientyp, ohne Parameter, klein geschrieben."""
    return (content_type or "").split(";")[0].strip().lower()


def _validated(call, *, conflict: bool = False) -> ValidatedBinary:
    """Uebersetzt eine Validierungsablehnung in 422.

    Die Meldung aus `binary_validation` wird durchgereicht: sie besteht
    ausschliesslich aus festen Texten und Zeichen aus einer Allowlist,
    enthaelt also keine Angreiferdaten, die in Proxy-Logs zurueckgespiegelt
    werden koennten.
    """
    try:
        return call()
    except BinaryValidationError as exc:
        raise HTTPException(
            status_code=409 if conflict else 422, detail=str(exc)
        ) from exc


def _odoo_text(result: Any, key: str) -> str:
    """Ein fehlendes oder falsch typisiertes Feld in der Odoo-Antwort ist ein
    Konflikt, kein 500 -- wie `_required` fuer die Routen oben."""
    if not isinstance(result, dict) or not isinstance(result.get(key), str):
        raise HTTPException(status_code=409, detail="Unexpected resource result.")
    return result[key]


async def _reserve_signed_nonce(
    odoo, verified: VerifiedInternalRequest, job_id: str, processing_lease_token: str
):
    """Reserviert die Nonce der verifizierten Signatur, gebunden an Job,
    Generation UND (seit Fix-Runde 1) das Lease-Token des Aufrufers.
    Autoritativ ist der Store in Odoo (Task 8, 900s Retention) -- ein
    prozesslokaler Cache waere pro Worker getrennt und damit kein
    Replay-Schutz."""
    try:
        return await odoo.execute_kw(
            "picking.assistant.webhook.nonce",
            "api_reserve_request_nonce",
            [
                "n8n_to_backend",
                verified.signature.key_id,
                verified.signature.nonce,
                False,
                job_id,
                verified.signature.delivery_generation,
                processing_lease_token,
            ],
        )
    except OdooAPIError as exc:
        raise HTTPException(status_code=409, detail="Resource request conflict.") from exc


@router.get(
    "/instances/{odoo_instance}/jobs/{job_id}"
    "/leases/{processing_lease_token}/media/{media_ref}"
)
async def get_job_media(
    odoo_instance: str,
    job_id: str,
    processing_lease_token: str,
    media_ref: str,
    verified: VerifiedInternalRequest = Depends(verify_n8n_to_backend_request),
    runtime: RuntimeServices = Depends(get_runtime),
) -> Response:
    """Liefert ein job-gebundenes Bild als ROHE Bytes.

    Das Bild wird auch auf dem Rueckweg validiert, nicht nur beim Hochladen:
    Odoo ist fuer diese Route eine Datenquelle wie jede andere, und ein
    Anhang, der auf anderem Weg in die Datenbank gekommen ist, darf hier
    nicht ungeprueft an einen Workflow gereicht werden.

    `processing_lease_token` bindet den Zugriff an DIE Lease, die der
    Aufrufer tatsaechlich haelt (#5b, Fix-Runde 1) -- vorher pruefte Odoo nur
    "Generation passt und irgendeine Lease ist aktiv".
    """
    _require_canonical_uuid(job_id, "job id")
    if not _LEASE_TOKEN.fullmatch(processing_lease_token):
        raise HTTPException(status_code=400, detail="Malformed processing lease token.")
    if not _MEDIA_REF.fullmatch(media_ref):
        raise HTTPException(status_code=400, detail="Malformed media reference.")
    odoo = get_callback_odoo_client(runtime, odoo_instance)
    generation = verified.signature.delivery_generation
    await _reserve_signed_nonce(odoo, verified, job_id, processing_lease_token)
    try:
        result = await odoo.execute_kw(
            "picking.assistant.integration.job",
            "api_get_job_media",
            [job_id, media_ref, generation, processing_lease_token],
        )
    except OdooAPIError as exc:
        raise HTTPException(status_code=409, detail="Media access conflict.") from exc
    try:
        body = base64.b64decode(_odoo_text(result, "content_base64"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Unexpected resource result.") from exc
    expected_sha256 = _odoo_text(result, "sha256")
    declared_mime = _odoo_text(result, "mimetype")
    validated = _validated(lambda: validate_image(body, declared_mime=declared_mime))
    if not compare_digest(validated.sha256, expected_sha256):
        raise HTTPException(status_code=409, detail="Media hash mismatch.")
    # Serverseitig erzeugter Dateiname: der Originalname des Uploads wird
    # gespeichert, aber niemals ausgeliefert (er ist Angreiferdaten).
    filename = sanitize_filename(f"{job_id}-{media_ref}.{validated.extension}")
    return Response(
        content=body,
        media_type=validated.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            # Der Typ ist validiert; nosniff verbietet dem Client trotzdem,
            # ihn selbst zu erraten.
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/instances/{odoo_instance}/jobs/{job_id}"
    "/leases/{processing_lease_token}/events/{source_event_id}/artifacts/{artifact_kind}",
    status_code=201,
)
async def store_job_artifact(
    odoo_instance: str,
    job_id: str,
    processing_lease_token: str,
    source_event_id: str,
    artifact_kind: str,
    verified: VerifiedInternalRequest = Depends(verify_n8n_to_backend_request),
    runtime: RuntimeServices = Depends(get_runtime),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    content_type: str | None = Header(default=None, alias="Content-Type"),
) -> JSONResponse:
    """Nimmt ein Artefakt als ROHE Bytes an und legt es job-gebunden ab.

    201 fuer ein neues Artefakt, 200 fuer eine identische Wiedervorlage --
    die Unterscheidung trifft Odoo unter Sperre (gleiche Bytes = Replay,
    andere Bytes unter derselben Art = Konflikt), nicht diese Route.

    `processing_lease_token` bindet den Zugriff an DIE Lease, die der
    Aufrufer tatsaechlich haelt (#5b, Fix-Runde 1) -- vorher pruefte Odoo nur
    "Generation passt und irgendeine Lease ist aktiv".
    """
    if artifact_kind not in ARTIFACT_KINDS:
        raise HTTPException(status_code=400, detail="Unknown artifact kind.")
    _require_canonical_uuid(job_id, "job id")
    if not _LEASE_TOKEN.fullmatch(processing_lease_token):
        raise HTTPException(status_code=400, detail="Malformed processing lease token.")
    _require_canonical_uuid(source_event_id, "source event id")
    _require_idempotency_key(idempotency_key)
    odoo = get_callback_odoo_client(runtime, odoo_instance)
    declared_mime = _declared_media_type(content_type)
    # Phase 1: billig und streng gebunden (Groesse, Magic, deklarierter Typ,
    # ZPL-Kommandoscan). Kein Parser, keine Dekompression.
    _validated(
        lambda: precheck_artifact(
            artifact_kind, verified.raw_body, declared_mime=declared_mime
        )
    )
    generation = verified.signature.delivery_generation
    # Phase 2: das Replay-Gate. Erst hier faellt eine Nonce -- und nur fuer
    # eine Anfrage, die Phase 1 bereits bestanden hat.
    await _reserve_signed_nonce(odoo, verified, job_id, processing_lease_token)
    # Phase 3: der teure Durchlauf (Objektgraph, Expansionsbudget).
    validated = _validated(
        lambda: validate_artifact(
            artifact_kind, verified.raw_body, declared_mime=declared_mime
        )
    )
    filename = sanitize_filename(f"{job_id}-{artifact_kind}.{validated.extension}")
    try:
        result = await odoo.execute_kw(
            "picking.assistant.integration.job",
            "api_store_job_artifact",
            [
                job_id,
                source_event_id,
                artifact_kind,
                generation,
                # Base64 NUR hier, fuer den internen JSON-RPC-Hop.
                base64.b64encode(verified.raw_body).decode("ascii"),
                validated.sha256,
                validated.mime_type,
                filename,
                processing_lease_token,
            ],
        )
    except OdooAPIError as exc:
        raise HTTPException(status_code=409, detail="Artifact storage conflict.") from exc
    artifact_ref = _required(result, "artifact_ref")
    if not isinstance(artifact_ref, str) or not artifact_ref:
        raise HTTPException(status_code=409, detail="Unexpected resource result.")
    replayed = _require_bool(result, "replayed")
    return JSONResponse(
        status_code=200 if replayed else 201,
        content={"artifact_ref": artifact_ref, "replayed": replayed},
    )
