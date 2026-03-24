---
paths:
  - "Mobile Picking und Voice Assistant/odoo/**/*"
---

# Odoo Rules

- Odoo bleibt das System of Record. Keine Logik aus `odoo/` in die PWA verschieben und keine Schatten-Datenmodelle im Backend aufbauen.
- Arbeite bei Addon-Aenderungen bevorzugt additiv und stabil. Bestehende Modellnamen wie `quality.alert.custom` und `quality.alert.stage.custom` nicht stillschweigend umbenennen.
- Wenn du Felder in Python-Modellen aenderst, pruefe immer die betroffenen XML-Views, Security-Dateien, Demo-/Data-Dateien und die FastAPI-Seite mit.
- Die externe API-Methode `api_create_alert` ist ein Vertragsanker fuer das Backend. Aendere Payload-Form oder Rueckgabe nicht ohne passende Backend-Anpassung.
- `sudo()` nur dort verwenden, wo der bestehende API-Pfad es bewusst vorsieht. Keine pauschale Rechte-Umgehung in normalen Formular-/Button-Flows einfuehren.
- Bei View-Aenderungen in XML auf Odoo-kompatible Widgets, Statusbar-/Button-Flows und lesbare Form-/List-/Kanban-Strukturen achten.
- Wenn Odoo-Feldnamen oder Workflows die FastAPI- oder n8n-Vertraege beeinflussen, danach mindestens `verify-code` und bei Webhook-Folgen zusaetzlich `verify-workflows` einplanen.
- Keine Aenderung an Core-Stock-Logik oder Odoo-Standardmodellen ohne klaren fachlichen Grund; zuerst das Custom-Addon bevorzugen.

## SCHUTZ: quality_alert_custom — NICHT ANFASSEN OHNE EXPLIZITE ANWEISUNG

Das Addon `quality_alert_custom` ist stabil und funktionsfaehig. Folgende Dateien sind **eingefroren**:

| Datei | Warum geschuetzt |
|---|---|
| `models/quality_alert.py` | Vollstaendiges Modell mit stage_id, mail.thread, lot_id, photo_gallery, api_create_alert — alles benoetigt |
| `views/quality_alert_views.xml` | Kanban mit Spalten (Neu/In Bearbeitung/Erledigt), Form mit Chatter, List; einzige Aenderung war Entfernung von widget="many2one_avatar_user" (Enterprise-only) |
| `security/quality_alert_security.xml` | Gruppen + base.group_user implied — sonst verliert admin nach Reinstall den Zugriff |
| `data/quality_alert_data.xml` | Stage-Records mit noupdate="1" |
| `__manifest__.py` | Korrekte depends, data-Reihenfolge, view-Dateiname (Plural: quality_alert_views.xml) |

**Kritische Lektionen (aus langer Fehlersuche gelernt):**
- `widget="many2one_avatar_user"` ist Enterprise-only → KanbanArchParser-Crash in Community
- `_read_group_stage_ids(self, stages, domain)` Odoo-18-Signatur (kein `order`-Parameter)
- `web_icon` auf Root-Menuitem ist Pflicht fuer Home-Screen-Sichtbarkeit in Odoo 18
- Aktive DB ist `masterfischer`, NICHT `picking`
- Nach Reinstall sind Gruppen leer — deshalb `base.group_user implied group_quality_user` in security XML
