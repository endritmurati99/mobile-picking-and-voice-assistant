from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, cluster, demo, health, instances, integration, llm, n8n_internal, obsidian, pickings, quality, scan, voice

# --- Task 9: settings-bound lifespan for the outbox dispatcher/watchdog ----
import asyncio  # noqa: E402
import logging  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from app.config import Settings, get_instance_registry  # noqa: E402
from app.dependencies import get_integration_watchdog, get_outbox_dispatcher  # noqa: E402

logger = logging.getLogger(__name__)


def build_lifespan(candidate_settings: Settings):
    """Lifespan-Factory: startet Dispatcher + Watchdog nur bei
    `dispatcher_enabled=true` (Tests lassen das Flag aus, ausser sie
    injizieren explizit einen Dispatcher). Task 16 uebergibt hier spaeter die
    candidate-Settings der App-Factory."""

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        stop_event = asyncio.Event()
        tasks: list[asyncio.Task] = []
        if candidate_settings.dispatcher_enabled:
            dispatcher = get_outbox_dispatcher(candidate_settings)
            watchdog = get_integration_watchdog(candidate_settings)
            tasks.append(asyncio.create_task(dispatcher.run(stop_event)))

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
        try:
            yield
        finally:
            stop_event.set()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    return app_lifespan


app = FastAPI(
    title="Picking Assistant API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=build_lifespan(settings),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
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
