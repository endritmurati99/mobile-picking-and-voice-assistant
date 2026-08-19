# Leitfaden: Handytest der Kommissionier-App

Stand 19. August 2026. Geschrieben für jemanden, der das System zum ersten Mal
auf einem Mobilgerät benutzt — und für die Wiederholung durch andere.

---

## Vorbemerkung: Was hier simuliert wird

**Es gibt kein physisches Lager.** Keine Regale, keine Kartons, keine Ware. Was
in der App als „Regal A-01" erscheint, ist ein Datensatz in einer
Demonstrationsdatenbank.

Der Test ersetzt den Rundgang durch Papier: Der Simulationsbogen
(`simulationsbogen-lager2.pdf`) trägt genau die Barcodes, die im echten Betrieb
am Regal und auf dem Karton kleben würden. Man hält das Handy davor, als hätte
man den Artikel gerade in der Hand. Alles dahinter — Prüfung, Buchung,
Kartonzuordnung, Rückschreiben nach Odoo — läuft echt.

Das ist keine Einschränkung des Tests, sondern seine Bauart: geprüft wird die
Software, nicht die Existenz eines Regals.

---

## Was man braucht

| | |
|---|---|
| Gerät | **Android-Handy mit Chrome.** Siehe Kasten unten. |
| Netz | Handy und Rechner im **selben WLAN**. |
| Papier | `handy-start.pdf` (Startseite mit QR) und `simulationsbogen-lager2.pdf`. Beide bei 100 % auf A4 drucken — oder einfach am Bildschirm anzeigen, das Abscannen vom Monitor funktioniert ebenso. |
| Stack | Muss laufen. Prüfen: `https://localhost/` im Browser am Rechner öffnet die App. |

> **Warum Android und Chrome?**
> Die Barcode-Erkennung nutzt die `BarcodeDetector`-Schnittstelle des Browsers.
> Die gibt es in Chrome unter Android, nicht in Safari auf dem iPhone. Auf einem
> iPhone sieht man das Kamerabild, aber es wird nichts erkannt; dort bleibt nur
> die manuelle Eingabe im Scanner-Fenster. Das ist eine Grenze des Browsers,
> kein Fehler der App — gehört aber in jede Auswertung, die man über den Test
> schreibt.


> **Nicht mehr benutzen:** `cluster-pwa-mobile-start.pdf`, `cluster-pwa-lan-qr.png`
> und `cluster-scan-testbogen.pdf` stammen aus dem Testlauf vom 14./16. August.
> Ihr QR zeigt auf `https://172.31.18.88/` — diese Adresse gibt es nicht mehr —
> und der Scanbogen trägt Artikelnummern aus Lager 1. Sie bleiben nur als
> Nachweis jenes Laufs liegen.

---

## Schritt 1 — Einmalig je Gerät: Zertifikat installieren

Die App läuft über HTTPS mit einem selbst ausgestellten Zertifikat. Ohne
installierte Stammzertifizierungsstelle gibt der Browser weder Kamera noch
Mikrofon frei, und die App lässt sich nicht als App installieren. Ohne diesen
Schritt ist der Test wertlos.

**Weg 1 — über das Netz (schnellster Weg)**

1. Am Handy im Browser öffnen: `https://172.22.147.158/rootCA.crt`
2. Die Zertifikatswarnung erscheint. **Erweitert → Trotzdem fortfahren.**
   Das ist an dieser einen Stelle in Ordnung: heruntergeladen wird nur ein
   öffentliches Zertifikat, kein Schlüssel.
3. Die Datei wird geladen. Dann: **Einstellungen → Sicherheit → Verschlüsselung
   und Anmeldedaten → Zertifikat installieren → CA-Zertifikat** und die
   heruntergeladene Datei auswählen. Android warnt dabei ausdrücklich — das ist
   die normale Warnung für jede selbst installierte Zertifizierungsstelle.

**Weg 2 — über Kabel**

Datei `C:\Users\endri\AppData\Local\mkcert\rootCA.pem` per USB auf das Handy
kopieren, dann wie oben unter Einstellungen installieren. Diesen Weg nehmen,
wenn der Browser die Datei nur anzeigt statt sie zu speichern.

