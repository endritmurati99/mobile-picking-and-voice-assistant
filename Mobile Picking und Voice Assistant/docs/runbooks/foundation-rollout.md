# Foundation Rollout

Ausrollreihenfolge und Rückfallpunkte für das Foundation-Programm.

Die Reihenfolge ist nicht redaktionell. Jeder Schritt setzt voraus, dass der
vorige beweisbar bestanden hat, und die teuren, schwer rückholbaren Schritte
(Dispatcher scharf, Produktions-Caddy, Grace-Mode aus) stehen bewusst am Ende:
was vorher schiefgeht, kostet einen Neuversuch, was danach schiefgeht, kostet
einen Rückbau im Betrieb.

**Kein Schritt gilt als bestanden, weil er übersprungen wurde.** Die Live-Gates
scheitern hart, wenn die Umgebung fehlt — ein `skip` ist kein Ergebnis.

## Voraussetzungen

| Sache | Woher |
|---|---|
| Integrationscommit | `git rev-parse HEAD` auf `integration/foundation-remediation` |
| Datenbank-Sicherungen | unveränderlich, vor Schritt 1, mit Prüfsumme |
| Workflow-Sicherungen | `infrastructure/scripts/import-workflows.sh backup` |
| Zweiter LAN-Host | für `verify-remote-surface.sh`; ohne ihn existiert das Netz-Gate nicht |
| Mobilgerät | für den TLS-Vertrauenstest; ein `curl` vom Laptop ersetzt ihn nicht |

## Reihenfolge

1. **Integrationscommit festhalten, unveränderliche Sicherungen anlegen** von
   beiden Datenbanken und allen Workflows. Prüfsummen notieren.
2. **Odoo-19-Faktengate und beide Modul-Testtags laufen lassen.**
   ```bash
   docker compose stop odoo   # sonst SerializationFailure
   docker compose run --rm --no-deps -T odoo odoo --no-http --test-enable \
     --stop-after-init --workers=0 --max-cron-threads=0 \
     -d masterfischer_o19_foundation_test \
     -u picking_assistant_integration,picking_assistant_core
   ```
3. **DB-Rollen `backup`, `apply`, `verify`.** Bei jedem unerwarteten
   Cross-Connect anhalten. **Blockiert:** dieser Schritt gehört zu R4, und R4 ist
   zweimal abgelehnt worden (siehe Handoff §4). Ohne freigegebenes R4 wird
   Schritt 3 nicht ausgeführt und Schritt 5 läuft gegen die Bestandsrollen.
4. **Integrationsmodelle mit `DISPATCHER_ENABLED=false` ausrollen.** Der
   Dispatcher bleibt aus, bis Schritt 12 ihn gezielt für ein einziges Event
   einschaltet.
5. **Zwei-Datenbank- und Nebenläufigkeits-Gates.**
   ```bash
   bash infrastructure/scripts/run-foundation-live-gates.sh
   ```
6. **Native und HMAC-Credentials bereitstellen, Metadaten prüfen.** Insbesondere
   `baseUrl` der `pwrOutboundHmac`-Credential: der signierte Node schlägt
   fail-closed fehl, wenn sie nicht dem deklarierten `host` entspricht. Diese
   Credential wurde noch nie gelesen — vor der ersten Aktivierung nachsehen.
7. **v2-Workflows inaktiv importieren, statischen Verifier laufen lassen.**
   ```bash
   python3 n8n/verify-workflows.py
   ```
8. **Nur den Foundation-Smoke über `activate-test` aktivieren**, signierte,
   binäre und Replay-Tests fahren, danach das passende `deactivate-test` mit
   derselben `RUN_ID` verlangen. Eine fehlende oder abweichende `RUN_ID` ist ein
   harter Fehler, kein Hinweis.
   > **Der Smoke-Workflow ist noch nie gelaufen.** `Build Acceptance` liest
   > `$json.body.event_id`, während der Webhook mit `rawBody: true` läuft. Ob
   > n8n daneben noch ein geparstes `json.body` füllt, ist ohne laufende
   > n8n-Instanz nicht zu klären. **Das ist das Erste, was der erste Live-Lauf
   > prüfen muss** — trifft es nicht zu, laufen alle Acceptance-Felder leer.
