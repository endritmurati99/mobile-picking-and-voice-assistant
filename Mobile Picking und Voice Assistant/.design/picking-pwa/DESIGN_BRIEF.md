# Design Brief: Picking Assistant PWA — Cross-Device Redesign

## Problem

Der Lagermitarbeiter öffnet die App auf einem Desktop-Browser und sieht einen schmalen, abgeschnittenen Streifen in der Mitte des Bildschirms. Die Farben wirken inkohärent, Kontraste sind unzureichend. Auf dem iPhone fehlen Safe-Area-Abstände und Touch-Targets sind zu klein für Handschuhe. Auf dem Samsung S22 gibt es Scroll-Probleme im Detail-View. Kurz: Das Interface fühlt sich auf keinem Gerät "zuhause" an.

## Solution

Eine Picking-App die sich auf Desktop wie ein echtes Dashboard verhält (zwei Spalten, Sidebar-Navigation, voll genutzter Viewport), auf iPhone als native-ähnliche PWA (Safe Areas, große Touch-Targets, systemnahe Gesten) und auf Android als kompaktes, schnell bedienbare Warehouse-Tool. Ein einziges CSS-System — mobile-first, mit expliziten Desktop-Breakpoints die das Layout grundlegend verändern, nicht nur strecken.

## Experience Principles

1. **Ort vor Inhalt** — Die Lagerposition (z.B. "A-12-3") ist immer die prominenteste Information. Alles andere ist sekundär.
2. **Handschuh-tauglich** — Jedes Touch-Target min. 48×48px, bevorzugt 56px+. Kein hover-only Feedback.
3. **Sofort lesbar bei schlechtem Licht** — WCAG AA als Minimum, kritische Elemente (Location, Quantity, Confirm) WCAG AAA.

## Aesthetic Direction

- **Philosophy**: Warehouse Command Center — klar, direkt, kein Dekor. Daten sind der Content.
- **Tone**: Ruhig-autoritär. Nicht verspielt. Der Picker soll Vertrauen fühlen, nicht Begeisterung.
- **Reference points**: Linear App (Dichte + Typografie), Vercel Dashboard (dark mode Kontraste), Warehouse-Scanner-UIs (große Targets, hohe Lesbarkeit)
- **Anti-references**: Consumer-App-Ästhetik (Pastell, runde Hero-Illustrationen), Material Design 2 (zu farbenfroh)

## Existing Patterns

- **Typography**: Plus Jakarta Sans (variable 400–800), JetBrains Mono (Codes, Labels). Beibehalten.
- **Colors**: Dark Theme `--bg: #151324`, `--surface: #1F1C35`, `--primary: #A299FF`, `--accent: #FF8A7E`. Tokens bleiben, Kontraste werden angehoben.
- **Spacing**: `--radius: 20px`, `--radius-sm: 14px`. CSS custom properties bereits vorhanden.
- **Components**: Alle bestehenden Klassen (`.pick-list-card`, `.detail-shell`, `.nav-btn`, etc.) bleiben erhalten — additive Änderungen only.

## Component Inventory

| Component | Status | Notes |
|-----------|--------|-------|
| `#app` max-width wrapper | **Modify** | Desktop: kein max-width-Phone mehr; 2-Spalten-Grid |
| `#header` | **Modify** | Desktop: wird linke Sidebar; Mobile: bleibt oben |
| `#nav` (Bottom Nav) | **Modify** | Desktop: in Sidebar integriert; Mobile: bleibt unten |
| `main` content area | **Modify** | Desktop: nimmt rechte Spalte ein, volle Höhe |
| `.pick-list-card` | **Keep** | Unverändert |
| `.detail-shell` | **Keep** | Unverändert |
| Desktop-Sidebar | **New** | Nur @media (min-width: 900px) |
| CSS-Kontrast-Fixes | **Modify** | `--ink-muted` und `--line` Werte anpassen |

## Key Interactions

- **Desktop**: Klick auf Picking-Card öffnet Detail in der rechten Spalte (kein Full-Screen-Replace)
- **Mobile**: Bestehende Swipe/Tap-Flows bleiben unverändert
- **Voice-Button**: Auf Desktop prominent in Sidebar, auf Mobile weiterhin im Bottom Nav
- **Status-Toggle**: Desktop: dauerhaft sichtbar in Sidebar-Header

## Responsive Behavior

| Breakpoint | Layout |
|------------|--------|
| < 600px (Mobile) | Single column, Bottom Nav, Full-screen views |
| 600–899px (Tablet) | Wie Mobile, etwas mehr Padding |
| ≥ 900px (Desktop) | 2-Spalten: 280px Sidebar links + Flex-1 Content rechts |
| ≥ 1400px (Wide) | Sidebar 320px, Content zentriert max-width 1100px |

## Accessibility Requirements

- Kontrast `--ink` auf `--bg`: min. 7:1 (WCAG AAA)
- Kontrast `--ink-soft` auf `--surface`: min. 4.5:1 (WCAG AA)
- `--ink-muted` auf `--surface`: min. 3:1 (für dekorative Labels)
- Touch-Targets: min. 48×48px überall
- Focus-Ring: sichtbar, 3px, in `--primary` Farbe
- `prefers-reduced-motion`: Animationen deaktivierbar

## Out of Scope

- Dark/Light-Mode-Toggle UI (existiert bereits, wird nicht verändert)
- Backend/API-Logik
- Voice-Engine-Änderungen
- n8n-Workflow-Änderungen
- Neue Seiten oder Views (kein neues Feature)
