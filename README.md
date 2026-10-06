# Metzgertheke – Online-Version (kostenlos)

Öffentliche Web-App (PWA) mit Wochenangeboten + Mittagstisch regionaler
Metzgereien. Läuft komplett kostenlos: Hosting über **GitHub Pages**, das
wöchentliche Auslesen der Metzger-Websites/Bilder per **Gemini** über
**GitHub Actions**. Keine eigene Hardware/Server nötig. Unabhängig vom Raspberry Pi.

## Struktur
- `index.html`, `manifest.json`, Icons, `logos/` – die App (statisch)
- `data.json`, `mittagstisch.json` – die Daten (werden automatisch aktualisiert)
- `tools/scrape.py` – liest die Angebote per Gemini aus (Portierung der HA-Automation)
- `.github/workflows/update.yml` – Zeitplan (Mo) + manueller Start

## Einmalige Einrichtung (im Browser, GitHub ist eingeloggt)
1. **Secret setzen:** Repo → *Settings* → *Secrets and variables* → *Actions*
   → *New repository secret* → Name `GEMINI_API_KEY`, Wert = dein Gemini-API-Key.
   (optional: unter *Variables* `GEMINI_MODEL` setzen, z. B. `gemini-2.0-flash`.)
2. **GitHub Pages aktivieren:** Repo → *Settings* → *Pages* →
   *Source: Deploy from a branch* → Branch `main` / `/root` → *Save*.
   Die Seite erscheint dann unter `https://<user>.github.io/<repo>/`.
3. **Erstes Update starten:** Repo → *Actions* → „Angebote aktualisieren“
   → *Run workflow*. Danach läuft es jeden Montag automatisch.

## Android-App (APK)
Die App ist eine PWA → mit **pwabuilder.com** (URL eingeben) oder **Bubblewrap**
eine signierte APK erzeugen. Direkt verteilbar (Sideload) oder via Play Store.

## iOS
Auf dem iPhone über **„Zum Home-Bildschirm hinzufügen“** installierbar (gratis).
Eine echte App-Store-App bräuchte ein Apple-Developer-Konto (99 $/Jahr) + macOS/Cloud-Mac.
