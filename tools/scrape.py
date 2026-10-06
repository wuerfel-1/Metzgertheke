#!/usr/bin/env python3
"""Metzgertheke – Online-Scraper (Portierung der Home-Assistant-Automation).

Liest die Wochenangebote und den Mittagstisch mehrerer Metzgereien per Gemini
aus (Website-Text + Bild-OCR) und schreibt data.json / mittagstisch.json im
selben Format wie die bisherige Pi-Lösung. Laeuft kostenlos in GitHub Actions.

Benoetigt:  GEMINI_API_KEY  (Secret)        optional: GEMINI_MODEL
"""
import os, re, sys, json, time
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Berlin")
except Exception:
    TZ = None
import requests
from google import genai
from google.genai import types

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not API_KEY:
    sys.exit("FEHLER: GEMINI_API_KEY nicht gesetzt.")
client = genai.Client(api_key=API_KEY)
BASE_SLEEP = float(os.environ.get("BASE_SLEEP", "8"))  # Abstand zwischen KI-Aufrufen

def pick_model():
    """Nimmt GEMINI_MODEL falls gesetzt, sonst automatisch ein schlankes
    flash-Modell aus der Liste der verfuegbaren Modelle (hoeheres Gratis-Limit,
    weniger Auslastung). Vermeidet erneute Ausfaelle bei Modell-Umbenennungen."""
    want = os.environ.get("GEMINI_MODEL", "").strip()
    if want:
        return want
    try:
        names = []
        for m in client.models.list():
            acts = list(getattr(m, "supported_actions", None)
                        or getattr(m, "supported_generation_methods", None) or [])
            if "generateContent" in acts:
                names.append(m.name.split("/")[-1])
    except Exception as e:
        print("Modell-Liste fehlgeschlagen (%s) -> gemini-flash-latest" % e)
        return "gemini-flash-latest"
    def bad(n):
        return any(b in n for b in ("exp", "thinking", "image", "audio", "tts",
                                    "embedding", "learnlm", "vision-", "preview"))
    def score(n):
        s = 0
        if "lite" in n: s += 6
        if "latest" in n: s += 3
        if bad(n): s -= 50
        return s
    flash = [n for n in names if "flash" in n and not bad(n)] or \
            [n for n in names if "flash" in n]
    flash.sort(key=score, reverse=True)
    chosen = flash[0] if flash else "gemini-flash-latest"
    print("Auto-Modell: %s   (flash-Modelle: %s)" % (chosen, ", ".join(flash[:8])))
    return chosen

MODEL = pick_model()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root

# Reihenfolge wie in der HA-Automation (Woerlein direkt nach Wettelsheim)
ORDER = ["Geißelmeier Treuchtlingen", "Geißelmeier Wettelsheim", "Wörlein Treuchtlingen",
         "Zum Schneck (Suffersheim)", "Völk Weißenburg", "Struller Weißenburg"]

# ---------------------------------------------------------------- Helpers ----
def http_get(url, timeout=25):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r

def page_text(url):
    html = http_get(url).text
    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?</style>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = re.sub(r"\s+", " ", html)
    return html.strip()[:12000]

_RETRY = ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "overloaded")

def _retry_wait(msg, fallback):
    m = re.search(r"retry in (\d+(?:\.\d+)?)", msg or "")
    if m:
        return min(35.0, float(m.group(1)) + 1.0)
    return fallback

def generate(contents, tries=5):
    delay = 12.0
    for attempt in range(tries):
        try:
            return client.models.generate_content(model=MODEL, contents=contents)
        except Exception as e:
            msg = str(e)
            if attempt < tries - 1 and any(s in msg for s in _RETRY):
                wait = _retry_wait(msg, delay)
                print("    (Limit/Auslastung – warte %.0fs, Versuch %d/%d)" % (wait, attempt + 1, tries))
                time.sleep(wait)
                delay = min(35.0, delay * 1.4)
                continue
            raise

def ai_text(prompt):
    return (generate(prompt).text or "").strip()

def ai_image(prompt, img_bytes, mime):
    resp = generate([prompt, types.Part.from_bytes(data=img_bytes, mime_type=mime)])
    return (resp.text or "").strip()

def parse_price(s):
    m = re.search(r"[0-9][0-9.,]*[0-9]|[0-9]", (s or "").replace("€", ""))
    if not m:
        return None
    num = m.group(0)
    if "," in num and "." in num:
        num = num.replace(".", "").replace(",", ".")
    elif "," in num:
        num = num.replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None

def parse_block(block, lunch=False):
    items = []
    for raw in (block or "").split("\n"):
        l = raw.strip()
        if not l or l[0] not in "•-*":
            continue
        body = l[1:].strip()
        name, sep, price = body.rpartition(":")
        if not sep:
            name, price = body, ""
        name = name.strip()
        val = parse_price(price)
        if val is not None:
            items.append([name, val])
        elif lunch:
            note = price.strip()
            if note and note.lower() not in ("", "-", "—", "keine"):
                name = name + " · " + note
            items.append([name, None])
    return items

