import json
import os
import subprocess
import sys
from pathlib import Path


VERIFY_PREFIXES = (
    "Mobile Picking und Voice Assistant/backend/",
    "Mobile Picking und Voice Assistant/n8n/workflows/",
    "Mobile Picking und Voice Assistant/odoo/",
    "Mobile Picking und Voice Assistant/pwa/",
    "Mobile Picking und Voice Assistant/infrastructure/scripts/",
    "Mobile Picking und Voice Assistant/docker-compose.yml",
)

UI_VERIFY_PREFIXES = (
    "Mobile Picking und Voice Assistant/pwa/",
    "Mobile Picking und Voice Assistant/e2e/",
    "Mobile Picking und Voice Assistant/playwright.config.js",
    "Mobile Picking und Voice Assistant/package.json",
)

VISUAL_VERIFY_SUFFIXES = (".css", ".html", ".js")

CODE_VERIFY_PREFIXES = (
    "Mobile Picking und Voice Assistant/backend/",
    "Mobile Picking und Voice Assistant/odoo/",
    "Mobile Picking und Voice Assistant/infrastructure/scripts/",
    "Mobile Picking und Voice Assistant/docker-compose.yml",
)

WORKFLOW_VERIFY_PREFIXES = (
    "Mobile Picking und Voice Assistant/backend/app/",
    "Mobile Picking und Voice Assistant/n8n/workflows/",
)


def load_payload() -> dict:
    raw_bytes = sys.stdin.buffer.read()
    if not raw_bytes:
        return {}

    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            raw = raw_bytes.decode(encoding).strip()
            break
        except UnicodeDecodeError:
            raw = ""

    if not raw:
        return {}

    return json.loads(raw)


def load_state(project_dir: Path) -> dict:
    state_path = project_dir / ".claude" / "state" / "last_obsidian_sync.json"
    if not state_path.exists():
        return {}

    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(project_dir: Path, state: dict) -> None:
    state_path = project_dir / ".claude" / "state" / "last_obsidian_sync.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def resolve_project_root(payload: dict) -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)

    start = Path(payload.get("cwd") or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".claude").exists() or (candidate / ".mcp.json").exists():
            return candidate
    return start


def requires_verify(edited_paths: list[str]) -> bool:
    return any(path.startswith(VERIFY_PREFIXES) for path in edited_paths)


def requires_code_verify(edited_paths: list[str]) -> bool:
    return any(path.startswith(CODE_VERIFY_PREFIXES) for path in edited_paths)


def requires_ui_verify(edited_paths: list[str]) -> bool:
    return any(path.startswith(UI_VERIFY_PREFIXES) for path in edited_paths)


def requires_visual_verify(edited_paths: list[str]) -> bool:
    for path in edited_paths:
        if path in {
            "Mobile Picking und Voice Assistant/playwright.config.js",
            "Mobile Picking und Voice Assistant/package.json",
            "Mobile Picking und Voice Assistant/package-lock.json",
            "Mobile Picking und Voice Assistant/e2e/capture-sight.js",
            ".claude/rules/frontend.md",
        }:
            return True
        if path.startswith("Mobile Picking und Voice Assistant/e2e/helpers/") and path.endswith(".js"):
            return True
        if path.startswith("Mobile Picking und Voice Assistant/pwa/") and path.endswith(VISUAL_VERIFY_SUFFIXES):
            return True
    return False


def requires_workflow_verify(edited_paths: list[str]) -> bool:
    return any(path.startswith(WORKFLOW_VERIFY_PREFIXES) for path in edited_paths)


def run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(cwd), text=True, capture_output=True)


def stack_is_running(app_root: Path) -> bool:
    result = run_command(
        ["docker", "compose", "ps", "--services", "--filter", "status=running"],
        cwd=app_root,
    )
    if result.returncode != 0:
        return False

    services = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return {"caddy", "backend"}.issubset(services)


