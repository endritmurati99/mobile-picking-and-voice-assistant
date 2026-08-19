"""Der Fehlerpfad darf nicht am eigenen Protokoll scheitern.

Live am 19.08.2026 beobachtet: der n8n-Error-Workflow ruft
`POST /api/integration/log`, und das Backend antwortete mit 500, weil
`docker-compose.yml` das Zielverzeichnis bewusst schreibgeschuetzt einhaengt.
Eine Fehlerbenachrichtigung, die selbst einen Fehler ausloest, ist keine.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import app.services.integration_log as integration_log
from app.schemas.obsidian import ObsidianLogRequest


def _request() -> ObsidianLogRequest:
    return ObsidianLogRequest(
        category="quality_assessment_failed",
        message="Absichtlicher Fehler zum Nachweis des Fehlerpfads",
        timestamp=datetime(2026, 8, 19, 10, 4, 12),
    )


def test_readonly_target_degrades_instead_of_raising(monkeypatch, tmp_path):
    """Genau der Live-Fall: das Zielverzeichnis laesst sich nicht anlegen."""

    def _readonly_mkdir(self, *args, **kwargs):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(
        integration_log, "DEFAULT_DAILY_NOTES_PATH", tmp_path / "02 - Daily Notes"
    )
    monkeypatch.setattr(Path, "mkdir", _readonly_mkdir)

    result = integration_log.write_daily_note_log(_request())

    assert result["status"] == "skipped"
    assert "Read-only file system" in result["reason"]


def test_unwritable_file_degrades_too(monkeypatch, tmp_path):
    """Verzeichnis vorhanden, Datei aber nicht zu oeffnen."""

    target = tmp_path / "02 - Daily Notes"
    target.mkdir()
    monkeypatch.setattr(integration_log, "DEFAULT_DAILY_NOTES_PATH", target)

    def _unwritable_open(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "open", _unwritable_open)

    result = integration_log.write_daily_note_log(_request())

    assert result["status"] == "skipped"


def test_writable_target_still_writes(monkeypatch, tmp_path):
    """Der gute Fall bleibt unveraendert -- kein stiller Verlust."""

    target = tmp_path / "02 - Daily Notes"
    monkeypatch.setattr(integration_log, "DEFAULT_DAILY_NOTES_PATH", target)

    result = integration_log.write_daily_note_log(_request())

    assert result["status"] == "success"
    written = Path(result["file"]).read_text(encoding="utf-8")
    assert "quality_assessment_failed" in written
    assert "10:04:12" in written
