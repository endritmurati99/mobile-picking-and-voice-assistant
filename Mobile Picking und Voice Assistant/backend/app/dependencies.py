"""Dependency Injection fuer FastAPI."""
from collections.abc import Callable
from functools import lru_cache
import logging
import secrets
import threading

from fastapi import Depends, Header, HTTPException, Query, Request

from app.services.mobile_workflow import (
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


def get_picking_service(
    odoo: OdooClient = Depends(get_request_odoo_client),
    n8n: N8NWebhookClient = Depends(get_n8n_client),
) -> PickingService:
    return PickingService(odoo, n8n)


def get_cluster_service(
    odoo: OdooClient = Depends(get_request_odoo_client),
    n8n: N8NWebhookClient = Depends(get_n8n_client),
) -> ClusterService:
    return ClusterService(odoo, n8n)


def get_mobile_workflow_service(
    odoo: OdooClient = Depends(get_request_odoo_client),
) -> MobileWorkflowService:
    return MobileWorkflowService(odoo)


def get_required_picker_identity(
    principal: Principal = Depends(get_current_principal),
) -> PickerIdentity:
    """Picker-Identitaet direkt aus dem Principal -- keine Odoo-Rueckfrage noetig,
    da die Session bereits gegen Odoo validiert wurde (siehe SessionService).
    """
    return PickerIdentity(
        user_id=principal.picker_user_id,
        device_id=principal.device_id,
        picker_name=principal.picker_name,
        odoo_instance=principal.odoo_instance,
        roles=principal.roles,
    )


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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(get_current_principal),
    _csrf: None = Depends(require_browser_csrf),
) -> WriteRequestContext:
    """Schreibkontext fuer Browser-Mutationen: Identitaet kommt ausschliesslich
    aus dem Principal, jede Mutation erfordert ein gueltiges CSRF-Token und
    einen erlaubten Origin (siehe `require_browser_csrf`).
    """
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


def resolve_legacy_header_identity(
    picker_user_id: str | None = Header(default=None, alias="X-Picker-User-Id"),
    device_id: str | None = Header(default=None, alias="X-Device-Id"),
) -> PickerIdentity | None:
    """Legacy-Header-Identitaet -- NUR fuer Entwicklungs-Grace-Mode, NIE als
    Dependency einer sicheren Route verwendet.

    Laeuft ausschliesslich, wenn `runtime_profile != "production"` UND
    `mobile_header_grace_mode` aktiv ist (in production ist Grace-Mode durch
    `validate_runtime_security` bereits fail-closed verboten). Loggt hoechstens
    eine Warnung pro Aufruf, niemals die Header-Werte selbst.
    """
    if settings.runtime_profile == "production" or not settings.mobile_header_grace_mode:
        return None
    if picker_user_id is None and device_id is None:
        return None
    logger.warning(
        "Legacy X-Picker-User-Id/X-Device-Id headers accepted under dev grace mode; "
        "these headers carry no authority in secure/production mode."
    )
    user_id: int | None = None
    if picker_user_id is not None:
        try:
            user_id = int(picker_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="X-Picker-User-Id muss numerisch sein.") from exc
    return PickerIdentity(user_id=user_id, device_id=device_id)


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
