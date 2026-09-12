# Isolierte technische Evaluation

Diese Skripte reproduzieren die technische Szenarioevaluation mit künstlichen
Datensätzen. Der Runner liest die Konfiguration und ein Datenbankabbild aus
einem vorhandenen Quellstack, schreibt aber ausschließlich in drei temporäre
Container und die geklonte Datenbank `evaluation`. Das Testnetz ist intern,
hat keine veröffentlichten Ports und startet Odoo ohne Cronjobs; Mailserver und
der Backend-Dispatcher werden in der Kopie deaktiviert.

Der Runner ist für Docker Desktop mit WSL sowie für eine native Linux-Docker-
Umgebung ausgelegt. Standardmäßig verwendet er die Anwendungskopie, in der
dieses Verzeichnis liegt. Ein anderer Checkout muss ausdrücklich mit
`--app-path` angegeben werden. Die Namen der drei Quellcontainer sind ebenfalls
als Optionen sichtbar und können an andere Compose-Projektnamen angepasst
werden:

```bash
python3 infrastructure/evaluation/run_isolated_evaluation.py \
  --output /home/user/audits/picking-evaluation
```

Beispiel mit vollständig angegebenen Quellen:

```bash
python3 infrastructure/evaluation/run_isolated_evaluation.py \
  --app-path '/mnt/c/path/to/Mobile Picking und Voice Assistant' \
  --source-backend-container mobilepickingundvoiceassistant-backend-1 \
  --source-odoo-container mobilepickingundvoiceassistant-odoo-1 \
  --source-db-container mobilepickingundvoiceassistant-db-1 \
  --output /home/user/audits/picking-evaluation
```

Der Runner verweigert die Ausführung, wenn die gemounteten Laufzeitquellen
(`backend/app`, `odoo/addons`, `n8n/workflow-registry.json`) vom ermittelten
Git-Stand abweichen. `environment.json` zeichnet den Git-Tree der Anwendung,
die verwendeten Image-IDs, Isolationsmerkmale und Exitcodes auf. Es enthält
keine Anmeldedaten. Stderr und temporäre Fixture-Daten bleiben unter `private/`
und dürfen nicht veröffentlicht werden.

Alle fünf Szenarioskripte müssen mit Exitcode 0 enden. Dazu gehört seit der
lokalen Vertragskorrektur auch `test_negative_quantity.py`: Eine negative Menge
muss mit HTTP 400 oder 422 abgewiesen werden und darf den Odoo-Zustand nicht
ändern. Bei jedem fehlgeschlagenen Skript endet der Runner mit Exitcode 1 und
`runner-status.json` enthält `status: failed`; ein erfolgreicher Lauf enthält
`status: passed`.

Vorhandene temporäre Ressourcen führen zum Abbruch. `--replace` entfernt nur
`bachelor-eval-db`, `bachelor-eval-odoo`, `bachelor-eval-backend` und das Netz
`bachelor-eval-isolated`, bevor sie neu erstellt werden. Der Quellstack wird
nicht ersetzt. Nach Sicherung der bereinigten Ergebnisse können ausschließlich
diese Testressourcen entfernt werden:

```bash
docker rm -f -v bachelor-eval-backend bachelor-eval-odoo bachelor-eval-db
docker network rm bachelor-eval-isolated
```

Der optionale Sprachversuch verwendet Piper und Whisper aus dem vorhandenen
Stack und ruft keine Buchungsroute auf:

```bash
docker exec -i mobilepickingundvoiceassistant-backend-1 \
  python - < infrastructure/evaluation/voice_synthetic_eval.py \
  > voice_synthetic_results.json
```

Er verwendet synthetische Piper-Audiosignale, kein Mikrofon und keine echten
Sprecher. Seine Treffer und Zeiten sind technische Beobachtungen dieses Laufs,
keine Nutzerstudie und keine allgemeine Erkennungsrate.

## Nachweisgrenzen und Runner-Prüfung

Für jeden Lauf ein neues oder leeres `--output`-Verzeichnis verwenden. Vorhandene Nachweise werden nicht überschrieben. Die drei Testcontainer starten mit den unveränderlichen Image-IDs der inspizierten Quellcontainer. Quellen mit einem reservierten Testcontainernamen werden vor jeder Bereinigung abgewiesen, auch wenn sie über eine ID angesprochen wurden.

`python infrastructure/evaluation/test_runner_guards.py` prüft diese Schutzregeln ohne Docker-Zugriff. Fehlgeschlagene und blockierte Fälle werden sowohl in JSONL als auch in JSON-Arrays erkannt; sie erlauben keinen erfolgreichen Gesamtstatus. Diese Offline-Prüfung ersetzt die Ausführung der isolierten Integrationstests nicht.
