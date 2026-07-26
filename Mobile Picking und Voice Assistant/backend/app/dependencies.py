"""Dependency Injection fuer FastAPI."""
from collections.abc import Callable
from functools import lru_cache
import inspect
import logging
import secrets
import threading

from fastapi import Depends, Header, HTTPException, Query, Request

from app.services.mobile_workflow import (
    InvalidPickerIdentityError,
    MobileWorkflowService,
    PickerIdentity,
    WriteRequestContext,
)
from app.services.auth_sessions import AuthenticationFailed, CsrfFailed, SessionService
from app.services.cluster_service import ClusterService
from app.services.llm_client import LlmClient
from app.services.n8n_webhook import N8NWebhookClient
from app.services.odoo_client import OdooClient
from app.services.picking_service import PickingService
from app.config import settings, decode_secret_b64, get_instance_registry
from app.models.auth import Principal
# Task 10 additions (kept as separate import lines so concurrent branches that
# touch the block above merge cleanly).
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import Settings
from app.models.webhook_security import HmacKey, HmacKeyring, VerifiedSignature
from app.services.hmac_signing import SignatureError, verify_signature

logger = logging.getLogger(__name__)


# Per-Profil-Client-Cache: je Odoo-Instanz EIN langlebiger Client
# (eigener uid/secret-Cache + httpx-Pool). Reine Funktion (keine Dependency),
# damit der Instanz-Name nicht als Query-Param auf jedem Endpunkt auftaucht.
_clients: dict[str, OdooClient] = {}
# sync DI läuft im FastAPI-Threadpool → double-checked locking verhindert,
# dass zwei gleichzeitige First-Requests denselben Client doppelt anlegen.
_clients_lock = threading.Lock()


def _get_cached_client(name: str) -> OdooClient:
    client = _clients.get(name)
    if client is None:
        with _clients_lock:
            client = _clients.get(name)
            if client is None:
                client = OdooClient(get_instance_registry()[name])
                _clients[name] = client
    return client


def get_odoo_client() -> OdooClient:
    """Lokale/Default-Instanz. Genutzt von n8n-Callbacks (bewusst immer local)."""
    return _get_cached_client("local")


@lru_cache()
def get_n8n_client() -> N8NWebhookClient:
    return N8NWebhookClient()


@lru_cache()
def get_llm_client() -> LlmClient:
    return LlmClient(
        endpoint=settings.llm_endpoint,
        model=settings.llm_model,
        timeout_ms=settings.llm_timeout_ms,
    )


def resolve_instance(
    x_odoo_instance: str | None = Header(default=None, alias="X-Odoo-Instance"),
    instance: str | None = Query(default=None),
) -> str:
    """Waehlt das Odoo-Profil pro Request. Default 'local'; unbekannt -> 400.

    Nur fuer Endpunkte ohne Principal (z. B. anonyme Demo-Umschalter), die
    ihre eigene Autorisierung separat pruefen. Sichere, Principal-gebundene
    Routen nutzen ausschliesslich `get_request_odoo_client`.
    """
    name = (x_odoo_instance or instance or "local").strip().lower()
    if name not in get_instance_registry():
        raise HTTPException(status_code=400, detail=f"Unbekannte Odoo-Instanz: {name}")
    return name


@lru_cache()
def get_session_service() -> SessionService:
    """Ein gecachter SessionService fuer alle Instanzen (analog zu `_get_cached_client`).

    Nutzt niemals ein anderes globales Settings-Objekt als `app.config.settings` und
    baut den Odoo-Client je Instanz ueber `_get_cached_client` (ein langlebiger Client
    pro Odoo-Profil).
    """
    return SessionService(
        client_factory=_get_cached_client,
        instance_names=set(get_instance_registry().keys()),
        throttle_secret=decode_secret_b64(
            "SESSION_THROTTLE_HMAC_SECRET_B64", settings.session_throttle_hmac_secret_b64
        ),
        allowed_origins=set(
            item.strip() for item in settings.pwa_origins.split(",") if item.strip()
        ),
        session_seconds=settings.session_max_age_seconds,
        revalidate_seconds=settings.session_role_revalidate_seconds,
    )


