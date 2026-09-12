# Lesefassung der Architektur

Diese Lesefassung führt in die Architektur des Mobile Picking und Voice Assistant ein. Sie richtet sich an Personen, die zuerst den Arbeitsablauf und die Verantwortlichkeiten verstehen möchten. Die drei Figuren verdichten vorhandene technische Excalidraw-Ebenen; sie ersetzen diese nicht.

| Lesefigur | Ausgangsebene | Dateien | Aussage |
| --- | --- | --- | --- |
| Systemlandkarte | [Ebene 1: Systemlandkarte](../ebene-1-systemlandkarte.md) | [Quelle](./systemlandkarte.excalidraw) · [SVG](./systemlandkarte.svg) · [PDF](./systemlandkarte.pdf) | Wer arbeitet mit dem System, welche Komponenten sind beteiligt und wo liegt die fachliche Datenführung? |
| Auftragsablauf | [Ebene 2: PWA und normaler Auftrag](../ebene-2-pwa-normaler-auftrag.md) | [Quelle](./auftragsablauf.excalidraw) · [SVG](./auftragsablauf.svg) · [PDF](./auftragsablauf.pdf) | Wie wird ein Auftrag ausgewählt, bestätigt und in Odoo abgeschlossen? |
| Qualitätsmeldung | [Ebene 5: Quality, n8n sowie Text- und Bild-KI](../ebene-5-quality-n8n-ki.md) | [Quelle](./qualitaetsmeldung.excalidraw) · [SVG](./qualitaetsmeldung.svg) · [PDF](./qualitaetsmeldung.pdf) | Wie wird eine Auffälligkeit mit Kontext gespeichert und anschließend weiterverarbeitet? |

Für jede Lesefigur gehören drei gleichnamige Dateien zusammen:

- `.excalidraw` ist die editierbare Quelle.
- `.svg` ist die skalierbare Web- und Dokumentationsgrafik.
- `.pdf` ist die Druckfassung derselben freigegebenen SVG.

Die Dateien werden als `systemlandkarte`, `auftragsablauf` und `qualitaetsmeldung` benannt. Die Links werden vollständig, sobald die drei Excalidraw-, SVG- und PDF-Dateien in diesem Verzeichnis vorliegen.

## Lesereihenfolge

1. Die Systemlandkarte erklärt die Rollen: Die PWA führt durch den Arbeitsschritt, FastAPI prüft und vermittelt, Odoo führt Aufträge und Bestände, und n8n verarbeitet spätere Folgeaufgaben.
2. Der Auftragsablauf zeigt die unmittelbare Lagerarbeit von der Auswahl bis zur bestätigten Rückschreibung. Er zeigt keine vollständige technische Fehleranalyse.
3. Die Qualitätsmeldung zeigt, dass Alert und Anhänge zunächst in Odoo gespeichert werden. Die spätere Automatisierung bleibt ein getrennter Folgeprozess.

Für Schnittstellen, Datenmodelle, Fehlerfälle, Rechte, Voice und Cluster-Picking bleiben die technischen Originalebenen maßgeblich. Die frühere TikZ-Fassung `reviewed-2026-09-12` bleibt eine historische Alternative und wird durch diese Lesefassung weder überschrieben noch als aktueller Quellstand behandelt.

## Reproduzierbarer Export

1. Die zugehörige `.excalidraw`-Datei in Excalidraw öffnen und nur diese Quelle bearbeiten.
2. Die freigegebene Zeichnung nativ als SVG exportieren. SVG wird nicht durch einen Screenshot ersetzt.
3. Die PDF-Datei aus genau dieser freigegebenen SVG erzeugen. Vor der Veröffentlichung prüfen, dass Titel, Beschriftungen, Pfeilspitzen und Ränder bei der vorgesehenen Seitenbreite lesbar sind.
4. Die drei Formate gemeinsam prüfen: Inhalt und Versionsstand müssen übereinstimmen; die `.excalidraw`-Datei bleibt die bearbeitbare Quelle.

Die Lesefiguren enthalten keine privaten Thesis-Texte, PDF-Manuskripte, Evaluationsdaten oder interne Review-Berichte.
