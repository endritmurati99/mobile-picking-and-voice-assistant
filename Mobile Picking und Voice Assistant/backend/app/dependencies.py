"""Dependency Injection fuer FastAPI."""
from collections.abc import Callable
import inspect
import logging
import re
import secrets

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
from app.services.vision_client import VisionClient
from app.services.n8n_webhook import N8NWebhookClient
from app.services.odoo_client import OdooClient
from app.services.picking_service import PickingService
# `settings` wird hier bewusst NICHT mehr importiert: jede Konfiguration kommt
# aus `get_runtime(request).settings`. Ein Import dieses Namens waere die
# Einladung, versehentlich wieder am App-Kontext vorbei zu lesen -- und genau
# das war der Defekt, den Task 16 schliesst.
from app.config import (
    get_instance_registry,
    read_secret,
)
from app.models.auth import Principal
from app.runtime import RuntimeServices
from app.route_policy import MUTATING_METHODS, requires_idempotency_key
# Task 10 additions (kept as separate import lines so concurrent branches that
# touch the block above merge cleanly).
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import Settings
from app.models.webhook_security import HmacKey, HmacKeyring, VerifiedSignature
from app.services.hmac_signing import SignatureError, verify_signature

logger = logging.getLogger(__name__)


# Task 16: der langlebige Zustand gehoert der App, nicht diesem Modul. Er wird
# in `create_app` als `RuntimeServices` an `app.state.runtime` gebunden und hier
# ausschliesslich ueber den Request aufgeloest. Vorher lagen Client-Cache,
# SessionService und LLM-Client als Modul-Globals bzw. `lru_cache` hier -- zwei
# Apps in einem Prozess teilten sie, und das `candidate`-Argument von
# `create_app` war unterhalb der Routentabelle wirkungslos.
def get_runtime(request: Request) -> RuntimeServices:
    return request.app.state.runtime


def get_odoo_client(request: Request) -> OdooClient:
    """Lokale/Default-Instanz. Genutzt von n8n-Callbacks (bewusst immer local)."""
    return get_runtime(request).odoo_client("local")


def get_n8n_client(request: Request) -> N8NWebhookClient:
    return get_runtime(request).n8n_client()


def get_llm_client(request: Request) -> LlmClient:
    return get_runtime(request).llm_client()


def get_vision_client(request: Request) -> VisionClient | None:
    """`None` heisst: Bildpruefung abgeschaltet, siehe `RuntimeServices`."""
    return get_runtime(request).vision_client()


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


def get_session_service(request: Request) -> SessionService:
    """Fail-closed Wrapper um `RuntimeServices.session_service`.

    Ein fehlendes oder unlesbares `SESSION_THROTTLE_HMAC_SECRET_B64` ist eine
    Fehlkonfiguration, kein Programmfehler: vorher schlug `decode_secret_b64`
    hier mitten in der Dependency-Aufloesung durch und jede geschuetzte Route
    antwortete 500 (Stacktrace mit Secret-Namen im Log, Antwort ohne
    verwertbare Information). Jetzt gilt dieselbe Regel wie fuer jedes andere
    fehlende Secret in dieser Datei: 503, Route geschlossen, Grund nur im Log.
    """
    try:
        return get_runtime(request).session_service()
    except (ValueError, OSError) as exc:
        logger.error("Session service is not configured: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Session service ist nicht konfiguriert.",
        ) from exc