**Prüfen, ob es geklappt hat:** `https://172.22.147.158/` öffnen. Erscheint die
App **ohne** Warnung, ist alles richtig. Erscheint weiter eine Warnung, wurde das
Zertifikat nicht als Zertifizierungsstelle installiert, sondern nur abgelegt.

> **Tipp für wiederholte Tests:** Das Zertifikat enthält auch die
> Tailscale-Adresse `100.87.184.52`. Wer Tailscale auf dem Handy installiert
> hat, benutzt besser `https://100.87.184.52/` — diese Adresse bleibt gleich,
> egal in welchem Netz Rechner und Handy stecken, und übersteht jeden
> WLAN-Wechsel. Dann entfällt das Neu-Ausstellen des Zertifikats komplett.
>
> Das Zertifikat gilt bis 19. November 2028 und enthält neben der WLAN-Adresse
> auch die Kabel- und die Tailscale-Adresse. Wechselt das WLAN und damit die
> IP-Adresse des Rechners, muss es neu ausgestellt werden:
> `bash infrastructure/scripts/setup-certs.sh <DNS-Name> <neue-IP>`.
> Die Zertifizierungsstelle bleibt dabei dieselbe — auf dem Handy ist dann
> **nichts** neu zu installieren.

---

## Schritt 2 — Starten

1. Auf `handy-start.pdf` den **QR-Code** mit der Handykamera scannen. Er führt
   direkt auf `https://172.22.147.158/`.
2. Anmelden: Benutzer `lena.lager`, Passwort `admin`.
3. Lager wählen: **Lager 2**.

> **Warum Lager 2?** In Lager 1 hängen zurzeit zwölf der vierzehn offenen
> Aufträge in älteren Sammelaufträgen aus früheren Testläufen. Wer schon in
> einem Sammelauftrag steckt, wird nicht mehr vorgeschlagen — deshalb zeigt
> Lager 1 keine Cluster an. In Lager 2 stehen vier Vorschläge bereit.
> Die KI-Bildbewertung dagegen gibt es nur in Lager 1.

**Als App installieren** (optional, macht den Eindruck vollständig): im
Chrome-Menü „Zum Startbildschirm hinzufügen". Danach startet die App ohne
Browserleiste im Vollbild.

---

## Schritt 3 — Der einfache Fall: ein Auftrag, ohne Scannen

Diese Runde beantwortet die Frage „Muss ich eigentlich scannen?" — nein, muss
man nicht.

1. In der Auftragsliste einen Auftrag antippen.
2. Bei jeder Position **„Bestätigen"** antippen.

Die App bucht dann gegen den hinterlegten Soll-Barcode, so als hätte man ihn
gescannt. Der Scan ist eine **Prüfung**, keine Pflicht: Er verhindert den
falschen Griff, aber er ist nicht der Weg, auf dem gebucht wird.

Wer eine Position mit Seriennummer erwischt, wird nach der Nummer gefragt — das
ist gewollt und lässt sich nicht überspringen.

Ergebnis: Der Auftrag steht danach in Odoo als erledigt. Damit ist der Grundweg
durch — ohne Papier, ohne Kamera.

---

## Schritt 4 — Der interessante Fall: Sammelauftrag mit Scannen

Hier liegt der eigentliche Nutzen: mehrere Aufträge in einem Rundgang, jeder
Griff auf den richtigen Karton verteilt.

1. In der App auf **Cluster** wechseln.
2. Den Vorschlag mit **drei Aufträgen und acht Positionen** wählen
   (`WH/OUT/00022`, `WH/OUT/00025`, `WH/OUT/00030`) und starten.
   In diesem Moment vergibt das System die Kartonnamen — genau die, die auf dem
   Simulationsbogen stehen.
3. Den Rundgang abarbeiten. Für jeden der vier Halte:
   - Auf **Scannen** tippen, das Handy auf den **Artikel-Barcode** des Bogens
     halten. Die App meldet „Artikel geprüft".
   - Dann fragt sie nach dem Zielkarton. Entweder das **Kartonetikett** auf dem
     Bogen scannen — oder den farbigen Karton-Knopf antippen. Beides ist gültig;
     der Scan ist die strengere Variante.
   - Bei den Halten A-01 und A-02 wiederholt sich das je Karton, weil derselbe
     Artikel auf alle drei Aufträge verteilt wird.
