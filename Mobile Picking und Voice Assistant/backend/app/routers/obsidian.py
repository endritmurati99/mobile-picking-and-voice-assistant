import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from app.dependencies import require_n8n_callback_secret
from app.schemas.obsidian import ObsidianLogRequest, ObsidianSearchRequest
from app.services.obsidian_context import format_obsidian_hits, search_obsidian_notes

router = APIRouter(prefix="/obsidian", tags=["obsidian"])

# Pfad zu deinem Obsidian-Vault (relativ zum Projekt-Root)
OBSIDIAN_BASE_PATH = os.getenv("OBSIDIAN_PATH", "../../../Notzien")
DAILY_NOTES_PATH = os.path.join(OBSIDIAN_BASE_PATH, "02 - Daily Notes")

@router.post("/log", dependencies=[Depends(require_n8n_callback_secret)])
async def log_to_daily_note(request: ObsidianLogRequest):
    today = datetime.now().strftime("%Y-%m-%d")
    file_path = os.path.join(DAILY_NOTES_PATH, f"{today}.md")
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"\n- [{timestamp}] **{request.category}**: {request.message}"
    
    try:
        # Sicherstellen, dass der Ordner existiert
        os.makedirs(DAILY_NOTES_PATH, exist_ok=True)
        
        # Datei im Append-Modus öffnen oder erstellen
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
            
        return {"status": "success", "file": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Schreiben in Obsidian: {str(e)}")


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
