from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, cluster, demo, health, instances, integration, llm, n8n_internal, obsidian, pickings, quality, scan, voice
# Task 10: eigene Importzeile, damit parallele Branches die Zeile oben nicht anfassen muessen.
from app.routers import n8n_v2

app = FastAPI(
    title="Picking Assistant API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
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
# Task 10: signierte v2-Routen, wie n8n_internal unter /api gemountet. Der
# Legacy-Router n8n_internal bleibt bewusst daneben bestehen (v1).
app.include_router(n8n_v2.router, prefix="/api", tags=["n8n-v2"])
