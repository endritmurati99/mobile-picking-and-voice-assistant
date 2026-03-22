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
