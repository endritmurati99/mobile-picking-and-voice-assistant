from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import pickings, quality, voice, scan, health, obsidian, n8n_internal

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

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(pickings.router, prefix="/api", tags=["pickings"])
app.include_router(quality.router, prefix="/api", tags=["quality"])
app.include_router(voice.router, prefix="/api", tags=["voice"])
app.include_router(scan.router, prefix="/api", tags=["scan"])
app.include_router(obsidian.router, prefix="/api", tags=["obsidian"])
app.include_router(n8n_internal.router, prefix="/api")
