# Bedienanleitung — Kommissionieren mit dem Handy

Lager 1. Stand 19. August 2026.

---

## 1. Einmalig je Gerät: Zertifikat installieren

Ohne dieses Zertifikat gibt der Browser die Kamera nicht frei, und ohne Kamera
kein Scannen.

1. Am Handy `https://172.22.147.158/rootCA.crt` öffnen.
2. Die Sicherheitsabfrage bestätigen (**Erweitert → Trotzdem fortfahren**).
3. Die geladene Datei als Zertifizierungsstelle installieren:
   - **Android:** Einstellungen → Sicherheit → Verschlüsselung und Anmeldedaten
     → Zertifikat installieren → CA-Zertifikat
   - **iPhone:** Einstellungen → Profil geladen → Installieren, danach
     Einstellungen → Allgemein → Info → Zertifikatsvertrauenseinstellungen →
     den Eintrag aktivieren. **Der zweite Schritt wird oft vergessen und ist
     zwingend.**

Fertig, wenn `https://172.22.147.158/` ohne Warnung öffnet.

---

## 2. Anmelden

1. Den QR-Code auf dem Startblatt scannen — er öffnet die App.
2. Benutzer `lena.lager`, Passwort `admin`.
3. Lager: **Lager 1**.

Wer die App dauerhaft nutzt, fügt sie über das Browsermenü zum Startbildschirm
hinzu. Sie startet dann im Vollbild ohne Adressleiste.

---

## 3. Einzelnen Auftrag abarbeiten

1. In der Auftragsliste den Auftrag antippen.
2. Die App führt Position für Position. Zu jeder Position stehen Artikel,
   Lagerplatz und Menge auf dem Bildschirm.
3. Zwei Wege, eine Position zu buchen:
   - **Scannen** antippen und den Artikelcode vor die Kamera halten. Die App
     vergleicht mit dem Sollartikel und bucht bei Übereinstimmung.
   - **Bestätigen** antippen. Bucht ohne Prüfung.

   Scannen ist der sichere Weg: es verhindert den falschen Griff. Bestätigen ist
   der schnelle Weg, wenn der Artikel eindeutig ist.
4. Verlangt eine Position eine **Seriennummer**, muss sie eingegeben werden.
   Dieser Schritt lässt sich nicht überspringen.
5. Nach der letzten Position schließt die App den Auftrag ab.

---

## 4. Sammelauftrag: vier Aufträge in einem Rundgang

Statt vier Mal durch das Lager zu laufen, wird jeder Artikel einmal geholt und
gleich auf die vier Kartons verteilt.

### Vorbereiten

1. In der App auf **Cluster** wechseln.
2. Die vier Aufträge auswählen: **WH/OUT/00047, 00051, 00053, 00054**.
3. **Starten.** Die App vergibt jetzt die Kartonnummern — Karton 1 bis 4, in
   dieser Reihenfolge den vier Aufträgen zugeordnet. Die Etiketten dazu stehen
   auf Seite 2 des Kommissionierbogens.

### Der Rundgang

Fünf Halte, elf Positionen. Die App führt in dieser Reihenfolge:

| Halt | Lagerplatz | Artikel | Menge |
|---|---|---|---|
| 1 | Regal B-01 | Brick 2x2 blau | 2 in Karton 3 |
| 2 | Regal B-02 | Brick 2x2 dot blau Propeller | je 1 in Karton 1, 2 und 4 |
| 3 | Regal C-01 | Flower hellblau | 1 in Karton 3 |
| 4 | Regal C-02 | Brick 2x2 weiß | je 1 in Karton 1, 2 und 4 |
| 5 | Regal C-02 | Brick Round 2x2x2 weiß | je 2 in Karton 1, 2 und 4 |

An jedem Halt:

1. **Artikelcode scannen.** Die App meldet „Artikel geprüft".
2. **Zielkarton angeben** — entweder das Kartonetikett scannen oder den farbigen
   Kartonknopf antippen.
