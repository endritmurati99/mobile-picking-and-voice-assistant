from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from app.schemas.obsidian import ObsidianLogRequest


logger = logging.getLogger(__name__)

OBSIDIAN_BASE_PATH = Path(os.getenv("OBSIDIAN_PATH", "../../../Notzien"))
DEFAULT_DAILY_NOTES_PATH = OBSIDIAN_BASE_PATH / "02 - Daily Notes"


def write_daily_note_log(request: ObsidianLogRequest) -> dict[str, str]:
    """Schreibt eine Zeile ins Tagesprotokoll -- und scheitert dabei niemals hart.

    Befund vom 19.08.2026, live am Fehlerpfad beobachtet: `docker-compose.yml`
    haengt `./docs` bewusst als `:ro` unter `/obsidian` ein, waehrend diese
    Funktion genau dorthin schreiben will. Das `mkdir` lag ausserhalb des
    `try`, also kam ein `OSError: [Errno 30] Read-only file system` als 500
    mitsamt Stacktrace beim Aufrufer an.

    Der einzige Aufrufer ist `POST /api/integration/log`, und der wird vom
    n8n-Error-Workflow benutzt -- also von genau dem Pfad, der laeuft, wenn
    ohnehin schon etwas schiefgegangen ist. Ein Protokolleintrag, der nicht
    geschrieben werden kann, darf die Fehlerbenachrichtigung nicht zusaetzlich
    zum Scheitern bringen. Deshalb: Warnung ins Anwendungsprotokoll, Antwort
    `skipped`, kein 500. Der Vorgang bleibt damit sichtbar, nur eben im
    Container-Log statt in der Notizablage.
    """
    target_dir = DEFAULT_DAILY_NOTES_PATH
    timestamp_source = request.timestamp or datetime.now()
    timestamp = timestamp_source.strftime("%H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")
    file_path = target_dir / f"{today}.md"
    log_entry = f"\n- [{timestamp}] **{request.category}**: {request.message}"

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8") as handle:
            handle.write(log_entry)
    except OSError as exc:
        logger.warning(
            "Integrationslog nicht schreibbar (%s): %s -- Eintrag: %s: %s",
            file_path,
            exc,
            request.category,
            request.message,
        )
        return {"status": "skipped", "file": str(file_path), "reason": str(exc)}

    return {"status": "success", "file": str(file_path)}
