---
paths:
  - "Mobile Picking und Voice Assistant/pwa/**/*"
---

# Frontend Rules

- Halte die PWA bei Vanilla HTML, CSS und JavaScript. Keine Framework-Einfuehrung ohne ausdrueckliche Anforderung.
- Die PWA spricht ausschliesslich mit `/api/*`. Keine direkte Kommunikation mit Odoo, PostgreSQL oder n8n aus dem Frontend.
- Mobile-first bleibt Pflicht. Touch muss immer als Fallback funktionieren, auch wenn Voice oder Scan aktiv sind.
- Bei UI-Aenderungen stabile, testbare DOM-Strukturen beibehalten und `verify-ui` gruen halten.
- HTTPS-, Service-Worker-, Kamera- und Mikrofon-Annahmen nicht stillschweigend aufbrechen.
