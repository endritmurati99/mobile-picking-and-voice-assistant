import os
from datetime import datetime
from fastapi import APIRouter, HTTPException
from app.schemas.obsidian import ObsidianLogRequest

router = APIRouter(prefix="/obsidian", tags=["obsidian"])

# Pfad zu deinem Obsidian-Vault (relativ zum Projekt-Root)
OBSIDIAN_BASE_PATH = os.getenv("OBSIDIAN_PATH", "../../../Notzien")
DAILY_NOTES_PATH = os.path.join(OBSIDIAN_BASE_PATH, "02 - Daily Notes")

@router.post("/log")
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
