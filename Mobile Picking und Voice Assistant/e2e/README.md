# e2e — stillgelegte Browsertests

Dieses Verzeichnis enthält die Playwright-Spezifikationen, mit denen die PWA
zwischen Juni und August 2026 geprüft wurde. Die Ergebnisse dieser Läufe werden
in der Projektdokumentation zitiert, deshalb bleiben die Quelldateien erhalten.

**Die Werkzeugkette selbst ist am 19. August 2026 entfernt worden.** Es gibt
weder `node_modules` noch einen Playwright-Browser mehr, `playwright.config.js`
ist gelöscht und die zugehörigen Make-Ziele (`test-ui`, `test-visual*`,
`test-a11y`, `verify-ui`) existieren nicht mehr. Die Dateien hier sind damit
Belegmaterial, kein ausführbarer Testlauf.

Grund: der Browserteil der Testkette war seit dem Versionswechsel des Chromium-
Pakets nicht mehr lauffähig, und die Wartung dieser Kette stand in keinem
Verhältnis zu ihrem Nutzen für diese Arbeit. Browserprüfungen werden seitdem
interaktiv über eine CDP-Steuerung des ohnehin vorhandenen Chrome durchgeführt.

Ebenfalls entfernt wurden drei reine Hilfsskripte ohne Beleglage
(`capture-sight.js`, `check-n8n-live.js`, `debug-n8n-paths.js`); sie dienten der
Werkzeugunterstützung während der Entwicklung, nicht der Prüfung des Systems.

Wer die Suite wiederbeleben will, braucht `npm install -D @playwright/test
@axe-core/playwright`, eine neue `playwright.config.js` und einen passenden
Chromium. Der Stand vor der Stilllegung liegt vollständig in der
Versionsgeschichte.
