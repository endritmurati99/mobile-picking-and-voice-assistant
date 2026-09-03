# NotebookLM-Lernpaket für das Kolloquium

**Stand:** 2026-09-03  
**Ziel:** Ein belegtes, verständliches Lernpaket für alle elf Prüfungsgebiete des Projekts erstellen und als genau 22 Markdown-Quellen in ein neues NotebookLM-Notebook laden.

## Ergebnis

Für jedes Gebiet A bis K entstehen zwei Dateien:

1. ein etwa 10 bis 11 Seiten umfassender Lerntext;
2. ein Fragenkatalog mit 30 realistischen Professorenfragen.

Damit umfasst das Paket genau 22 Markdown-Dateien und 330 Fragen. Eine zusätzliche Framework-Datei wird nicht angelegt. Arbeitsweise, Quellenregeln und Nutzungshinweise werden in die elf Lerntexte aufgenommen; gemeinsame Hinweise stehen vollständig im ersten Lerntext und werden in den übrigen Texten knapp wiederholt.

## Gebiete und Dateipaare

| Nr. | Gebiet | Lerntext | Fragen |
|---:|---|---|---|
| 01 | Gesamtarchitektur | `01-gesamtarchitektur-lerntext.md` | `01-gesamtarchitektur-fragen.md` |
| 02 | PWA und Scanning | `02-pwa-scanning-lerntext.md` | `02-pwa-scanning-fragen.md` |
| 03 | FastAPI und Python | `03-fastapi-python-lerntext.md` | `03-fastapi-python-fragen.md` |
| 04 | Odoo, ORM und PostgreSQL | `04-odoo-orm-postgresql-lerntext.md` | `04-odoo-orm-postgresql-fragen.md` |
| 05 | Claim, Heartbeat und Idempotenz | `05-claim-heartbeat-idempotenz-lerntext.md` | `05-claim-heartbeat-idempotenz-fragen.md` |
| 06 | Docker, Caddy und Netzwerke | `06-docker-caddy-netzwerke-lerntext.md` | `06-docker-caddy-netzwerke-fragen.md` |
| 07 | n8n, Outbox und Ereignisse | `07-n8n-outbox-ereignisse-lerntext.md` | `07-n8n-outbox-ereignisse-fragen.md` |
| 08 | Sprache, lokale KI und Qualitätsprüfung | `08-sprache-ki-qualitaet-lerntext.md` | `08-sprache-ki-qualitaet-fragen.md` |
| 09 | Sicherheit und Fehlerfälle | `09-sicherheit-fehlerfaelle-lerntext.md` | `09-sicherheit-fehlerfaelle-fragen.md` |
| 10 | Tests und Evaluation | `10-tests-evaluation-lerntext.md` | `10-tests-evaluation-fragen.md` |
| 11 | Wissenschaftlicher Beitrag und Reflexion | `11-wissenschaft-reflexion-lerntext.md` | `11-wissenschaft-reflexion-fragen.md` |

## Inhalt der Lerntexte

Jeder Lerntext erklärt das Gebiet von den Grundlagen bis zur konkreten Umsetzung im Projekt. Ein Leser soll ihn ohne zusätzliche mündliche Erklärung verstehen können. Jeder Text enthält:

- Zweck und Einordnung des Gebiets;
- Komponenten und Verantwortlichkeiten;
- vollständige Daten- und Kontrollflüsse;
- Erklärung jedes erstmals verwendeten Fachbegriffs;
- Erklärung genannter APIs, Routen, wichtiger Methoden und Funktionen;
- erfolgreiche Abläufe, Fehlerfälle und Teilzustände;
- Vertrauensgrenzen und Sicherheitsentscheidungen;
- bekannte Schwächen und Grenzen des Prototyps;
- Bezug zur Bachelorarbeit und zur wissenschaftlichen Fragestellung, soweit belegt;
- ein kurzes Glossar;
- Quellen direkt an den fachlichen Aussagen.

Begriffe werden nicht nur umschrieben. Beispielsweise wird ein Reverse Proxy als vorgeschalteter Server erklärt, der Anfragen entgegennimmt und an interne Dienste weiterleitet. Eine API wird als festgelegte Schnittstelle erläutert, über die Programme strukturierte Anfragen und Antworten austauschen. Projektspezifische Funktionsnamen werden zusammen mit Eingaben, Aufgabe, Ergebnis und Aufrufern beschrieben.

## Aufbau der Fragenkataloge

Jede der 30 Fragen pro Gebiet enthält:

1. die realistische Prüfungsfrage;
2. das geprüfte Lernziel;
3. eine ausführliche, belegte Musterantwort;
4. eine mündliche Kurzantwort für etwa 60 bis 90 Sekunden;
5. Erklärungen neu auftretender Fachbegriffe;
6. typische Fehler oder unvollständige Antworten;
7. mindestens eine mögliche Nachfrage des Professors;
8. eine Antwort auf die Nachfrage;
9. die relevanten Quellen.

Die Fragen decken Erinnerung, Verständnis, Ablaufwissen, Anwendung, Fehleranalyse und kritische Reflexion ab. Sie dürfen sich nicht nur durch kleine Wortänderungen unterscheiden.

## Quellen und Wahrheitsregeln