9. **Kill/Restart-Test.**
   ```bash
   bash infrastructure/scripts/test-foundation-restart.sh
   ```
   > **Blockiert:** braucht `api_create_smoke_job` und `api_get_job_probe` auf
   > `picking.assistant.integration.job`. Beide existieren nicht; das Skript
   > bricht mit ihren Namen ab, statt eine erfundene Methode aufzurufen.
10. **Zusammenführen und prüfen:** PWA-Login-Oberfläche, Voice-Assist ohne
    Schreibzugriff, Cluster-Reservierungsgate.
11. **`MOBILE_HEADER_GRACE_MODE=false` setzen, Start prüfen.** Ab hier ist das
    Session-Cookie die einzige Identität, und die PWA muss den Login können.
12. **`DISPATCHER_ENABLED=true` — nur für das Smoke-Event.**
13. **Produktions-Caddy/Compose ausrollen**, dann lokale, entfernte, TLS- und
    Mobilgeräte-Gates.
    ```bash
    bash infrastructure/scripts/verify-production-gates.sh
    bash infrastructure/scripts/verify-remote-surface.sh picking.warehouse.test
    ```
14. **Visual Quality aktivieren, danach Shipping** — ein Workflow nach dem
    anderen, jeder in seinem freigegebenen Plan.
15. **Legacy-v1-Workflows nur so lange behalten**, bis das Rollback-Fenster der
    jeweiligen Ablösung geschlossen ist.

## Rückfall

Jeder Auslöser bricht den Rollout ab. Nicht weiterfahren und „hinterher
reparieren" — die späteren Schritte machen die Diagnose teurer.

| Auslöser | Maßnahme |
|---|---|
| **DB-Isolation scheitert** | Apps stoppen; DB-Rollen-Rollback fahren; vorherige Rollennamen wiederherstellen; Health prüfen. |
| **Session-/PWA-Gate scheitert** | Strikte Produktion aus lassen; vorheriges Frontend zurückspielen; Header-Grace-Mode **nicht** öffentlich freigeben. |
| **Signatur- oder Replay-Gate scheitert** | v2-Workflows deaktivieren; Dispatcher aus; Outbox-Zeilen `pending` lassen; Receipts **nicht** löschen. |
| **Restart-/Duplikat-Gate scheitert** | Dispatcher und Provider-Workflow aus; Job-, Outbox- und Receipt-Sätze zur Prüfung aufbewahren. |
| **Netz-Gate scheitert** | Vorherige Caddy-/Compose-Version hinter der Host-Firewall wiederherstellen; Service-Ports **nicht** als Behelf öffnen. |

Warum Receipts und Outbox-Zeilen in zwei dieser Fälle ausdrücklich bleiben:
sie sind der einzige Nachweis, was tatsächlich zugestellt wurde. Wer sie
aufräumt, um „sauber neu zu starten", vernichtet die Diagnose und wiederholt
den Fehler beim nächsten Versuch.

## Was der Rollout heute noch nicht kann

Ehrlich, damit niemand einen halben Lauf für einen ganzen hält:

- **Schritt 3** hängt an R4 (gesperrt, zweimal abgelehnt).
- **Schritt 9** hängt an einer Odoo-Probe-Oberfläche, die nicht existiert.
- **Schritt 8** hat mit dem `rawBody`/`json.body`-Widerspruch eine offene Frage,
  die nur eine laufende n8n-Instanz beantwortet.
- **Schritt 13** braucht einen zweiten Host und ein echtes Mobilgerät; beides
  wurde noch nie benutzt.
