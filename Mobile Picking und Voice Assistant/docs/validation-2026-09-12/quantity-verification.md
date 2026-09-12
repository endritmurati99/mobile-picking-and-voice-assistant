# Versionierter Nachtrag zur Mengenvalidierung, 12.09.2026

Die Anwendung aus Commit `3c545b6` wurde auf einem separaten Revisionsbranch geprüft. Der historische Odoo-Negativbefund bleibt unverändert: Eine negative Menge wurde damals akzeptiert.

Der aus dem lokalen Nachtrag vom 11.09. übernommene Test wurde zuerst ohne Schemafix ausgeführt: drei Testgruppen, 20 fehlgeschlagene ungültige Modell-/HTTP-Unterfälle. Anschließend wurden beide Request-Modelle auf endliche, nichtnegative Mengen begrenzt. Null als vorhandener Standardwert und positive Teilmengen bleiben auf Modellebene zulässig.

Codeänderung im Code-Commit `eee996b`: `ConfirmLineRequest` und `ClusterConfirmRequest` verwenden `Field(default=0, ge=0, allow_inf_nan=False)`.

Nach der Änderung: drei Testgruppen bestanden. Der Lauf dauerte 0,060 Sekunden; dies ist Testlaufzeit und keine Anwendungslatenz. Getestet wurden gültige Modellwerte, ungültige Modellwerte und die Abweisung ungültiger Mengen über beide tatsächlichen FastAPI-Router. Dependency-Overrides ersetzen Datenbank-/Authentifizierungszugriffe.

```powershell
$env:RUNTIME_PROFILE='test'
uv run --python 3.12 --with-requirements 'Mobile Picking und Voice Assistant/backend/requirements.txt' python 'Mobile Picking und Voice Assistant/infrastructure/scripts/test-confirm-quantity.py'
```

Dieser Befund belegt die Request-Validierung. Er belegt weder die fachliche Odoo-Buchung noch eine Nutzerwirkung. Die Rohprotokolle des lokalen Vorher-/Nachher-Laufs liegen im privaten Revisionsordner; der öffentliche Nachweis verwendet diese bereinigte Zusammenfassung.

Zusätzlich wurden die vorhandenen Voice-Backend-, Voice-Actions- und Voice-Frontend-Regressionen erfolgreich ausgeführt. Die beiden JavaScript-Skripte benötigen `node --experimental-vm-modules`; ein erster Aufruf ohne diesen Schalter scheiterte an der Testumgebung und wurde mit dem erforderlichen Schalter korrigiert. Diese Tests sind keine neue Mikrofon-/Spracherkennungsstudie.