async def get_current_principal(
    request: Request,
    service: SessionService = Depends(get_session_service),
) -> Principal:
    """Browser-Autoritaet kommt ausschliesslich aus dem `pwr_session`-Cookie.

    `X-Picker-User-Id`/`X-Device-Id`/`X-Odoo-Instance` sind hier nie autoritativ.
    Bei einem fehlenden oder ungueltigen Token wird kein Server-Zustand veraendert.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Ungueltige oder abgelaufene Sitzung.")
    try:
        return await service.resolve_principal(token)
    except AuthenticationFailed as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def get_request_odoo_client(
    principal: Principal = Depends(get_current_principal),
) -> OdooClient:
    """Odoo-Client fuer die aktuelle Anfrage, ausschliesslich ueber die
    Session-Principal-Instanz aufgeloest. `X-Odoo-Instance` ist niemals
    autoritativ -- ein Client fuer eine andere Instanz kann durch Header-
    Spoofing nicht erreicht werden.
    """
    return _get_cached_client(principal.odoo_instance)


def get_demo_odoo_client(instance: str = Depends(resolve_instance)) -> OdooClient:
    """Odoo-Client fuer die anonymen Demo-Traceability-Endpunkte.

    Diese Endpunkte pruefen ihre eigene Autorisierung ueber
    `demo_traceability_enabled`/die DB-Allowlist (siehe `app/routers/demo.py`) und
    sind bewusst nicht Principal-gebunden -- genau der Fall, den `resolve_instance`
    in seinem eigenen Docstring als Ausnahme benennt.
    """
    return _get_cached_client(instance)


def _grace_mode_active() -> bool:
    """Grace-Mode ist nur ausserhalb von `production` UND nur mit dem expliziten
    Feature-Flag aktiv. `validate_runtime_security` verbietet das Flag in
    production zusaetzlich fail-closed -- diese Funktion ist die zweite,
    redundante Absicherung direkt an der Nutzungsstelle.
    """
    return settings.runtime_profile != "production" and settings.mobile_header_grace_mode


def _resolve_session_service(request: Request) -> SessionService:
    """Wie `Depends(get_session_service)`, aber nur bei tatsaechlichem Bedarf
    aufgerufen (siehe `_resolve_principal_or_none_for_grace`): ein anonymer
    Grace-Mode-Request ohne Session-Cookie soll keinen echten `SessionService`
    konstruieren (der in Tests ohne konfiguriertes
    `SESSION_THROTTLE_HMAC_SECRET_B64` fehlschlagen wuerde) -- als `Depends`-
    Parameter waere `get_session_service` dagegen fuer jede Anfrage eager
    aufgeloest worden, auch wenn der Request nie ein Cookie mitbringt.
    """
    override = request.app.dependency_overrides.get(get_session_service)
    if override is not None:
        return override()
    return get_session_service()


async def _resolve_principal_or_none_for_grace(request: Request) -> Principal | None:
    """Best-effort Principal-Aufloesung fuer die grace-mode-faehigen Abhaengigkeiten
    (`get_required_picker_identity`, `get_write_request_context`,
    `get_request_odoo_client_or_grace`).

    Ehrt einen expliziten Test-Override auf `get_current_principal` (der bekannte
    Seam aus `test_auth_dependencies.py`), da diese Abhaengigkeiten selbst keinen
    `Depends(get_current_principal)`-Parameter deklarieren koennen -- ein fehlendes
    oder ungueltiges Cookie ist hier (anders als bei `get_current_principal`) kein
    fataler Fehler, sondern der Ausloeser fuer den Legacy-Header-Fallback. Ohne
    Override und ohne Cookie liefert diese Funktion `None` (nie eine Exception),
    damit der Aufrufer auf `resolve_legacy_header_identity()` zurueckfallen kann.
    """
    override = request.app.dependency_overrides.get(get_current_principal)
    if override is not None:
        sig = inspect.signature(override)
        kwargs: dict = {}
        if "request" in sig.parameters:
            kwargs["request"] = request
        if "service" in sig.parameters:
            kwargs["service"] = _resolve_session_service(request)
        result = override(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    sessions = _resolve_session_service(request)
    try:
        return await sessions.resolve_principal(token)
    except AuthenticationFailed:
        return None


async def get_request_odoo_client_or_grace(
    request: Request,
    x_odoo_instance: str | None = Header(default=None, alias="X-Odoo-Instance"),
    instance: str | None = Query(default=None),
) -> OdooClient:
    """Odoo-Client fuer die mobilen/Sprach-/Qualitaets-Workflows: mit Session
    ausschliesslich ueber die Principal-Instanz aufgeloest, genau wie
    `get_request_odoo_client`. Ohne Session faellt dieser Getter -- nur wenn
    Grace-Mode aktiv ist (nie in production) -- auf `X-Odoo-Instance`/`instance`
    (Default `local`) zurueck, statt sofort 401 zu werfen.

    `get_request_odoo_client` selbst bleibt davon unberuehrt und bedient
    weiterhin ausschliesslich strikt Principal-gebundene Routen.

    ACHTUNG, geaendert am 2026-07-26: `/api/products/{id}/image` gehoert NICHT
    mehr dazu -- diese Route bezieht ihren Client bewusst hier, weil `<img src>`
    keine Custom-Header setzen kann und bis zum PWA-Login-UI (Task 16) kein
    Session-Cookie existiert. Im Dev-Profil sind Produktbilder damit ohne
    Session lesbar; in production bleibt Grace-Mode fail-closed und die Route
    antwortet weiter 401. Beide Zusagen sind in `test_instance_routing.py`
    festgenagelt. Die saubere Loesung waere eine kurzlebig signierte Bild-URL,
    dann kann die Ausnahme wieder entfallen.

    Ehrt zusaetzlich einen expliziten Test-Override auf `get_request_odoo_client`
    (der in bestehenden Routen-Tests uebliche Seam, um einen Fake-Client statt
    eines echten HTTP-Clients einzuschleusen) -- so bleiben Tests, die diesen
    Namen ueberschreiben, unabhaengig davon funktionsfaehig, ob eine Route ihren
    Odoo-Client ueber `get_request_odoo_client` oder `get_request_odoo_client_or_grace`
    bezieht.
    """
    override = request.app.dependency_overrides.get(get_request_odoo_client)
    if override is not None:
        sig = inspect.signature(override)
        kwargs: dict = {}
        if "request" in sig.parameters:
            kwargs["request"] = request
        result = override(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    principal = await _resolve_principal_or_none_for_grace(request)
    if principal is not None:
        return _get_cached_client(principal.odoo_instance)
    if not _grace_mode_active():
        raise HTTPException(status_code=401, detail="Ungueltige oder abgelaufene Sitzung.")
    name = (x_odoo_instance or instance or "local").strip().lower()
    if name not in get_instance_registry():
        raise HTTPException(status_code=400, detail=f"Unbekannte Odoo-Instanz: {name}")
    return _get_cached_client(name)


def get_picking_service(
    odoo: OdooClient = Depends(get_request_odoo_client_or_grace),
    n8n: N8NWebhookClient = Depends(get_n8n_client),
) -> PickingService:
    return PickingService(odoo, n8n)


def get_cluster_service(
    odoo: OdooClient = Depends(get_request_odoo_client_or_grace),
    n8n: N8NWebhookClient = Depends(get_n8n_client),
) -> ClusterService:
    return ClusterService(odoo, n8n)


def get_mobile_workflow_service(
    odoo: OdooClient = Depends(get_request_odoo_client_or_grace),
) -> MobileWorkflowService:
    return MobileWorkflowService(odoo)


def resolve_legacy_header_identity(
    picker_user_id: str | None = Header(default=None, alias="X-Picker-User-Id"),
    device_id: str | None = Header(default=None, alias="X-Device-Id"),
    x_odoo_instance: str | None = Header(default=None, alias="X-Odoo-Instance"),
) -> PickerIdentity | None:
    """Legacy-Header-Identitaet -- NUR fuer Entwicklungs-Grace-Mode, NIE als
    Dependency einer sicheren Route verwendet.

    Laeuft ausschliesslich, wenn `runtime_profile != "production"` UND
    `mobile_header_grace_mode` aktiv ist (in production ist Grace-Mode durch
    `validate_runtime_security` bereits fail-closed verboten). Loggt hoechstens
    eine Warnung pro Aufruf, niemals die Header-Werte selbst.
    """
    if not _grace_mode_active():
        return None
    if picker_user_id is None and device_id is None and x_odoo_instance is None:
        return None
    logger.warning(
        "Legacy X-Picker-User-Id/X-Device-Id/X-Odoo-Instance headers accepted under "
        "dev grace mode; these headers carry no authority in secure/production mode."
    )
    user_id: int | None = None
    if picker_user_id is not None:
        try:
            user_id = int(picker_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="X-Picker-User-Id muss numerisch sein.") from exc
    return PickerIdentity(user_id=user_id, device_id=device_id, odoo_instance=x_odoo_instance)


async def get_required_picker_identity(
    request: Request,
    workflow: MobileWorkflowService = Depends(get_mobile_workflow_service),
    legacy_identity: PickerIdentity | None = Depends(resolve_legacy_header_identity),
) -> PickerIdentity:
    """Picker-Identitaet direkt aus dem Principal -- keine Odoo-Rueckfrage noetig,
    da die Session bereits gegen Odoo validiert wurde (siehe SessionService).

    Nur wenn keine Session vorhanden ist UND Grace-Mode aktiv ist (nie in
    production, siehe `_grace_mode_active`), faellt diese Abhaengigkeit auf die
    Legacy-Header via `resolve_legacy_header_identity()` zurueck und validiert
    sie -- wie vor Task 7 -- gegen Odoo (`workflow.resolve_identity`).
    """
    principal = await _resolve_principal_or_none_for_grace(request)
    if principal is not None:
        return PickerIdentity(
            user_id=principal.picker_user_id,
            device_id=principal.device_id,
            picker_name=principal.picker_name,
            odoo_instance=principal.odoo_instance,
            roles=principal.roles,
        )
    if not _grace_mode_active():
        raise HTTPException(status_code=401, detail="Ungueltige oder abgelaufene Sitzung.")
    if legacy_identity is None:
        raise HTTPException(status_code=400, detail="X-Picker-User-Id ist erforderlich.")
    try:
        return await workflow.resolve_identity(legacy_identity)
    except InvalidPickerIdentityError as exc:
        raise HTTPException(status_code=403, detail="Unbekannter oder inaktiver Picker.") from exc


async def require_browser_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    principal: Principal = Depends(get_current_principal),
    sessions: SessionService = Depends(get_session_service),
) -> None:
    try:
        await sessions.validate_csrf(
            principal,
            x_csrf_token,
            request.headers.get("Origin"),
        )
    except CsrfFailed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


async def get_write_request_context(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    legacy_identity: PickerIdentity | None = Depends(resolve_legacy_header_identity),
) -> WriteRequestContext:
    """Schreibkontext fuer Browser-Mutationen: mit Session kommt die Identitaet
    ausschliesslich aus dem Principal, jede Mutation erfordert dann ein gueltiges
    CSRF-Token und einen erlaubten Origin (siehe `require_browser_csrf`).

    Ohne Session faellt dieser Kontext -- nur wenn Grace-Mode aktiv ist (nie in
    production) -- auf die Legacy-Header via `resolve_legacy_header_identity()`
    zurueck; Service-zu-Service-Aufrufe erfordern in diesem Fall keine CSRF/
    Origin-Pruefung (die gab es fuer Legacy-Header-Clients nie).
    """
    principal = await _resolve_principal_or_none_for_grace(request)
    if principal is not None:
        sessions = _resolve_session_service(request)
        try:
            await sessions.validate_csrf(
                principal,
                x_csrf_token,
                request.headers.get("Origin"),
            )
        except CsrfFailed as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return WriteRequestContext(
            idempotency_key=idempotency_key,
            identity=PickerIdentity(
                user_id=principal.picker_user_id,
                device_id=principal.device_id,
                picker_name=principal.picker_name,
                odoo_instance=principal.odoo_instance,
                roles=principal.roles,
            ),
            principal_scope=f"user:{principal.picker_user_id}",
        )
    if not _grace_mode_active():
        raise HTTPException(status_code=401, detail="Ungueltige oder abgelaufene Sitzung.")
    return WriteRequestContext(
        idempotency_key=idempotency_key,
        identity=legacy_identity or PickerIdentity(),
        principal_scope=None,
    )


def get_legacy_n8n_write_context(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> WriteRequestContext:
    """Schreibkontext ausschliesslich fuer die fuenf legacy n8n-Callback-Routen.

    Diese Routen laufen service-zu-service hinter `require_n8n_callback_secret`
    und erhalten nie Browser-Cookies, Origin oder CSRF -- die Identitaet ist
    bewusst leer, der principal_scope markiert sie als Service-Aufrufe.
    """
    return WriteRequestContext(
        idempotency_key=idempotency_key,
        identity=PickerIdentity(),
        principal_scope="service:n8n-v1",
    )


def require_roles(*required: str) -> Callable:
    """Rollen-Gate fuer Principal-Endpunkte. Baut ausschliesslich auf
    `get_current_principal` auf, damit Tests und andere Aufrufer die Identitaet
    ueber den einen bekannten Seam (`get_current_principal`) ueberschreiben
    koennen -- es gibt keinen zweiten, session-cookie-basierten Pfad, der diese
    Ueberschreibung umgehen wuerde.
    """
    required_roles = frozenset(required)

    async def dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if not required_roles.issubset(principal.roles):
            raise HTTPException(status_code=403, detail="Rolle nicht erlaubt.")
        return principal

    return dependency


def require_n8n_callback_secret(
    provided_secret: str | None = Header(default=None, alias="X-N8N-Callback-Secret"),
) -> None:
    expected_secret = settings.n8n_callback_secret
    if not expected_secret:
        raise HTTPException(
            status_code=503,
            detail="N8N callback secret ist nicht konfiguriert.",
        )
    if not provided_secret or not secrets.compare_digest(provided_secret, expected_secret):
        raise HTTPException(status_code=403, detail="Ungueltiges n8n callback secret.")


# ---------------------------------------------------------------------------
# Task 10: signierte n8n -> Backend Transportschicht (v2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifiedInternalRequest:
    """Ergebnis einer BESTANDENEN Signaturpruefung.

    Es gibt keinen Konstruktionsweg zu diesem Objekt, der die Pruefung
    ueberspringt: `verify_n8n_to_backend_request` erzeugt es ausschliesslich
    nach `verify_signature`. Routen sehen den Rohbody erst hier -- damit ist
    "erst verifizieren, dann parsen" strukturell erzwungen und nicht bloss
    Konvention.
    """

    signature: VerifiedSignature
    raw_body: bytes


def get_signature_now() -> datetime:
    """Uhr fuer die Signatur-Skew-Pruefung als eigene Dependency, damit Tests
    das Zeitfenster deterministisch setzen koennen (statt von der Wanduhr
    abzuhaengen)."""
    return datetime.now(timezone.utc)


def build_n8n_to_backend_keyring(candidate: Settings) -> HmacKeyring:
    """Keyring fuer die n8n -> Backend Richtung aus der uebergebenen
    `candidate`-Settings-Instanz (niemals ein anderes globales Settings-Objekt).

    `decode_secret_b64` erzwingt >= 32 entschluesselte Bytes und faellt bei
    fehlender/ungueltiger Konfiguration mit ValueError aus -- fail closed, es
    gibt keinen Pfad zu einem leeren oder Default-Secret.
    """
    active = HmacKey(
        candidate.pwr_n8n_to_backend_active_key_id,
        decode_secret_b64(
            "PWR_N8N_TO_BACKEND_ACTIVE_SECRET_B64",
            candidate.pwr_n8n_to_backend_active_secret_b64,
        ),
    )
    previous = None
    if candidate.pwr_n8n_to_backend_previous_key_id:
        previous = HmacKey(
            candidate.pwr_n8n_to_backend_previous_key_id,
            decode_secret_b64(
                "PWR_N8N_TO_BACKEND_PREVIOUS_SECRET_B64",
                candidate.pwr_n8n_to_backend_previous_secret_b64,
            ),
        )
    return HmacKeyring(active=active, previous=previous)


def get_n8n_to_backend_keyring() -> HmacKeyring:
    # Transitional dependency until Task 16 binds the keyring to
    # app.state.runtime. Bis dahin wird der Keyring pro Request aus
    # `app.config.settings` gebaut -- absichtlich NICHT gecacht, damit eine
    # Key-Rotation keinen Prozess-Neustart braucht.
    try:
        return build_n8n_to_backend_keyring(settings)
    except ValueError as exc:
        # Fehlendes/ungueltiges Secret => 503, exakt wie
        # `require_n8n_callback_secret` fuer den Legacy-Pfad. Es gibt keinen
        # Fallback-Key: ohne Konfiguration ist die Route geschlossen. Der Grund
        # bleibt im Log, nicht in der Antwort.
        logger.error("n8n-to-backend HMAC keyring is not configured: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="n8n-to-backend signing keys sind nicht konfiguriert.",
        ) from exc


async def verify_n8n_to_backend_request(
    request: Request,
    keyring: HmacKeyring = Depends(get_n8n_to_backend_keyring),
    now: datetime = Depends(get_signature_now),
) -> VerifiedInternalRequest:
    """Prueft die HMAC-Signatur des ROHEN Requests, bevor irgendetwas anderes
    passiert (Schema, Instanz-Routing, Odoo).

    Der signierte Pfad wird gegen `raw_path` verglichen, nicht gegen den von
    Starlette dekodierten `url.path`: sonst koennten prozentkodierte Varianten
    desselben Ziels dieselbe Signatur bedienen. Ein Query-String ist auf diesen
    Routen komplett verboten (`verify_signature` -> 400), damit kein
    ungesignter Parameter Verhalten beeinflussen kann.

    Replay-Schutz liegt bewusst NICHT hier: der autoritative Nonce-Store ist
    `picking.assistant.webhook.nonce` in Odoo (Task 8, 900s Retention > der
    geforderten 600s). Er wird innerhalb von `api_accept_event` /
    `api_apply_callback` reserviert, also in derselben Transaktion wie die
    Zustandsaenderung -- ein prozesslokaler Cache hier waere pro Worker
    getrennt und damit kein Replay-Schutz. Das Skew-Fenster
    (`pwr_hmac_max_skew_seconds`) begrenzt zusaetzlich, wie alt eine
    wiedervorgelegte Signatur sein darf.
    """
    raw_body = await request.body()
    raw_path = request.scope.get("raw_path") or request.url.path.encode("utf-8")
    try:
        try:
            actual_target = raw_path.decode("ascii")
        except UnicodeDecodeError as exc:
            # Ein Pfad mit Nicht-ASCII-Bytes ist nie ein gueltiges signiertes
            # Ziel -- fail closed statt Signaturpruefung mit Ersatzzeichen.
            raise SignatureError(400, "malformed_target") from exc
        signature = verify_signature(
            actual_method=request.method,
            actual_target=actual_target,
            raw_query=request.scope.get("query_string", b""),
            raw_body=raw_body,
            headers=dict(request.headers),
            keyring=keyring,
            now=now,
            max_skew_seconds=settings.pwr_hmac_max_skew_seconds,
        )
    except SignatureError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"reason_code": exc.reason_code},
        ) from exc
    return VerifiedInternalRequest(signature=signature, raw_body=raw_body)


def get_callback_odoo_client(odoo_instance: str) -> OdooClient:
    """Odoo-Client fuer die signierten v2-Routen, ausschliesslich aus dem
    Instanznamen im SIGNIERTEN Body aufgeloest.

    Bewusst KEINE FastAPI-Dependency: es gibt damit keinen Weg, den Namen aus
    einem Header (`X-Odoo-Instance`), einem Query-Parameter oder einem
    `local`-Default zu beziehen. Der Name wird als Allowlist gegen das
    serverseitige Instanzregister geprueft (exakter Treffer, keine
    Normalisierung -- der Body muss den kanonischen Namen nennen) und eine
    unbekannte Instanz endet in 403 mit einer Meldung, die nicht verraet,
    welche Instanzen existieren.
    """
    if odoo_instance not in get_instance_registry():
        raise HTTPException(status_code=403, detail="Unbekannte Callback-Instanz.")
    return _get_cached_client(odoo_instance)


# ---------------------------------------------------------------------------
# Task 9: signed v2 event transport — outbox dispatcher and integration
# watchdog. Deliberately appended (imports included) so concurrent edits to
# this file stay trivially mergeable.
# ---------------------------------------------------------------------------
from pathlib import Path  # noqa: E402

from app.config import Settings  # noqa: E402
from app.services.outbox_dispatcher import (  # noqa: E402
    IntegrationWatchdog,
    OutboxDispatcher,
    build_integration_watchdog,
    build_outbox_dispatcher,
)
from app.services.workflow_targets import load_event_targets  # noqa: E402


def get_outbox_dispatcher(candidate: Settings = settings) -> OutboxDispatcher:
    """Dispatcher fuer die uebergebene Settings-Instanz. Die Event-zu-Pfad-
    Zuordnung kommt ausschliesslich aus dem einen Registry-File
    (`load_event_targets`), nie aus einer Python-Konstante."""
    targets = load_event_targets(Path(candidate.workflow_registry_path))
    return build_outbox_dispatcher(candidate, _get_cached_client, targets)


def get_integration_watchdog(candidate: Settings = settings) -> IntegrationWatchdog:
    return build_integration_watchdog(candidate, _get_cached_client)
