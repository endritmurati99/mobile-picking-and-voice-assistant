---
paths:
  - "Mobile Picking und Voice Assistant/pwa/**/*"
---

# Frontend Rules

- Halte die PWA bei Vanilla HTML, CSS und JavaScript. Keine Framework-Einfuehrung ohne ausdrueckliche Anforderung.
- Die PWA spricht ausschliesslich mit `/api/*`. Keine direkte Kommunikation mit Odoo, PostgreSQL oder n8n aus dem Frontend.
- Mobile-first bleibt Pflicht. Touch muss immer als Fallback funktionieren, auch wenn Voice oder Scan aktiv sind.
- Bei UI-Aenderungen stabile, testbare DOM-Strukturen beibehalten und `verify-ui` gruen halten.
- Bei sichtbaren UI-Aenderungen an Layout, CSS, HTML oder UI-relevanten `pwa/*.js` Dateien zusaetzlich `verify-visual` ausfuehren.
- `verify-visual` erzeugt semantisch validierte Mobile-Artefakte unter `.claude/artifacts/`.
- Lies zuerst `.claude/artifacts/ui_state-index.json`; die einzelnen PNGs nur dann, wenn du wirklich visuell nachpruefen musst.
- Ein visueller Check zaehlt erst, wenn der Capture-Lauf nicht nur `#app`, sondern den Ready-State der jeweiligen View bestaetigt.
- HTTPS-, Service-Worker-, Kamera- und Mikrofon-Annahmen nicht stillschweigend aufbrechen.
