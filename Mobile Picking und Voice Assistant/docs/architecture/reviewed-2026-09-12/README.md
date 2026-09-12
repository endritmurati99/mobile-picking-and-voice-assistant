# Einbindung der vier Abbildungen

Stand: 12.09.2026. Alle Dateien enthalten nur ein TikZ-Bild mit lokalem einfachen Zeilenabstand und Schrift `\small` (11 pt bei der vorhandenen 12-pt-Klasse). Kein `resizebox`, keine neue TikZ-Bibliothek. Die vorhandenen Pakete `tikz`, `setspace`, `arrows.meta` und `positioning` reichen. Aus `thesis/main.tex` mit den folgenden Pfaden einbinden. Captions können redaktionell gekürzt werden, die Einschränkungen müssen im Text erhalten bleiben.

## F1: Anforderungen / Prozessszenario

```latex
\begin{figure}[htbp]
\centering
\input{figures/process.tex}
\caption[Angenommener Referenzprozess und digital unterstützter Zielprozess]{Angenommener Referenzprozess und digital unterstützter Zielprozess. Eigene Darstellung eines vereinfachten Szenarios; kein gemessener Vorher-nachher-Vergleich.}
\label{fig:referenz-zielprozess}
\end{figure}
```

Textbezug: Die Entnahme und Prüfung der Ware bleibt bestehen; verändert wird der Weg der Rückmeldung. Kein belegter Zeitgewinn, keine Behauptung einer empirischen Ist-Aufnahme. Ein Quality Alert ist optional und keine Voraussetzung jeder Pick-Bestätigung.

## F2: Referenzarchitektur

Den alten vollständigen TikZ-Block ersetzen, nicht zusätzlich behalten. Bestehendes Label bleibt erhalten.

```latex
\begin{figure}[htbp]
\centering
\input{figures/architecture.tex}
\caption[Referenzarchitektur mit persistierter Outbox]{Referenzarchitektur mit persistierter Outbox und Dispatcher im Backend. Eigene Darstellung nach Projektcode, Stand \texttt{3c545b6}. Gezeigt ist der Kernumfang; die gemeinsame Speicherung von Alert, Job und Ereignis bezeichnet den Quality-Pfad.}
\label{fig:referenzarchitektur}
\end{figure}
```

Textbezug: Dispatcher liest fällige Ereignisse per Odoo-RPC und meldet Zustellstatus zurück. Der Doppelpfeil „Lease / Status“ steht für diese Aufrufe einschließlich Lesen des gespeicherten Ereignisses. n8n spricht auf dem Rückweg mit FastAPI, nicht unmittelbar mit Odoo. Callback-Annahme und Verarbeitungsergebnis sind zu unterscheiden. Durchgezogen/gestrichelt kennzeichnet hier fachliche Pfade, nicht die technische Aussage, dass Webhooks ohne HTTP-Antwort ablaufen. Voice, lokale Modelle, Reverse Proxy und Deployment sind bewusst außerhalb dieses Ausschnitts.

## F3: Idempotenz und Antwortverlust

```latex
\begin{figure}[htbp]
\centering
\input{figures/confirmation-sequence.tex}
\caption[Bestätigung und Wiederholung nach Antwortverlust]{Bestätigung und bewusste Wiederholung nach Antwortverlust. Eigene Darstellung nach Projektcode, Stand \texttt{3c545b6}. Durchgezogene Pfeile zeigen Aufrufe, gestrichelte Antworten; das Kreuz markiert den Antwortverlust. Nicht gezeichnete Zwischenantworten werden im dargestellten Erfolgsfall vorausgesetzt.}
\label{fig:bestaetigung-antwortverlust}
\end{figure}
```

Textbezug: Das Beispiel setzt erfolgreiche Buchung und Finalisierung voraus. Gleicher Schlüssel, identischer Anfrage-Fingerprint, Endpunkt und Berechtigungsbereich sowie eine noch gültige Reservierung sind Voraussetzung des gezeigten Replay. Eine noch laufende Reservierung und abweichende Daten führen zu Konfliktantworten. Der Client führt keine automatische Offline-Warteschlange aus. Zwischen getrennten RPC-Aufrufen gibt es keine globale Transaktion. Ein Fehler nach bereits erfolgter Buchung, aber vor Finalisierung, bleibt ein gesonderter Fall mit unbekanntem Ausgang. Eine pauschale Exactly-once-Aussage ist aus der Grafik nicht ableitbar.

## F4: Datenmodell für Qualitätsmeldungen

```latex
\begin{figure}[htbp]
\centering
\input{figures/quality-data-model.tex}
\caption[Ausgewählte Datenbezüge der Qualitätserfassung]{Ausgewählte Datenbezüge der Qualitätserfassung. Eigene Darstellung nach Projektcode, Stand \texttt{3c545b6}. Der punktierte Anschluss erläutert Felder desselben Alert-Datensatzes; er bezeichnet keine weitere Entität.}
\label{fig:qualitaetsdatenmodell}
\end{figure}
```

Textbezug: `quality.alert.custom` ist das projektspezifische Custom-Modell, nicht Odoos Enterprise-Modell. Es enthält keinen direkten Fremdschlüssel auf `stock.move.line`. Ein fachlicher Bezug zur Position kann über Kontext beschrieben werden, darf aber nicht als eindeutiger Positions-Fremdschlüssel dargestellt werden. Die gezeigten optionalen Referenzen erlauben unzugeordnete Datensätze; im normalen mobilen Auftragsablauf ist die Position einem konkreten Picking zugeordnet. Fachlicher Bearbeitungsstand und maschineller Auswertungsstatus sind verschiedene Felder. Aufzählung der Auswertungszustände ist keine Behauptung, dass jeder vorhandene Alert bereits einen solchen Wert besitzt.

## Technische Druckprüfung

Prüfdatei `check.tex`, Resultat `check.pdf`; PNG-Seiten `check-1.png` bis `check-4.png`. Dieselbe Klasse, Schrift, A4-Ränder und 1,5-facher äußerer Zeilenabstand wie im Manuskript. Satzbreite 15,5 cm. Unskaliert gemessen:

| Datei | Breite | Höhe |
|---|---:|---:|
| process.tex | 15,05 cm | 6,56 cm |
| architecture.tex | 14,98 cm | 7,93 cm |
| confirmation-sequence.tex | 14,94 cm | 7,97 cm |
| quality-data-model.tex | 14,85 cm | 7,97 cm |

Ein abschließender Gesamtbuild muss die tatsächliche Float-Platzierung und Querverweise im Manuskript prüfen; das ist nicht Teil des isolierten Figurentests.
