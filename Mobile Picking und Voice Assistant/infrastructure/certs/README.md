# Zertifikate

Dieser Ordner enthält die mkcert-Zertifikate für lokales HTTPS.
Die Dateien werden NICHT committed (.gitignore).

## Generierung

```bash
bash infrastructure/scripts/setup-certs.sh <LAN-IP>
```

## CA auf mobile Geräte übertragen

CA-Datei finden: `mkcert -CAROOT`

### iOS
1. CA-Datei per AirDrop/Mail senden
2. Profil installieren (Einstellungen → Allgemein → VPN & Geräteverwaltung)
3. Einstellungen → Allgemein → Info → Zertifikatsvertrauenseinstellungen → aktivieren

### Android
1. Einstellungen → Sicherheit → Weitere Sicherheitseinstellungen
2. Von Gerätespeicher installieren → CA-Zertifikat
3. Datei auswählen