Technische Aussagen werden gegen den aktuellen Projektstand geprüft. Die Rangfolge lautet:

1. aktueller Code, Konfiguration, Tests und reproduzierbare Laufzeitbeobachtung;
2. Bachelorarbeit, Anforderungsunterlagen, Architekturentscheidungen und Messergebnisse;
3. offizielle Dokumentation der eingesetzten Produkte;
4. sonstige Quellen nur, wenn die ersten drei Ebenen nicht ausreichen.

Codequellen werden möglichst mit relativem Pfad, Symbol und Zeile angegeben. Dokumentierte Soll-Architektur und tatsächlich implementierter Stand werden getrennt dargestellt. Nicht belegbare Aussagen werden weggelassen oder ausdrücklich als Schlussfolgerung beziehungsweise offene Frage gekennzeichnet.

## Erstellung mit Subagents

Die Arbeit läuft in mehreren Wellen mit höchstens drei Subagents gleichzeitig. Ein Themenagent erstellt jeweils ein vollständiges Dateipaar. Agenten werden anschließend für weitere Gebiete wiederverwendet, damit die Gesamtzahl normalerweise fünf nicht überschreitet.

Vor dem Schreiben wird ein gemeinsames Muster für Inhalt, Fragen und Quellen festgelegt. Danach gilt für jedes Dateipaar:

1. Quelleninventar für das Gebiet;
2. Entwurf des Lerntexts;
3. Entwurf der 30 Fragen und Antworten;
4. zentrale Prüfung auf Fakten, Abdeckung und Überschneidungen;
5. sprachliche Überarbeitung;
6. abschließende Quellen- und Vollständigkeitskontrolle.

Subagents verändern weder NotebookLM noch Authentifizierungsdaten. Upload und Notebook-Konfiguration bleiben Aufgabe des Hauptagents.

## Humanizer

Das Repository `blader/humanizer` wird als lokale Schreibregel verwendet. Der Humanizer folgt auf die fachliche Prüfung und darf keine Fakten, Zahlen, Pfade, Funktionsnamen, Zitate oder Quellen erfinden oder verändern. Er soll insbesondere stereotype KI-Formulierungen, unnötige Wiederholungen, Werbesprache, künstliche Dreiergruppen und monotone Satzmuster entfernen. Technische Genauigkeit hat Vorrang vor stilistischer Glättung.

## NotebookLM und Authentifizierung

`gemini-notebook-mcp-cli` wird lokal installiert und zunächst nur mit ungefährlichen Lese- und Versionsbefehlen geprüft. Die Installation allein gewährt keinen Kontozugriff. Für `nlm login` wählt der Benutzer sein Google-Konto selbst im geöffneten Browserprofil aus und erledigt gegebenenfalls Passwort oder Mehrfaktor-Anmeldung. Sitzungsdaten werden nicht ausgegeben, kopiert oder in das Projekt geschrieben.

Nach erfolgreicher Anmeldung erstellt der Hauptagent ein neues Notebook. Anschließend werden die 22 geprüften Markdown-Dateien hochgeladen und ihr Verarbeitungsstatus kontrolliert. Das Notebook wird weder öffentlich geteilt noch gelöscht. Die CLI wird nicht als öffentlicher HTTP-Dienst betrieben.

## Lernartefakte in NotebookLM

Nach erfolgreichem Quellenimport werden die Möglichkeiten des Kontos geprüft. Soweit verfügbar, entstehen:

- kapitelbezogene Quizze;
- Lernkarten je Gebiet;
- thematisch gebündelte Audio- beziehungsweise Podcastfassungen;
- eine übergreifende Prüfungssimulation;
- weitere sinnvolle Studio-Artefakte nur, wenn sie einen eigenen Lernnutzen besitzen.

Die 330 belegten Fragen bleiben die maßgebliche Fragensammlung. Automatisch erzeugte NotebookLM-Quizze sind ergänzende Übungen und werden nicht als neue fachliche Quelle behandelt.

## Abnahmekriterien

Die Aufgabe ist abgeschlossen, wenn:

- genau 22 Markdown-Dateien vorhanden sind;
- jeder Lerntext das vereinbarte Gebiet vollständig und verständlich behandelt;
- jeder Fragenkatalog genau 30 unterschiedliche, beantwortete Fragen enthält;
- alle 330 Fragen Quellen besitzen;
- zentrale Fachbegriffe, APIs, Methoden und Funktionen erklärt sind;
- bekannte Schwächen nicht als gelöste Funktionen dargestellt werden;
- die Texte den Humanizer-Prüflauf ohne Informationsverlust durchlaufen haben;
- alle Dateien in einem neuen NotebookLM-Notebook als verarbeitete Quellen sichtbar sind;
- die vereinbarten Lernartefakte erstellt oder kontobedingte Einschränkungen dokumentiert wurden.

## Nicht Bestandteil

- öffentliches Bereitstellen eines NotebookLM- oder MCP-Endpunkts;
- Ändern oder Löschen bestehender Notebooks;
- Teilen des Notebooks mit Dritten;
- Erfinden fehlender Forschungsergebnisse oder Projektnachweise;
- eine zusätzliche Anwendung oder eigene Lernplattform.