async def get_current_principal(
    request: Request,
    service: SessionService = Depends(get_session_service),
) -> Principal:
    """Browser-Autoritaet kommt ausschliesslich aus dem `pwr_session`-Cookie.

    `X-Picker-User-Id`/`X-Device-Id`/`X-Odoo-Instance` sind hier nie autoritativ.
    Bei einem fehlenden oder ungueltigen Token wird kein Server-Zustand veraendert.
    """
    token = request.cookies.get(get_runtime(request).settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Ungueltige oder abgelaufene Sitzung.")
    try:
        return await service.resolve_principal(token)
    except AuthenticationFailed as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def get_request_odoo_client(
    request: Request,
    principal: Principal = Depends(get_current_principal),
) -> OdooClient:
    """Odoo-Client fuer die aktuelle Anfrage, ausschliesslich ueber die
    Session-Principal-Instanz aufgeloest. `X-Odoo-Instance` ist niemals
    autoritativ -- ein Client fuer eine andere Instanz kann durch Header-
    Spoofing nicht erreicht werden.
    """
    return get_runtime(request).odoo_client(principal.odoo_instance)


def get_demo_odoo_client(
    request: Request,
    instance: str = Depends(resolve_instance),
) -> OdooClient:
    """Odoo-Client fuer die anonymen Demo-Traceability-Endpunkte.

    Diese Endpunkte pruefen ihre eigene Autorisierung ueber
    `demo_traceability_enabled`/die DB-Allowlist (siehe `app/routers/demo.py`) und
    sind bewusst nicht Principal-gebunden -- genau der Fall, den `resolve_instance`
    in seinem eigenen Docstring als Ausnahme benennt.
    """
    return get_runtime(request).odoo_client(instance)


def _grace_mode_active(runtime: RuntimeServices) -> bool:
    """Grace-Mode ist nur im Profil `development` UND nur mit dem expliziten
    Feature-Flag aktiv. `validate_runtime_security` verbietet das Flag in
    production zusaetzlich fail-closed -- diese Funktion ist die zweite,
    redundante Absicherung direkt an der Nutzungsstelle. `test` und jedes
    kuenftige Profil zaehlen bewusst NICHT als development.
    """
    return (
        runtime.settings.runtime_profile == "development"
        and runtime.settings.mobile_header_grace_mode
    )


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
    return get_session_service(request)


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

    token = request.cookies.get(get_runtime(request).settings.session_cookie_name)
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
        return get_runtime(request).odoo_client(principal.odoo_instance)
    if not _grace_mode_active(get_runtime(request)):
        raise HTTPException(status_code=401, detail="Ungueltige oder abgelaufene Sitzung.")
    name = (x_odoo_instance or instance or "local").strip().lower()
    if name not in get_instance_registry():
        raise HTTPException(status_code=400, detail=f"Unbekannte Odoo-Instanz: {name}")
    return get_runtime(request).odoo_client(name)


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


def get_legacy_n8n_workflow_service(
    odoo: OdooClient = Depends(get_odoo_client),
) -> MobileWorkflowService:
    """Workflow-Service fuer die fuenf Legacy-n8n-Callbacks (Service-zu-Service).

    Diese Routen sind ueber `require_n8n_callback_secret` autorisiert und sehen
    NIE einen Browser-Cookie. Sie duerfen deshalb nicht ueber
    `get_request_odoo_client_or_grace` laufen: der wirft in production 401,
    bevor der Handler ueberhaupt erreicht wird, und liesse im Development
    `X-Odoo-Instance` die Idempotenz-Buchfuehrung auf eine andere Instanz
    umlenken, waehrend der Business-Write ueber `get_odoo_client` fest auf
    `local` schreibt. Beide Haelften benutzen jetzt denselben Client.
    """
    return MobileWorkflowService(odoo)


def resolve_legacy_header_identity(
    request: Request,
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
    if not _grace_mode_active(get_runtime(request)):
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
    if not _grace_mode_active(get_runtime(request)):
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


# ---------------------------------------------------------------------------
# Task 16 / Befund #2b: die App-weiten Gates. Sie werden AUSSCHLIESSLICH beim
# Router-Einschluss in `main.create_app` verdrahtet -- kein Router-Body kennt
# sie, und kein Router-Body kann sie umgehen.
# ---------------------------------------------------------------------------

_IDEMPOTENCY_KEY = re.compile(r"[\x21-\x7e]{1,128}")


def validate_idempotency_key(value: str | None) -> str:
    """1 bis 128 sichtbare ASCII-Zeichen, sonst 400.

    `fullmatch` und der explizite Bereich \\x21-\\x7e schliessen Leerzeichen,
    Tab, CR/LF und jedes Nicht-ASCII aus. Ein Schluessel mit Zeilenumbruch
    landet sonst in Logs und in Odoo-Suchdomains, und ein leerer Schluessel
    wuerde als "kein Schluessel" durchrutschen.
    """
    if value is None or not _IDEMPOTENCY_KEY.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key must contain 1 to 128 visible ASCII characters.",
        )
    return value


def require_domain_idempotency(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    """Erzwingt einen syntaktisch gueltigen Idempotency-Key auf jeder Mutation
    eines Browser-Routers, ausser auf den in `route_policy` benannten Ausnahmen.

    Die Klassifikation haengt am ROUTEN-TEMPLATE (`scope["route"].path`), nicht
    am konkreten Pfad: eine Regex ueber `request.url.path` haette sonst ueber
    prozentkodierte oder mit Slash-Varianten geschriebene Pfade umgangen werden
    koennen.
    """
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if route_path is None:
        # Kein aufgeloestes Routen-Template => keine Klassifikation moeglich.
        # Fail closed: jede Mutation braucht dann einen Schluessel.
        if request.method in MUTATING_METHODS:
            validate_idempotency_key(idempotency_key)
        return
    if requires_idempotency_key(request.method, route_path):
        validate_idempotency_key(idempotency_key)


async def require_browser_session(request: Request) -> None:
    """Auth-Gate fuer die Browser-Router, gesetzt beim App-Einschluss.

    Bewusst NICHT `Depends(get_current_principal)`: dieses Gate haengt an
    JEDER Route dieser Router, auch an denen, die im Grace-Mode weiterhin ueber
    Legacy-Header identifiziert werden duerfen. Es benutzt darum denselben
    Resolver wie `get_write_request_context` -- eine zweite, abweichende
    Auth-Semantik im selben Prozess waere genau die Art Inkonsistenz, aus der
    Umgehungen entstehen.

    In production ist Grace-Mode durch `validate_runtime_security` verboten,
    das Gate also strikt session-gebunden.
    """
    principal = await _resolve_principal_or_none_for_grace(request)
    if principal is not None:
        return
    if not _grace_mode_active(get_runtime(request)):
        raise HTTPException(
            status_code=401, detail="Ungueltige oder abgelaufene Sitzung."
        )
    # Grace-Mode: die Route validiert die Legacy-Identitaet selbst
    # (`get_required_picker_identity`) -- unveraendert gegenueber Task 7.


async def require_csrf_on_browser_mutation(
    request: Request,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    """CSRF-/Origin-Gate fuer jede zustandsaendernde Methode.

    Lesende Anfragen bleiben ungefiltert -- ein GET, das ein CSRF-Token
    verlangt, ist kein Schutz, sondern ein Ausfall.

    Der Origin-Vergleich selbst liegt in `SessionService._require_origin` und
    ist exakte Mengenzugehoerigkeit; `test_route_security.py` nagelt Praefix-,
    Suffix-, Schema-, Port- und `null`-Varianten fest.

    Ohne Session gilt exakt dieselbe Regel wie in `get_write_request_context`:
    in production 401 (Grace-Mode ist dort verboten), im Grace-Mode kein
    CSRF -- Legacy-Header-Clients hatten nie eines.
    """
    if request.method not in MUTATING_METHODS:
        return
    principal = await _resolve_principal_or_none_for_grace(request)
    if principal is None:
        if not _grace_mode_active(get_runtime(request)):
            raise HTTPException(
                status_code=401, detail="Ungueltige oder abgelaufene Sitzung."
            )
        return
    sessions = _resolve_session_service(request)
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
    if not _grace_mode_active(get_runtime(request)):
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
    request: Request,
    provided_secret: str | None = Header(default=None, alias="X-N8N-Callback-Secret"),
) -> None:
    try:
        candidate = get_runtime(request).settings
        expected_secret = read_secret(
            candidate.n8n_callback_secret, candidate.n8n_callback_secret_file
        )
    except (ValueError, OSError) as exc:
        # An unreadable/misconfigured secret file is a 503 exactly like a
        # missing secret -- never a 500 that leaks the path, and never an
        # open route.
        logger.error("N8N callback secret is not resolvable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="N8N callback secret ist nicht konfiguriert.",
        ) from exc
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


def get_n8n_to_backend_keyring(request: Request) -> HmacKeyring:
    # Der Keyring kommt aus den Settings DIESER App und ist absichtlich NICHT
    # gecacht, damit eine Key-Rotation keinen Prozess-Neustart braucht.
    try:
        return get_runtime(request).n8n_to_backend_keyring()
    except (ValueError, OSError) as exc:
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
            max_skew_seconds=get_runtime(request).settings.pwr_hmac_max_skew_seconds,
        )
    except SignatureError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"reason_code": exc.reason_code},
        ) from exc
    return VerifiedInternalRequest(signature=signature, raw_body=raw_body)


