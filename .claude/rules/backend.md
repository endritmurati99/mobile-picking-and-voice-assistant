---
paths:
  - "Mobile Picking und Voice Assistant/backend/**/*"
---

# Backend Rules

- Odoo bleibt System of Record. Keine Schatten-Datenhaltung im Backend.
- FastAPI ist die einzige API-Schicht fuer die PWA. Keine direkte PWA-zu-Odoo- oder PWA-zu-n8n-Kopplung einfuehren.
- n8n bleibt aus dem Voice-Hot-Path heraus; Webhooks muessen fire-and-forget bleiben.
- Aendere Webhook-Vertraege nur zusammen mit `n8n/workflows/` und halte `verify-workflows` gruen.
- Fuer Backend-Aenderungen `verify-code` als Mindestcheck betrachten; bei Vertragsaenderungen zusaetzlich `verify-workflows`.