4. Am Ende **Abschließen**.

**Der Negativtest gehört dazu.** Auf dem Bogen stehen zwei Köder — echte Artikel
aus Lager 2, die aber nicht zu diesem Sammelauftrag gehören. Einen davon
irgendwann zwischendurch scannen. Erwartet: **„Falscher Artikel. Es wurde nichts
gebucht."** Passiert das nicht, ist das ein Befund und der Test ist gescheitert —
nicht bestanden.

---

## Schritt 5 — Was danach zu prüfen ist

| Prüfung | Wo |
|---|---|
| Drei Aufträge stehen auf erledigt | Odoo Lager 2, `http://localhost:8070` |
| Acht Positionen sind gebucht | ebenda, in den Aufträgen |
| Beide Köder wurden abgewiesen | am Handy beobachtet |
| Kein Abbruch beim Kartonwechsel | am Handy beobachtet |

---

## Wiederholung: der Test verbraucht seine Daten

Ein abgeschlossener Auftrag ist abgeschlossen. Für den nächsten Durchlauf
braucht es frische Aufträge:

```bash
python infrastructure/scripts/generate-pickings.py \
  --url http://localhost:8070 --db lager2_o19 \
  --user admin --api-key <ODOO_API_KEY aus der .env> --count 10
```

Danach den Simulationsbogen **neu erzeugen** — die Barcodes und vor allem die
Kartonnamen gelten nur für genau einen Sammelauftrag:

```bash
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" exec -i mobilepickingundvoiceassistant-odoo-1 python3 - \
  < infrastructure/scripts/generate-demo-sheets.py
```

Wer den alten Bogen weiterbenutzt, scannt Kartonetiketten, die es nicht mehr
gibt, und wundert sich über „Falscher Karton".

---

## Wenn etwas nicht geht

| Beobachtung | Ursache | Abhilfe |
|---|---|---|
| Seite lädt am Handy gar nicht | anderes WLAN, oder die Windows-Firewall blockt Port 443 | Handy-WLAN prüfen; am Rechner `https://localhost/` gegenprüfen |
| Zertifikatswarnung bleibt | CA nicht als Zertifizierungsstelle installiert | Schritt 1 wiederholen, Weg 2 |
| Kamera startet nicht | HTTPS nicht vertraut, oder Kamerarecht verweigert | Zertifikat prüfen, dann in den Website-Einstellungen die Kamera freigeben |
| Kamerabild da, aber nichts wird erkannt | iPhone, oder ein Browser ohne `BarcodeDetector` | Android mit Chrome benutzen, oder Barcode manuell eintippen |
| „Für diesen Artikel fehlt der Produktbarcode" | der Artikel hat in Odoo keinen Barcode | einen anderen Halt nehmen; in Lager 2 betrifft das keinen der vier |
| „Falscher Karton" bei richtigem Etikett | Bogen stammt aus einem älteren Sammelauftrag | Bogen neu erzeugen |
| Cluster-Ansicht ist leer | alle Aufträge hängen schon in Sammelaufträgen | anderes Lager wählen oder Aufträge nachlegen |

---

## Was dieser Test belegt — und was nicht

**Belegt:** dass die Kette vom Griff am Regal bis zur Buchung in Odoo
funktioniert, dass ein falscher Artikel erkannt wird, dass die Verteilung auf
mehrere Kartons stimmt, und dass all das auf einem Mobilgerät im WLAN bedienbar
ist.

**Nicht belegt:** Erkennungsraten unter realen Lagerbedingungen — schlechtes
Licht, beschädigte Etiketten, Handschuhe, Zeitdruck. Ein Barcode vom sauberen
Ausdruck ist der einfachste Fall, den es gibt. Wer aus diesem Test eine Aussage
über die Praxistauglichkeit ableitet, muss diese Grenze mitschreiben.