def get_callback_odoo_client(runtime: RuntimeServices, odoo_instance: str) -> OdooClient:
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
    if odoo_instance not in runtime.instances:
        raise HTTPException(status_code=403, detail="Unbekannte Callback-Instanz.")
    return runtime.odoo_client(odoo_instance)


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


def get_outbox_dispatcher(runtime: RuntimeServices) -> OutboxDispatcher:
    """Dispatcher fuer die Settings DIESER App. Die Event-zu-Pfad-Zuordnung
    kommt ausschliesslich aus dem einen Registry-File (`load_event_targets`),
    nie aus einer Python-Konstante.

    Nimmt bewusst das Runtime und nicht die Settings: der Dispatcher laeuft als
    Hintergrund-Task ueber die ganze Lebensdauer der App und muss dieselben
    Odoo-Clients benutzen wie die Requests -- ein eigener Client-Cache hier
    hiesse ein zweiter uid-Cache und ein zweiter httpx-Pool pro Instanz.
    """
    targets = load_event_targets(Path(runtime.settings.workflow_registry_path))
    return build_outbox_dispatcher(runtime.settings, runtime.odoo_client, targets)


def get_integration_watchdog(runtime: RuntimeServices) -> IntegrationWatchdog:
    return build_integration_watchdog(runtime.settings, runtime.odoo_client)
