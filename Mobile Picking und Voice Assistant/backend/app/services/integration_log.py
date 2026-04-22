from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from app.schemas.obsidian import ObsidianLogRequest


OBSIDIAN_BASE_PATH = Path(os.getenv("OBSIDIAN_PATH", "../../../Notzien"))
DEFAULT_DAILY_NOTES_PATH = OBSIDIAN_BASE_PATH / "02 - Daily Notes"


def write_daily_note_log(request: ObsidianLogRequest) -> dict[str, str]:
    target_dir = DEFAULT_DAILY_NOTES_PATH
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp_source = request.timestamp or datetime.now()
    timestamp = timestamp_source.strftime("%H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")
    file_path = target_dir / f"{today}.md"
    log_entry = f"\n- [{timestamp}] **{request.category}**: {request.message}"

    try:
        with file_path.open("a", encoding="utf-8") as handle:
            handle.write(log_entry)
    except Exception as exc:  # pragma: no cover - exercised through route tests
        raise HTTPException(status_code=500, detail=f"Fehler beim Schreiben ins Integrationslog: {exc}") from exc

    return {"status": "success", "file": str(file_path)}