def add(shops, title, block, lunch=False):
    if not block or block.lower() == "keine":
        print("  - %s: keine" % title); return
    items = parse_block(block, lunch)
    if items:
        shops.append({"title": title, "items": items})
        print("  + %s: %d Positionen" % (title, len(items)))
    else:
        print("  - %s: nichts erkannt" % title)

def order_shops(shops):
    idx = {t: i for i, t in enumerate(ORDER)}
    return sorted(shops, key=lambda s: idx.get(s["title"], 999))

def find_image(page_url, pattern, strip_thumb=False):
    html = http_get(page_url).text
    hits = re.findall(pattern, html)
    if not hits:
        return ""
    u = hits[0]
    if strip_thumb:
        u = re.sub(r"-\d+x\d+(\.[a-zA-Z]+)$", r"\1", u)
    return u

def img_bytes(url):
    r = http_get(url)
    mime = r.headers.get("Content-Type", "").split(";")[0].strip() or "image/jpeg"
    if "image" not in mime:
        mime = "image/png" if url.lower().endswith(".png") else "image/jpeg"
    return r.content, mime

# --------------------------------------------------------------- Prompts -----
P_OFFER_TXT = ("Du bekommst den Textinhalt der Angebotsseite einer Metzgerei oder eines "
    "Gasthauses. Extrahiere NUR aktuelle Fleisch-, Wurst- und Lebensmittel-Wochenangebote "
    "MIT Preis. Ausgabe pro Zeile exakt im Format '• Produkt: Preis' (Preis inklusive "
    "€-Zeichen). Keine Mittagsmenues, keine Oeffnungszeiten, keine Navigation, keine "
    "Telefonnummern. Hoechstens 15 Zeilen. Wenn keine Angebote mit Preis erkennbar sind, "
    "antworte exakt: keine . Seitentext: %s")
P_OFFER_IMG_VOELK = ("Lies aus diesem Angebotsbild einer Metzgerei die Fleisch-/Wurst-/"
    "Lebensmittel-Angebote MIT Preis. Ausgabe pro Zeile exakt '• Produkt: Preis' (mit €). "
    "Keine Oeffnungszeiten, keine Navigation. Wenn keine Angebote mit Preis erkennbar: "
    "antworte exakt: keine")
P_OFFER_IMG_STRULLER = ("Lies aus diesem Angebotsbild einer Metzgerei die Fleisch-/Wurst-/"
    "Lebensmittel-Wochenangebote MIT Preis. Ausgabe pro Zeile exakt '• Produkt: Preis' "
    "(mit €). Keine Mittagsmenues/Mittagstisch, keine Oeffnungszeiten, keine Navigation. "
    "Wenn keine Angebote mit Preis erkennbar: antworte exakt: keine")
P_OFFER_IMG_WOERLEIN = ("Lies aus diesem Angebotsbild einer Metzgerei die Fleisch-/Wurst-/"
    "Lebensmittel-Wochenangebote MIT Preis. Ausgabe pro Zeile exakt '• Produkt: Preis' "
    "(mit €). Preise sind je 100g. Keine Mittagsmenues/Mittagstisch, keine Oeffnungszeiten, "
    "keine Navigation, keine Slogans. Wenn keine Angebote mit Preis erkennbar: antworte "
    "exakt: keine")
P_LUNCH_TXT = ("Du bekommst den Textinhalt einer Metzgerei-/Gasthaus-Seite. Extrahiere NUR "
    "den woechentlichen MITTAGSTISCH bzw. das MITTAGSMENUE (Tagesgerichte Montag bis "
    "Samstag) MIT Preis. Ausgabe pro Gericht exakt '• <Tag> · <Gericht>: <Preis>'. <Tag> "
    "als Mo, Di, Mi, Do, Fr oder Sa. Preis inklusive €-Zeichen. Hat ein Gericht keinen "
    "festen Preis (z.B. nach Gewicht), schreibe als Preis: nach Gewicht. Keine "
    "Wochenangebote/Theken-Preise je 100g, keine Oeffnungszeiten, keine Navigation. Wenn "
    "kein Mittagstisch mit Gerichten erkennbar ist, antworte exakt: keine . Seitentext: %s")
P_LUNCH_IMG = ("Lies aus diesem Wochen-Menueplan-Bild die Tagesgerichte (Montag bis Samstag) "
    "MIT Preis. Ausgabe pro Gericht exakt '• <Tag> · <Gericht>: <Preis>'. <Tag> als Mo, Di, "
    "Mi, Do, Fr oder Sa. Preis inklusive €-Zeichen. Mehrere Gerichte pro Tag = je eine "
    "Zeile. Ohne festen Preis schreibe als Preis: nach Gewicht. Keine Oeffnungszeiten, keine "
    "Adresse, keine Slogans. Wenn nichts erkennbar: antworte exakt: keine")

def safe(fn, label):
    try:
        return fn()
    except Exception as e:
        print("  ! %s: Fehler: %s" % (label, e))
        return None

