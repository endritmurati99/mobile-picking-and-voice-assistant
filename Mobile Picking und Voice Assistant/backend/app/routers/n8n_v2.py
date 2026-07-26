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

Replay-Schutz und Zustandslogik liegen in Odoo (Task 8): `api_accept_event`
und `api_apply_callback` reservieren die Nonce im Store
`picking.assistant.webhook.nonce` in derselben Transaktion wie die
Zustandsaenderung. Jeder Odoo-Konflikt (Replay, Lease-Mismatch, unbekannter
Job, Generation) wird hier auf ein generisches 409 abgebildet -- die
Odoo-Meldung wird nie an den Aufrufer durchgereicht, damit die Antwort nicht
verraet, ob ein Job, ein Event oder ein Receipt existiert.
"""
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import ValidationError

from app.dependencies import (
    VerifiedInternalRequest,
    get_callback_odoo_client,
    verify_n8n_to_backend_request,
)
from app.models.events import (
    CallbackApplyResponse,
    CallbackEnvelopeV2,
    EventAcceptanceRequest,
    EventAcceptanceResponse,
)
from app.services.odoo_client import OdooAPIError

router = APIRouter(prefix="/internal/n8n/v2")


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


@router.post("/events/accept", response_model=EventAcceptanceResponse)
async def accept_event(
    verified: VerifiedInternalRequest = Depends(verify_n8n_to_backend_request),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    body = _verified_body(
        EventAcceptanceRequest, verified, idempotency_key, "event_id"
    )
    odoo = get_callback_odoo_client(body.odoo_instance)
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


@router.post("/callbacks/status", response_model=CallbackApplyResponse)
async def apply_callback(
    verified: VerifiedInternalRequest = Depends(verify_n8n_to_backend_request),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    body = _verified_body(
        CallbackEnvelopeV2, verified, idempotency_key, "callback_id"
    )
    odoo = get_callback_odoo_client(body.odoo_instance)
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
