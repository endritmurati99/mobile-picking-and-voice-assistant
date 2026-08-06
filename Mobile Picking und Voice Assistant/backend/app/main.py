from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings, parse_origins, reject_wildcard_origins_with_credentials
from app.middleware import RequestBodySizeLimitMiddleware
from app.route_policy import assert_exemptions_are_real_routes, collect_routes
from app.runtime import RuntimeServices
from app.routers import auth, cluster, demo, health, instances, integration, llm, n8n_internal, obsidian, pickings, quality, scan, voice
# Task 10: eigene Importzeile, damit parallele Branches die Zeile oben nicht anfassen muessen.
from app.routers import n8n_v2

# --- Task 9: settings-bound lifespan for the outbox dispatcher/watchdog ----
import asyncio  # noqa: E402
import logging  # noqa: E402
import threading  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from app.config import Settings, get_instance_registry  # noqa: E402
from app.services.voice_intent_classifier import get_classifier  # noqa: E402
from app.dependencies import (  # noqa: E402
    get_integration_watchdog,
    get_outbox_dispatcher,
    require_browser_session,
    require_csrf_on_browser_mutation,
    require_domain_idempotency,
)

logger = logging.getLogger(__name__)

# `uvicorn --log-level info` konfiguriert NUR die "uvicorn.*"-Logger. Der
# Root-Logger blieb ohne Handler, also verschwand jedes logger.info() der App --
# darunter die STT-Diagnosezeile in routers/voice.py, die zeigt WAS Whisper
# gehoert und WELCHEN Intent die Engine daraus gemacht hat. Ohne sie ist im
# Live-Betrieb nicht unterscheidbar, ob das Audio schlecht war oder die
# Zuordnung danebengriff. settings.log_level war definiert, aber nirgends
# angewandt; force=True ueberschreibt einen evtl. vorhandenen Notfall-Handler.
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)

# Process-local guard: exactly ONE dispatcher/watchdog pair per process.
# Every dispatcher in this process shares the same hostname:pid worker id,
# so a second concurrently entered lifespan would silently double delivery
# work under one lease identity — refuse it instead.
_dispatcher_process_guard = threading.Lock()


_INSTANCE_PROBE_RETRY_SECONDS = 2.0


