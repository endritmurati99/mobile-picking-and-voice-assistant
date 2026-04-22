# AGENTS.md

Gemeinsame Arbeitsanweisung fuer Codex, Claude Code und andere Coding-Agenten
im Projekt `Mobile Picking und Voice Assistant`.

## Ziel

Fuer Odoo und n8n gilt in diesem Projekt standardmaessig:

- CLI first
- MCP nur wenn ausdruecklich verlangt
- fuer Agenten bevorzugt One-shot-Kommandos mit `--json`
- erst lesen und verifizieren, dann schreiben oder aktivieren

## Bevorzugte lokale CLIs

Nutze diese Wrapper statt direkter MCP-Interaktion:

- `n8nctl.cmd`
- `odoocli`

Wenn die Wrapper im aktuellen Terminal nicht gefunden werden, nutze die direkten Pfade:

```powershell
C:\Users\endri\.local\bin\n8nctl.cmd
C:\Users\endri\.local\bin\odoocli.cmd
```

## n8n

### Standardregel

- Fuer Agenten immer One-shot-Aufrufe bevorzugen
- REPL nur fuer manuelle, interaktive Nutzung
- fuer maschinenlesbare Auswertung `--json` verwenden

### Read-first Befehle

```powershell
n8nctl.cmd --json session status
n8nctl.cmd --json server health
n8nctl.cmd --json server api-check
n8nctl.cmd --json workflow list
n8nctl.cmd --json workflow list --active
n8nctl.cmd --json workflow get "Quality Alert Created"
n8nctl.cmd --json workflow local-list --details
n8nctl.cmd --json credential list
n8nctl.cmd --json user me
n8nctl.cmd --json audit generate --categories credentials,nodes
```

Hinweis:

- `workflow list` liefert jetzt standardmaessig alle Live-Workflows, inklusive inaktiver und archivierter Eintraege.
- Wenn nur aktive Workflows gebraucht werden, immer explizit `workflow list --active` verwenden.

### Schreibende oder riskantere Befehle

Nur nach klarer Nutzerfreigabe:

```powershell
n8nctl.cmd workflow activate --file shortage-reported.json
n8nctl.cmd workflow deactivate --file voice-exception-query.json
n8nctl.cmd workflow import .\n8n\workflows\quality-alert-created.json
n8nctl.cmd credential import .\n8n\backups\credentials\gmail.json
n8nctl.cmd credential export-all --backup -o .\n8n\backups\credentials
n8nctl.cmd rollout backup
n8nctl.cmd rollout import <backup-dir>
n8nctl.cmd rollout activate <backup-dir>
n8nctl.cmd rollout rollback <backup-dir>
```

## Odoo

### Standardregel

- vor jeder echten Arbeit zunaechst `auth whoami` pruefen
- wenn nicht eingeloggt, Passwort-Login verwenden
- fuer Agenten bevorzugt `--json`

### Login-Flow

```powershell
odoocli --json auth whoami
```

Falls das fehlschlaegt:

```powershell
odoocli auth login --password admin
```

Danach erneut pruefen:

```powershell
odoocli --json auth whoami
```

### Read-first Befehle

```powershell
odoocli --json config show
odoocli --json db list
odoocli --json server version
odoocli --json model search-read res.users --fields id,name,login --limit 5
odoocli --json model fields stock.picking --attributes string,type,required
odoocli --json model call stock.picking search_count --args "[[]]"
```

### Domain-Filter in PowerShell

Bei JSON-Domains in PowerShell zuerst eine Variable setzen:

```powershell
$domain = '[["state","=","assigned"]]'
odoocli --json model search-read stock.picking --domain $domain --fields id,name,state --limit 10
```

Weiteres Beispiel:

```powershell
$domain = '[["picking_id","=",337]]'
odoocli --json model search-read quality.alert.custom --domain $domain --fields id,name,stage_id,ai_evaluation_status --limit 20
```

### Schreibende Befehle

Nur nach klarer Nutzerfreigabe:

```powershell
odoocli model create <model> --values "{...}"
odoocli model write <model> --ids 1,2 --values "{...}"
odoocli model call <model> <method> --ids 123 --args "[...]" --kwargs "{...}"
```

## Agent-Workflow

Wenn ein Agent Odoo oder n8n anfasst, ist die Reihenfolge:

1. Verbindung oder Auth pruefen
2. aktuelle Daten oder Konfiguration lesen
3. Ergebnisse kurz zusammenfassen
4. erst dann aendernde Befehle ausfuehren
5. Ergebnis danach erneut lesend verifizieren

## Gute Prompt-Formulierungen

```text
Nutze nicht MCP. Nutze die lokalen CLIs n8nctl.cmd und odoocli. Fuer Agenten nach Moeglichkeit immer --json verwenden. Erst lesen, dann aendern.
```

```text
Nutze odoocli, pruefe auth, lies dann die letzten 10 quality.alert.custom Datensaetze und fasse sie zusammen.
```

```text
Nutze n8nctl.cmd --json workflow list und pruefe, welche Workflows aktiv sind.
```

## Projektkontext

- Projektroot: `C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant`
- n8n nutzt lokale Workflow-Dateien in `n8n/workflows/`
- Odoo ist System of Record
- PWA spricht nur mit FastAPI, nicht direkt mit Odoo oder n8n
- n8n ist Orchestrator, nicht App-Backend

## Dateipolitik

- Diese Datei ist die kanonische Agent-Anweisung fuer CLI-first Arbeit im Projekt.
- `CLAUDE.md` bleibt fuer Claude-Code-spezifische Regeln erhalten.
- Eine Desktop-Kopie dient nur der schnellen Auffindbarkeit.
