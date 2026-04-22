from fastapi import APIRouter, Depends, Query

from app.dependencies import require_n8n_callback_secret
from app.schemas.obsidian import ObsidianLogRequest, ObsidianSearchRequest
from app.services.integration_log import write_daily_note_log
from app.services.obsidian_context import format_obsidian_hits, search_obsidian_notes


router = APIRouter(prefix="/obsidian", tags=["obsidian"])


@router.post("/log", dependencies=[Depends(require_n8n_callback_secret)], deprecated=True)
async def log_to_daily_note(request: ObsidianLogRequest):
    return write_daily_note_log(request)


@router.get("/search")
async def search_obsidian(
    q: str = Query(..., min_length=2, description="Freitext fuer die Obsidian-Suche"),
    limit: int = Query(default=3, ge=1, le=10),
):
    hits = search_obsidian_notes([q], limit=limit)
    return {
        "query": q,
        "count": len(hits),
        "context_text": format_obsidian_hits(hits),
        "hits": hits,
    }


@router.post("/search")
async def search_obsidian_post(request: ObsidianSearchRequest):
    q = request.query
    limit = request.limit
    hits = search_obsidian_notes([q], limit=limit)
    return {
        "query": q,
        "count": len(hits),
        "context_text": format_obsidian_hits(hits),
        "hits": hits,
    }
