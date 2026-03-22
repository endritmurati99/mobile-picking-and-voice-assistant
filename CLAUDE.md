# CLAUDE.md

Repository-Einstiegspunkt fuer Claude Code im Root von `Bachelor/`.

## Arbeitsbereiche

- Produkt- und Infrastrukturcode liegt in `Mobile Picking und Voice Assistant/`
- Wissensmanagement und Projektnotizen liegen in `Notzien (Obsidian)/`

## Routing

- Fuer Implementierung, Tests und Infrastruktur im Produktcode ist `Mobile Picking und Voice Assistant/CLAUDE.md` die operative Hauptanweisung.
- Fuer Architekturtexte und Fortschrittsnotizen arbeite gezielt in `Notzien (Obsidian)/`, aber nicht in `.obsidian/`.
- Starte bei Produktarbeit bevorzugt im Verzeichnis `Mobile Picking und Voice Assistant/`, damit der Kontext klein bleibt.

## Kontext-Hygiene

- Scanne nicht den gesamten Repo-Baum ohne Grund.
- Lies Obsidian-Dateien nur gezielt.
- Lokale Secrets, Zertifikate, Caches und Binary-Artefakte bleiben aus dem aktiven Kontext.

## Completion

- Task-Abschluss ist an die Projekt-Hooks gebunden.
- Wenn in einer Claude-Session Dateien editiert wurden, muessen Obsidian-Sync und die relevanten Verify-Schritte erfolgreich sein, bevor der Task als abgeschlossen gelten soll.