# ---------------------------------------------------------------- Angebote ---
def build_offers():
    print("ANGEBOTE:")
    shops = []
    # Text-Websites
    for title, url in [
        ("Geißelmeier Treuchtlingen", "https://metzgerei-geisselmeier.de/angebote/"),
        ("Geißelmeier Wettelsheim",   "https://landmetzgerei-geisselmeier.de/"),
        ("Zum Schneck (Suffersheim)", "https://www.gasthaus-metzgerei-zum-schneck.de/angebote.html"),
    ]:
        txt = safe(lambda: page_text(url), title)
        if txt is None: continue
        block = safe(lambda: ai_text(P_OFFER_TXT % txt), title)
        if block is not None: add(shops, title, block)
        time.sleep(BASE_SLEEP)
    # Bilder
    def img_offer(title, page_or_img, prompt, pattern=None, strip=False):
        url = page_or_img
        if pattern:
            url = safe(lambda: find_image(page_or_img, pattern, strip), title)
            if not url: print("  ! %s: kein Bild gefunden" % title); return
        data = safe(lambda: img_bytes(url), title)
        if not data: return
        block = safe(lambda: ai_image(prompt, data[0], data[1]), title)
        if block is not None: add(shops, title, block)
        time.sleep(BASE_SLEEP)

    img_offer("Völk Weißenburg", "https://www.fleischwaren-voelk.de/images/angebot.jpg",
              P_OFFER_IMG_VOELK)
    img_offer("Struller Weißenburg",
              "https://metzgerei-struller.de/wp-content/uploads/2025/05/Osterempfehlungen-20.png",
              P_OFFER_IMG_STRULLER)
    img_offer("Wörlein Treuchtlingen",
              "https://metzgerei-woerlein.de/angebote/aktuelle-wochenangebote/",
              P_OFFER_IMG_WOERLEIN,
              pattern=r"https://metzgerei-woerlein\.de/wp-content/uploads/20\d\d/\d\d/p-\d+[0-9x-]*\.jpg")
    return order_shops(shops)

# ------------------------------------------------------------- Mittagstisch --
def build_lunch():
    print("MITTAGSTISCH:")
    shops = []
    for title, url in [
        ("Geißelmeier Treuchtlingen", "https://metzgerei-geisselmeier.de/angebote/"),
        ("Geißelmeier Wettelsheim",   "https://landmetzgerei-geisselmeier.de/"),
    ]:
        txt = safe(lambda: page_text(url), title)
        if txt is None: continue
        block = safe(lambda: ai_text(P_LUNCH_TXT % txt), title)
        if block is not None: add(shops, title, block, lunch=True)
        time.sleep(BASE_SLEEP)

    def img_lunch(title, page_or_img, pattern=None, strip=False):
        url = page_or_img
        if pattern:
            url = safe(lambda: find_image(page_or_img, pattern, strip), title)
            if not url: print("  ! %s: kein Bild gefunden" % title); return
        data = safe(lambda: img_bytes(url), title)
        if not data: return
        block = safe(lambda: ai_image(P_LUNCH_IMG, data[0], data[1]), title)
        if block is not None: add(shops, title, block, lunch=True)
        time.sleep(BASE_SLEEP)

    img_lunch("Struller Weißenburg",
              "https://metzgerei-struller.de/wp-content/uploads/2025/05/NEU-Speiseplan-23.png")
    img_lunch("Völk Weißenburg", "https://fleischwaren-voelk.de/images/menueplan1.jpg")
    img_lunch("Wörlein Treuchtlingen", "https://metzgerei-woerlein.de/angebote/menueplan/",
              pattern=r"https://metzgerei-woerlein\.de/wp-content/uploads/20\d\d/\d\d/KW-[0-9x-]+\.jpg",
              strip=True)
    return order_shops(shops)

# ---------------------------------------------------------------------- Main -
def main():
    now = datetime.now(TZ) if TZ else datetime.now()
    updated = now.strftime("%d.%m. %H:%M")
    gen = now.isoformat(timespec="seconds")

    offers = build_offers()
    lunch  = build_lunch()

    wrote = []
    if offers:
        with open(os.path.join(HERE, "data.json"), "w", encoding="utf-8") as f:
            json.dump({"updated": updated, "generated": gen, "shops": offers}, f, ensure_ascii=False)
        wrote.append("data.json (%d Betriebe)" % len(offers))
    else:
        print("WARN: keine Angebote – data.json unveraendert gelassen.")
    if lunch:
        with open(os.path.join(HERE, "mittagstisch.json"), "w", encoding="utf-8") as f:
            json.dump({"updated": updated, "generated": gen, "shops": lunch}, f, ensure_ascii=False)
        wrote.append("mittagstisch.json (%d Betriebe)" % len(lunch))
    else:
        print("WARN: kein Mittagstisch – mittagstisch.json unveraendert gelassen.")

    if not wrote:
        sys.exit("FEHLER: weder Angebote noch Mittagstisch gefunden – nichts geschrieben.")
    print("OK: " + ", ".join(wrote) + " | Stand '%s'" % updated)

if __name__ == "__main__":
    main()