async def verify_instance_names(
    client_factory, instance_names, *, wait_seconds: float = 0.0
) -> None:
    """Jede Odoo-Instanz muss sich selbst so nennen, wie das Backend sie kennt.

    Der Name steht in JEDEM Envelope (`source.odoo_instance`) und entscheidet
    beim Callback, in welche Datenbank zurueckgeschrieben wird. Nennt sich
    Lager 2 faelschlich `local`, landet dessen Bewertung in Lager 1 -- ohne
    Fehlermeldung, weil beide Instanzen dieselben Modelle haben. Ein
    Startfehler ist die einzige ehrliche Antwort darauf; eine Warnung im Log
    wuerde genau so lange uebersehen, bis die Daten vermischt sind.

    `wait_seconds` unterscheidet zwei Faelle, die vorher denselben Abbruch
    ausloesten:

    * **Keine Antwort** heisst beim Kaltstart nur, dass Odoo noch laedt -- das
      dauert rund eine Minute. Darauf wird bis zum Ablauf gewartet.
    * **Falsche Antwort** heisst, dass die Instanz falsch konfiguriert ist.
      Warten macht das nicht besser, also bricht es sofort ab, unabhaengig von
      `wait_seconds`.

    Die Zusage bleibt damit unangetastet: eine falsch benannte Instanz kommt
    nie an den Dispatcher. Gewartet wird auf eine Antwort, nie auf eine
    bessere.

    Voreinstellung 0.0, damit Aufrufer die Wartezeit bewusst waehlen -- Tests
    laufen dadurch ohne Verzoegerung.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, wait_seconds)
    for name in instance_names:
        while True:
            try:
                reported = await client_factory(name).execute_kw(
                    "picking.assistant.api.mixin", "api_instance_name", []
                )
            except Exception as exc:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise RuntimeError(
                        f"Odoo-Instanz {name!r} meldet keinen Instanznamen: {exc}"
                    ) from exc
                logger.warning(
                    "Odoo-Instanz %r antwortet noch nicht (%s); warte weiter, "
                    "noch %.0f s.",
                    name,
                    exc,
                    remaining,
                )
                await asyncio.sleep(min(_INSTANCE_PROBE_RETRY_SECONDS, remaining))
                continue
            break
        if reported != name:
            raise RuntimeError(
                f"Odoo-Instanz {name!r} nennt sich selbst {reported!r}; "
                "picking_assistant.instance_name stimmt nicht mit dem Profil "
                "ueberein."
            )


def build_lifespan(candidate_settings: Settings):
    """Lifespan-Factory: startet Dispatcher + Watchdog nur bei
    `dispatcher_enabled=true` (Tests lassen das Flag aus, ausser sie
    injizieren explizit einen Dispatcher). Task 16 uebergibt hier spaeter die
    candidate-Settings der App-Factory."""

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        stop_event = asyncio.Event()
        tasks: list[asyncio.Task] = []
        guard_held = False
        if candidate_settings.dispatcher_enabled:
            if not _dispatcher_process_guard.acquire(blocking=False):
                raise RuntimeError(
                    "Outbox dispatcher is already running in this process."
                )
            guard_held = True
        # From here on, EVERYTHING (construction, task creation, run, and
        # shutdown) sits under one try/finally: any failure or cancellation
        # on any path stops partially created tasks and releases the guard
        # in the innermost finally — a leaked guard would permanently refuse
        # every later enabled lifespan in this process.
        try:
            if guard_held:
                # Erst pruefen, dann zustellen: ein falsch benannter Envelope
                # ist nicht reparierbar, sobald er einmal draussen ist.
                await verify_instance_names(
                    app.state.runtime.odoo_client,
                    tuple(get_instance_registry(candidate_settings)),
                    wait_seconds=candidate_settings.startup_odoo_wait_seconds,
                )
                dispatcher = get_outbox_dispatcher(app.state.runtime)
                tasks.append(asyncio.create_task(dispatcher.run(stop_event)))
                watchdog = get_integration_watchdog(app.state.runtime)

                async def watchdog_loop():
                    while not stop_event.is_set():
                        for instance in get_instance_registry(candidate_settings):
                            try:
                                await watchdog.run_once(instance)
                            except Exception:
                                logger.exception(
                                    "Watchdog cycle failed for instance %s", instance
                                )
                        try:
                            await asyncio.wait_for(stop_event.wait(), timeout=60)
                        except TimeoutError:
                            pass

                tasks.append(asyncio.create_task(watchdog_loop()))

            # Voice-LLM-Warmup (best-effort, nicht blockierend): laedt das
            # Ollama-Modell in den Speicher, damit die ERSTE unsichere
            # Sprachaeusserung nicht den Kaltstart (gemessen bis ~13s) bezahlt.
            # Eigenes Opt-in-Flag (nicht an den Dispatcher gekoppelt, der hier
            # aus ist); Default False haelt Tests ohne erreichbares Ollama frei.
            if candidate_settings.voice_llm_warmup:
                warmup_task = asyncio.create_task(get_classifier().warmup())
                tasks.append(warmup_task)
            yield
        finally:
            stop_event.set()
            try:
                if tasks:
                    try:
                        await asyncio.gather(*tasks, return_exceptions=True)
                    finally:
                        # Only meaningful when the await above was cancelled:
                        # cancel the (possibly partial) pair and await the
                        # cancellations so no orphan task survives. On the
                        # normal path all tasks are already done and both
                        # calls return immediately.
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                if guard_held:
                    _dispatcher_process_guard.release()

    return app_lifespan


def create_app(candidate_settings: Settings = settings) -> FastAPI:
    """Baut EINE Anwendung aus EINER Settings-Instanz.

    Task 16: die Sicherheitshaltung einer App wird ausschliesslich hier, beim
    Router-Einschluss, festgelegt -- keine Route bringt ihr eigenes Gate mit.
    """
    production = candidate_settings.runtime_profile == "production"
    application = FastAPI(
        title="Picking Assistant API",
        version="0.1.0",
        # Die Schema-Oberflaeche ist in production nicht bloss am Edge
        # geblockt, sondern gar nicht erst gebaut: der Edge-Deny-Liste zu
        # vertrauen hiesse, dass ein direkter Treffer auf den Container (etwa
        # aus dem automation-net) das ganze Routenverzeichnis ausliefert.
        docs_url=None if production else "/api/docs",
        redoc_url=None if production else "/api/redoc",
        openapi_url=None if production else "/api/openapi.json",
        lifespan=build_lifespan(candidate_settings),
    )

    # Task 16, RuntimeServices: ab hier gehoert der langlebige Zustand DIESER
    # App -- Odoo-Clients, SessionService, n8n-/LLM-Client, Keyring. Vorher
    # hingen sie an Modul-Globals in `app.dependencies`, womit `candidate_settings`
    # unterhalb der Routentabelle wirkungslos war. Dependencies loesen sie ueber
    # `request.app.state.runtime` auf.
    application.state.runtime = RuntimeServices(candidate_settings)

    pwa_origins = parse_origins(candidate_settings.pwa_origins)
    # Unconditional, in every runtime profile -- see reject_wildcard_origins_with_credentials.
    reject_wildcard_origins_with_credentials(pwa_origins, allow_credentials=True)

    # Task 15 / register §3.8, second layer: added BEFORE the CORS middleware so
    # that CORS ends up OUTSIDE it (`add_middleware` inserts at the front of the
    # stack, so the last one added is the outermost). A 413 therefore still
    # carries the CORS headers the PWA needs in order to read it, while the
    # limiter still sits above every route and above signature verification.
    application.add_middleware(
        RequestBodySizeLimitMiddleware,
        max_body_bytes=candidate_settings.max_request_body_bytes,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(pwa_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Pre-auth: die einzigen beiden Router, die eine Anfrage ohne Sitzung
    # ueberhaupt erreichen darf. `auth` traegt sein eigenes, feineres Gate
    # (nur /auth/instances und /auth/picker-session sind wirklich offen,
    # /auth/me, /auth/csrf und /auth/logout haengen an get_current_principal).
    application.include_router(health.router, prefix="/api", tags=["health"])
    application.include_router(auth.router, prefix="/api", tags=["auth"])

    # Befund #2b: genau HIER wird das Gate verdrahtet. Es haengt am
    # Router-Einschluss, nicht an einzelnen Handlern -- damit gibt es keine
    # Route auf diesen Routern, die es vergessen kann, und der Voice-/Cluster-
    # Track kann Routen hinzufuegen, ohne die Sicherheitshaltung zu kennen.
    browser_dependencies = [
        Depends(require_browser_session),
        Depends(require_csrf_on_browser_mutation),
        Depends(require_domain_idempotency),
    ]
    gated_routes: set[tuple[str, str]] = set()
    for router, tag in (
        (pickings.router, "pickings"),
        (cluster.router, "cluster"),
        (quality.router, "quality"),
        (voice.router, "voice"),
        (scan.router, "scan"),
    ):
        gated_routes |= collect_routes(router, prefix="/api")
        application.include_router(
            router,
            prefix="/api",
            tags=[tag],
            dependencies=browser_dependencies,
        )
    assert_exemptions_are_real_routes(frozenset(gated_routes))
    application.state.gated_routes = frozenset(gated_routes)

    # Service-zu-Service: eigene Autorisierung (HMAC-Signatur bzw.
    # Callback-Secret), nie Browser-Cookies. Am Edge zusaetzlich geblockt.
    application.include_router(integration.router, prefix="/api", tags=["integration"])
    application.include_router(n8n_internal.router, prefix="/api")
    application.include_router(llm.router, prefix="/api")
    # Task 10: signierte v2-Routen, wie n8n_internal unter /api gemountet. Der
    # Legacy-Router n8n_internal bleibt bewusst daneben bestehen (v1).
    application.include_router(n8n_v2.router, prefix="/api", tags=["n8n-v2"])

    # Entwicklungs-Oberflaechen: in production nicht eingeschlossen. Die
    # Caddy-Deny-Liste bleibt die zweite Schicht, ist aber nicht die einzige.
    if not production:
        application.include_router(obsidian.router, prefix="/api", tags=["obsidian"])
        application.include_router(instances.router, prefix="/api", tags=["instances"])
        application.include_router(demo.router, prefix="/api", tags=["demo"])
    return application


app = create_app(settings)
