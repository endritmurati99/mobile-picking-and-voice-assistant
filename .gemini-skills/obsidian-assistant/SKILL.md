---
name: obsidian-assistant
description: Specialized for maintaining the Obsidian vault in the Bachelor project. Handles Daily Notes, Changelogs, and Architectural consistency. Use this skill when working with the 'Notzien/' directory or when documentation updates are required after code changes.
---

# Obsidian Assistant

This skill provides specialized workflows for maintaining the project's documentation vault in Obsidian.

## Core Structure
*   **Vault Root:** `Notzien/`
*   **Daily Notes:** `Notzien/02 - Daily Notes/`
*   **Changelog:** `Notzien/04 - Ressourcen/Claude Code Aenderungslog.md`
*   **Templates:** `Notzien/_templates/`

## Workflows

### 1. Daily Note Management
When a task is completed or at the start of a session, ensure the Daily Note is updated.
*   **Current Date:** Use the current date in `YYYY-MM-DD.md` format.
*   **Note Creation:** If the note for today does not exist:
    1.  Read `Notzien/_templates/Daily Note.md`.
    2.  Create the new note in `Notzien/02 - Daily Notes/`.
    3.  Replace placeholders like `{{date:YYYY-MM-DD}}` and `{{date:W}}` (KW number).
*   **Note Update:** If the note exists, append a new section `## Session: [Summary]` or update existing sections (`Fortschritt`, `Entscheidungen`, `Nächste Schritte`).

### 2. Change Logging
After any file modification (Write, Edit, MultiEdit), add an entry to `Notzien/04 - Ressourcen/Claude Code Aenderungslog.md`.
*   **Format:** `- YYYY-MM-DD HH:MM:SS | [ToolName] | `[display_path]``
*   **Context:** Ensure the log remains chronological.

### 3. Architectural Consistency
When modifying core systems (Backend, Odoo, n8n, PWA), check relevant notes in `Notzien/01 - Architektur/` to ensure changes align with established decisions. Update these notes if the architecture evolves.

## Guidelines
*   **Monospace Paths:** Always use backticks for file paths in notes.
*   **Internal Links:** Use `[[Note Name]]` or `[[Folder/Note Name|Display Name]]` for cross-referencing.
*   **Imperative Style:** Keep documentation concise and professional.