def main() -> int:
    try:
        payload = load_payload()
    except json.JSONDecodeError:
        return 0

    if not payload:
        return 0

    project_dir = resolve_project_root(payload)
    app_root = project_dir / "Mobile Picking und Voice Assistant"
    state = load_state(project_dir)
    session_id = payload.get("session_id")

    if not state or state.get("session_id") != session_id:
        return 0

    edited_paths = state.get("edited_paths") or []
    if not edited_paths:
        return 0

    log_path = project_dir / "Notzien (Obsidian)" / "04 - Ressourcen" / "Claude Code Aenderungslog.md"
    if not log_path.exists() or not state.get("last_synced_at"):
        sys.stderr.write(
            "Kein erfolgreicher Obsidian-Sync fuer diese Session gefunden. "
            "Fuehre den Dateiaenderungs-Hook erfolgreich aus, bevor du den Task abschliesst.\n"
        )
        return 2

    if not requires_verify(edited_paths):
        print("Completion check: Obsidian-Sync fuer diese Session bestaetigt. Keine Code-Verifikation notwendig.")
        state["edited_paths"] = []
        save_state(project_dir, state)
        return 0

    workflow_script = app_root / "infrastructure" / "scripts" / "workflow.ps1"
    if requires_code_verify(edited_paths):
        verify_code = run_command(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(workflow_script), "verify-code"],
            cwd=app_root,
        )
        if verify_code.returncode != 0:
            sys.stderr.write("verify-code fehlgeschlagen. Bitte behebe die Fehler vor dem Task-Abschluss.\n")
            sys.stderr.write(verify_code.stdout)
            sys.stderr.write(verify_code.stderr)
            combined_output = f"{verify_code.stdout}\n{verify_code.stderr}"
            if "ModuleNotFoundError" in combined_output or "No module named" in combined_output:
                sys.stderr.write(
                    "\nHinweis: Lokale Python-Abhaengigkeiten fehlen. "
                    "Fuehre bei Bedarf `powershell -ExecutionPolicy Bypass -File infrastructure/scripts/workflow.ps1 install-backend-deps` aus.\n"
                )
            return 2
        print("Completion check: verify-code erfolgreich.")
    else:
        print("Completion check: verify-code uebersprungen, keine Backend/Odoo-Aenderungen erkannt.")

    if requires_ui_verify(edited_paths):
        verify_ui = run_command(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(workflow_script), "verify-ui"],
            cwd=app_root,
        )
        if verify_ui.returncode != 0:
            sys.stderr.write("verify-ui fehlgeschlagen. Bitte behebe die Fehler vor dem Task-Abschluss.\n")
            sys.stderr.write(verify_ui.stdout)
            sys.stderr.write(verify_ui.stderr)
            combined_output = f"{verify_ui.stdout}\n{verify_ui.stderr}"
            if "Cannot find module" in combined_output or "playwright" in combined_output.lower():
                sys.stderr.write(
                    "\nHinweis: Playwright oder der Chromium-Browser fehlen. "
                    "Fuehre bei Bedarf `powershell -ExecutionPolicy Bypass -File infrastructure/scripts/workflow.ps1 install-ui-deps` aus.\n"
                )
            return 2
        print("Completion check: verify-ui erfolgreich.")
    else:
        print("Completion check: verify-ui uebersprungen, keine PWA/UI-Aenderungen erkannt.")

    if requires_visual_verify(edited_paths):
        verify_visual = run_command(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(workflow_script), "verify-visual"],
            cwd=app_root,
        )
        if verify_visual.returncode != 0:
            sys.stderr.write("verify-visual fehlgeschlagen. Bitte behebe den visuellen Capture-Loop vor dem Task-Abschluss.\n")
            sys.stderr.write(verify_visual.stdout)
            sys.stderr.write(verify_visual.stderr)
            return 2
        print("Completion check: verify-visual erfolgreich.")
    else:
        print("Completion check: verify-visual uebersprungen, keine sichtbaren UI-Aenderungen erkannt.")

    if requires_visual_verify(edited_paths):
        verify_visual_diff = run_command(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(workflow_script), "verify-visual-diff"],
            cwd=app_root,
        )
        if verify_visual_diff.returncode != 0:
            sys.stderr.write("verify-visual-diff fehlgeschlagen. Bitte gleiche die visuellen Baselines oder das Layout ab.\n")
            sys.stderr.write(verify_visual_diff.stdout)
            sys.stderr.write(verify_visual_diff.stderr)
            return 2
        print("Completion check: verify-visual-diff erfolgreich.")
    else:
        print("Completion check: verify-visual-diff uebersprungen, keine sichtbaren UI-Aenderungen erkannt.")

    if requires_ui_verify(edited_paths):
        verify_a11y = run_command(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(workflow_script), "verify-a11y"],
            cwd=app_root,
        )
        if verify_a11y.returncode != 0:
            sys.stderr.write("verify-a11y fehlgeschlagen. Bitte behebe die Accessibility-Verstoesse vor dem Task-Abschluss.\n")
            sys.stderr.write(verify_a11y.stdout)
            sys.stderr.write(verify_a11y.stderr)
            return 2
        print("Completion check: verify-a11y erfolgreich.")
    else:
        print("Completion check: verify-a11y uebersprungen, keine PWA/UI-Aenderungen erkannt.")

    if requires_workflow_verify(edited_paths):
        verify_workflows = run_command(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(workflow_script), "verify-workflows"],
            cwd=app_root,
        )
        if verify_workflows.returncode != 0:
            sys.stderr.write("verify-workflows fehlgeschlagen. Bitte gleiche Backend- und n8n-Vertraege ab.\n")
            sys.stderr.write(verify_workflows.stdout)
            sys.stderr.write(verify_workflows.stderr)
            return 2
        print("Completion check: verify-workflows erfolgreich.")
    else:
        print("Completion check: verify-workflows uebersprungen, keine Workflow-relevanten Aenderungen erkannt.")

    if stack_is_running(app_root):
        verify_stack = run_command(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(workflow_script), "verify-stack"],
            cwd=app_root,
        )
        if verify_stack.returncode != 0:
            sys.stderr.write("verify-stack fehlgeschlagen, obwohl der lokale Stack laeuft.\n")
            sys.stderr.write(verify_stack.stdout)
            sys.stderr.write(verify_stack.stderr)
            return 2
        print("Completion check: verify-stack erfolgreich.")
    else:
        print("Completion check: verify-stack uebersprungen, weil der lokale Stack nicht laeuft.")

    state["edited_paths"] = []
    save_state(project_dir, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
