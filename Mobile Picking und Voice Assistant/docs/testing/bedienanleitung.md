# Kommissionieren mit dem Handy

## Start

1. Die aktuelle Adresse der PWA im Browser öffnen.
2. Mit dem bereitgestellten Odoo-Zugang anmelden.
3. Den richtigen Standort auswählen: **Lager 1** oder **Lager 2**.

Die Auswahl bestimmt die sichtbaren Aufträge und Bestände. Beide Standorte
bleiben getrennt.

## Auftrag bearbeiten

1. Auftrag öffnen.
2. Artikel, Lagerplatz und Menge prüfen.
3. Den Artikel mit Scanner oder Kamera erfassen. Wenn kein Scan möglich ist,
   kann die Position bewusst manuell bestätigt werden.
4. Seriennummern eingeben, wenn die App danach fragt.
5. Nach der letzten Position den Auftrag abschließen.

Bei einer falschen Erfassung wird nichts gebucht. Den richtigen Artikel oder
Karton wählen und erneut scannen.

## Sammelauftrag

In der Cluster-Ansicht werden passende Aufträge gemeinsam vorbereitet. Die App
führt durch die Stopps und zeigt, in welchen Karton die Ware gehört. Erst nach
der letzten Bestätigung wird der Sammelauftrag abgeschlossen.

## Wenn etwas nicht funktioniert

| Beobachtung | Nächster Schritt |
| --- | --- |
| Die App lädt nicht | Verbindung prüfen und die aktuelle PWA-Adresse erneut öffnen. |
| Kamera bleibt zu | Kamera im Browser erlauben. |
| Artikel oder Karton passt nicht | Nicht bestätigen; richtigen Code scannen. |
| Verbindung bricht ab | Kurz warten und den Auftrag neu laden. Bereits bestätigte Positionen bleiben im System. |

Aktuelle Ansichten der PWA und der beiden Odoo-Standorte stehen im
[Projekt-README](../../README.md#screenshots-vom-27-august-2026).
