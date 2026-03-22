import json
import os
import sys
from datetime import datetime
from pathlib import Path


def extract_path(payload: dict) -> str | None:
    tool_input = payload.get("tool_input") or {}
    for key in ("file_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def ensure_header(note_path: Path) -> None:
    if note_path.exists():
        return
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "---\n"
        "title: Claude Code Aenderungslog\n"
        "tags:\n"
        "  - workflow\n"
        "  - claude-code\n"
        "  - changelog\n"
        "---\n\n"
        "# Claude Code Aenderungslog\n\n"
        "Automatisches Protokoll fuer von Claude Code bearbeitete Dateien.\n\n"
        "## Eintraege\n",
        encoding="utf-8",
    )


def main() -> None:
    raw_bytes = sys.stdin.buffer.read()
    if not raw_bytes:
        return
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            raw = raw_bytes.decode(encoding).strip()
            break
        except UnicodeDecodeError:
            raw = ""
    if not raw:
        return

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return

    changed_path = extract_path(payload)
    if not changed_path:
        return

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path.cwd()))
    note_path = project_dir / "Notzien (Obsidian)" / "04 - Ressourcen" / "Claude Code Aenderungslog.md"
    ensure_header(note_path)

    try:
        relative_path = Path(changed_path).resolve().relative_to(project_dir.resolve())
        display_path = relative_path.as_posix()
    except Exception:
        display_path = changed_path.replace("\\", "/")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tool_name = payload.get("tool_name", "unknown")

    with note_path.open("a", encoding="utf-8") as handle:
        handle.write(f"- {timestamp} | {tool_name} | `{display_path}`\n")


if __name__ == "__main__":
    main()