3. Sind mehrere Kartons genannt, wiederholt sich Schritt 2 je Karton. Der
   Artikel bleibt dabei geprüft; er muss nicht erneut gescannt werden.

Nach dem letzten Halt **Abschließen**. Alle vier Aufträge sind damit erledigt.

---

## 5. Wenn etwas nicht stimmt

| Meldung der App | Was sie bedeutet | Was zu tun ist |
|---|---|---|
| „Falscher Artikel. Es wurde nichts gebucht." | Der gescannte Code gehört nicht zu diesem Halt | Artikel zurücklegen, richtigen holen. Es ist nichts passiert. |
| „Falscher Karton. Es wurde nichts gebucht." | Der Kartoncode passt nicht zur Position | Richtigen Karton scannen |
| „Charge oder Serie bitte über Manuell bestätigen erfassen." | Die Position braucht eine Seriennummer | Über **Manuell bestätigen** die Nummer eingeben |
| „Für diesen Artikel fehlt der Produktbarcode." | Der Artikel hat im System keinen Code | Position über **Bestätigen** buchen und dem Lagerleiter melden |
| „Odoo ist momentan nicht erreichbar." | Verbindung zum Warenwirtschaftssystem gestört | Kurz warten, erneut versuchen. Nicht gebuchte Positionen bleiben offen. |

**Wichtig:** Bricht die Verbindung mitten im Rundgang ab, gehen bereits gebuchte
Positionen nicht verloren — sie stehen im System. Die abgebrochene Position muss
wiederholt werden.

---

## 6. Kontrolle nach dem Rundgang

Erwartet nach dem Sammelauftrag oben:

- 11 Positionen gebucht
- vier Aufträge auf erledigt: WH/OUT/00047, 00051, 00053, 00054
- vier gefüllte Kartons, jeder einem Auftrag zugeordnet

Nachsehen lässt sich das in Odoo unter `http://localhost:8069` in der
Auftragsübersicht.

---

## 7. Wenn das Gerät nicht mitspielt

| Beobachtung | Abhilfe |
|---|---|
| Seite lädt nicht | Handy im selben WLAN? Adresse `https://172.22.147.158/` genau so eingegeben? |
| Zertifikatswarnung bleibt | Schritt 1 wiederholen; beim iPhone den Vertrauensschalter nicht vergessen |
| Kamera startet nicht | Im Browser unter Website-Einstellungen die Kamera freigeben |
| Code wird nicht erkannt | Abstand ändern, Blendung vermeiden — oder den Code im Scanner-Fenster von Hand eingeben |
| Cluster-Ansicht ist leer | Alle Aufträge stecken bereits in einem Sammelauftrag. Beim Lagerleiter melden. |

---

## 8. Für den Lagerleiter: neue Aufträge und neuer Bogen

Abgeschlossene Aufträge sind verbraucht. Für den nächsten Durchlauf:

```bash
python infrastructure/scripts/generate-pickings.py \
  --url http://localhost:8069 --db masterfischer_o19 \
  --user admin --api-key <ODOO_API_KEY aus der .env> --count 10
```

Danach im Kopf von `infrastructure/scripts/generate-demo-sheets.py` die
Auftragsnummern, Artikel und Kartonnamen anpassen und den Bogen neu erzeugen:

```bash
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" exec -i mobilepickingundvoiceassistant-odoo-1 python3 - \
  --sheet both --output-dir /tmp/bogen \
  < infrastructure/scripts/generate-demo-sheets.py
```

Die Kartonnamen folgen dem Muster `CLUSTER-B{Nummer}/{Auftrag}`, wobei die
Nummer der aufsteigenden Auftrags-ID folgt. Ein Bogen aus einem früheren
Sammelauftrag führt zu „Falscher Karton" — dann ist der Bogen veraltet, nicht
das Gerät.
