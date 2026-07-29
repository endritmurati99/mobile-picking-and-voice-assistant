from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings, parse_origins, reject_wildcard_origins_with_credentials
from app.routers import auth, cluster, demo, health, instances, integration, llm, n8n_internal, obsidian, pickings, quality, scan, voice
# Task 10: eigene Importzeile, damit parallele Branches die Zeile oben nicht anfassen muessen.
from app.routers import n8n_v2

# --- Task 9: settings-bound lifespan for the outbox dispatcher/watchdog ----
import asyncio  # noqa: E402
import logging  # noqa: E402
import threading  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from app.config import Settings, get_instance_registry  # noqa: E402
from app.dependencies import get_integration_watchdog, get_outbox_dispatcher  # noqa: E402

logger = logging.getLogger(__name__)

# Process-local guard: exactly ONE dispatcher/watchdog pair per process.
# Every dispatcher in this process shares the same hostname:pid worker id,
# so a second concurrently entered lifespan would silently double delivery
# work under one lease identity — refuse it instead.
_dispatcher_process_guard = threading.Lock()


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
                dispatcher = get_outbox_dispatcher(candidate_settings)
                tasks.append(asyncio.create_task(dispatcher.run(stop_event)))
                watchdog = get_integration_watchdog(candidate_settings)

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


app = FastAPI(
    title="Picking Assistant API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=build_lifespan(settings),
)

_pwa_origins = parse_origins(settings.pwa_origins)
# Unconditional, in every runtime profile -- see reject_wildcard_origins_with_credentials.
reject_wildcard_origins_with_credentials(_pwa_origins, allow_credentials=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_pwa_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(pickings.router, prefix="/api", tags=["pickings"])
app.include_router(cluster.router, prefix="/api", tags=["cluster"])
app.include_router(quality.router, prefix="/api", tags=["quality"])
app.include_router(voice.router, prefix="/api", tags=["voice"])
app.include_router(scan.router, prefix="/api", tags=["scan"])
app.include_router(integration.router, prefix="/api", tags=["integration"])
app.include_router(obsidian.router, prefix="/api", tags=["obsidian"])
app.include_router(n8n_internal.router, prefix="/api")
app.include_router(llm.router, prefix="/api")
app.include_router(instances.router, prefix="/api", tags=["instances"])
app.include_router(demo.router, prefix="/api", tags=["demo"])
# Task 10: signierte v2-Routen, wie n8n_internal unter /api gemountet. Der
# Legacy-Router n8n_internal bleibt bewusst daneben bestehen (v1).
app.include_router(n8n_v2.router, prefix="/api", tags=["n8n-v2"])
