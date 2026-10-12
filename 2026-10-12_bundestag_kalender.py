#!/usr/bin/env python3
"""
Bundestag-Kalender: erzeugt iCal-Feeds aus der Tagesordnung des Plenums.

Quelle: das JSON, das die Seite bundestag.de/parlament/plenum/tagesordnungen
selbst nachlädt (/apps/plenar/plenar/conferenceWeekJSON), plus die offiziellen
Sitzungswochen-Kalender (.ics) von bundestag.de.

Ausgabe (Ordner docs/):
  bundestag.ics                 alle Tagesordnungspunkte plus Sitzungswochen
  bundestag-energie-klima.ics   nur Punkte mit Energie-/Klima-/Industrie-Bezug
  index.html                    Abo-Links

Nur Standardbibliothek, läuft mit Python 3.9+.
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = "https://www.bundestag.de"
API = BASE + "/apps/plenar/plenar/conferenceWeekJSON"
SITZUNGSKALENDER = BASE + "/parlament/plenum/sitzungskalender"
UA = "bundestag-kalender/1.0 (privates Kalenderprojekt)"

# DIP-API des Bundestags. Der öffentliche Schlüssel steht auf
# https://dip.bundestag.de/über-dip/hilfe/api und gilt bis Ende Mai 2027.
# Eigener Schlüssel: als Umgebungsvariable DIP_API_KEY (GitHub-Secret) setzen.
DIP_BASE = "https://search.dip.bundestag.de/api/v1"
DIP_KEY = os.environ.get("DIP_API_KEY") or "R2BZaee.DjdCyihKZMf8AOjtScubP2EVydegzjmBIQ"
TTL = 3 * 3600          # aktuelle Einträge höchstens alle 3 Stunden neu abfragen
MAX_DIP_PRO_LAUF = int(os.environ.get("DIP_MAX_PRO_LAUF") or 400)  # neue Drucksachen je Lauf (erster Lauf füllt den Cache schrittweise)
MAX_TEXTARCHIV_PRO_LAUF = 60
WAHLPERIODE = 21
MAX_ANHAENGE = 12  # ATTACH-Zeilen je Plenartermin
MAX_ANHAENGE_AUSSCHUSS = 25
SITZUNG_MINUTEN = 120  # geschätzte Dauer nicht öffentlicher Ausschusssitzungen
MAX_DETAILS_PRO_LAUF = 50
BERLIN = ZoneInfo("Europe/Berlin")

# Betreiber und Adressen (für die Startseite)
BETREIBER = "KlimaUnion gGmbH, Berlin"
BETREIBER_URL = "https://klimaunion.org"
IMPRESSUM_URL = "https://klimaunion.org/impressum"
DATENSCHUTZ_URL = "https://klimaunion.org/datenschutz"
REPO_URL = "https://github.com/KlimaUnion-gGmbH/bundestag-kalender"
BASIS_URL = "https://klimaunion-ggmbh.github.io/bundestag-kalender/"  # Voreinstellung ohne GITHUB_REPOSITORY
# Rollen, die in die Ausschuss-Feeds aufgenommen werden. Mitberatung ist bewusst ausgeschlossen.
# Zum Wiederaufnehmen "mitberatend" ergänzen.
FEED_ROLLEN = ("federführend", "Beschlussempfehlung und Bericht")

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "docs"
CACHE = ROOT / "cache"

ORT = "Plenarsaal, Reichstagsgebäude, Platz der Republik 1, 11011 Berlin"
LETZTER_TOP_MINUTEN = 45  # Endzeit des letzten Punkts eines Tages (nicht veröffentlicht)
ERÖFFNUNG_MINUTEN = 5

# Ausschüsse, für die es je einen eigenen Feed gibt.
AUSSCHUESSE = {
    "wirtschaft-energie": {
        "datei": "bundestag-wirtschaft-energie.ics",
        "name": "Wirtschaft und Energie",
        "nr": 9,
        "kuerzel": {"AfWE"},
        "alias": [r"Wirtschaft und Energie", r"Wirtschaftsausschuss"],
        # Eigene Sitzungen und Anhörungen laut Ausschussseite (ID-Teile stehen in den Seiten-Skripten).
        "sitzungen": {
            "kurz": "Ausschuss WE",
            "seite": "ausschuesse/a09_wirtschaft",
            "to_pfad": "ausschuesse/a09_wirtschaft/wp21_a09_Tagesordnung/1057676-1057676",
            "ah_pfad": "ausschuesse/a09_wirtschaft/wp21_a09_Anhoerungen/1057552-1057552",
            "ah_seite": "ausschuesse/a09_wirtschaft/wp21_a09_Anhoerungen",
        },
    },
    "umwelt-klima": {
        "datei": "bundestag-umwelt-klima.ics",
        "name": "Umwelt, Klimaschutz, Naturschutz und nukleare Sicherheit",
        "nr": 16,
        "kuerzel": {"AfU"},
        "alias": [r"Umwelt, Klimaschutz, Naturschutz und nukleare Sicherheit", r"Umweltausschuss"],
    },
}

MONATE = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11,
    "dezember": 12,
}

VTIMEZONE = (
    "BEGIN:VTIMEZONE\r\nTZID:Europe/Berlin\r\n"
    "BEGIN:STANDARD\r\nTZNAME:CET\r\nDTSTART:19701025T030000\r\n"
    "TZOFFSETFROM:+0200\r\nTZOFFSETTO:+0100\r\n"
    "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU\r\nEND:STANDARD\r\n"
    "BEGIN:DAYLIGHT\r\nTZNAME:CEST\r\nDTSTART:19700329T020000\r\n"
    "TZOFFSETFROM:+0100\r\nTZOFFSETTO:+0200\r\n"
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU\r\nEND:DAYLIGHT\r\n"
    "END:VTIMEZONE\r\n"
)


# ---------------------------------------------------------------- Abruf

def http_get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "X-Requested-With": "XMLHttpRequest"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    sicher = re.sub(r"apikey=[^&]+", "apikey=***", url)
    raise RuntimeError(f"Abruf fehlgeschlagen: {sicher}: {re.sub(r'apikey=[^&]+', 'apikey=***', str(last))}")


def sitzungswochen():
    """Liest die offiziellen Sitzungswochen-.ics von bundestag.de.
    Rückgabe: Liste (start, ende_exklusiv) als date."""
    seite = http_get(SITZUNGSKALENDER).decode("utf-8", "ignore")
    links = sorted(set(re.findall(r"(/resource/blob/\d+/[^\"'\s>]+?\.ics)", seite)))
    wochen = set()
    for l in links:
        try:
            ics = http_get(BASE + l).decode("utf-8", "ignore")
        except RuntimeError as e:
            print("Warnung:", e, file=sys.stderr)
            continue
        for ev in ics.split("BEGIN:VEVENT")[1:]:
            s = re.search(r"DTSTART;VALUE=DATE:(\d{8})", ev)
            e = re.search(r"DTEND;VALUE=DATE:(\d{8})", ev)
            if s and e:
                wochen.add((datetime.strptime(s.group(1), "%Y%m%d").date(),
                            datetime.strptime(e.group(1), "%Y%m%d").date()))
    return sorted(wochen)


def lade_woche(jahr, kw, montag):
    """Holt eine Sitzungswoche. Vergangene Wochen (älter als 7 Tage) werden
    im Ordner cache/ abgelegt und nicht erneut abgerufen."""
    datei = CACHE / f"{jahr}-W{kw:02d}.json"
    freitag = montag + timedelta(days=4)
    eingefroren = (date.today() - freitag).days > 7
    if eingefroren and datei.exists():
        return json.loads(datei.read_text(encoding="utf-8"))
    try:
        daten = json.loads(http_get(f"{API}?year={jahr}&week={kw}"))
    except Exception as e:  # noqa: BLE001
        if datei.exists():
            print("Warnung: nutze Cache für", datei.name, e, file=sys.stderr)
            return json.loads(datei.read_text(encoding="utf-8"))
        raise
    if eingefroren and daten.get("conferences"):
        CACHE.mkdir(exist_ok=True)
        datei.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
    return daten


# ------------------------------------------------ Ausschuss-Sitzungen

SITZ_RE = re.compile(
    r"(\d+)\. Sitzung am [A-Za-zäöüÄÖÜ]+,? den (\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s+(\d{4}),?\s*"
    r"(\d{1,2})[:.](\d{2}) Uhr(?:,\s*(.+?))?\s*[-–]\s*(nicht öffentlich|öffentlich)")


def reintext(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def datum_de(text):
    m = re.search(r"(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s+(\d{4})", text or "")
    if not m or m.group(2).lower() not in MONATE:
        return None
    return date(int(m.group(3)), MONATE[m.group(2).lower()], int(m.group(1)))


def ajax(pfad, offset):
    return http_get(f"{BASE}/ajax/filterlist/de/{pfad}?offset={offset}").decode("utf-8", "ignore")


def parse_to_seite(h):
    rows = []
    for r in re.findall(r'<tr class="e-table__row.*?</tr>', h, re.S):
        tds = re.findall(r"<td.*?</td>", r, re.S)
        a = re.search(r'<a[^>]*href="([^"]+)"[^>]*>\s*<span>(.*?)</span>', r, re.S)
        if len(tds) < 4 or not a:
            continue
        d = datum_de(reintext(tds[0]))
        rows.append({"veroeff": d.isoformat() if d else "", "href": urljoin(BASE, a.group(1)),
                     "titel": reintext(a.group(2))})
    return rows


def crawl_tagesordnungen(cfg, cache, heute):
    grenze = date(heute.year - 1, 12, 1).isoformat()
    doks = cache.setdefault("dokumente", {})
    offset = 0
    for _ in range(80):
        rows = parse_to_seite(ajax(cfg["to_pfad"], offset))
        if not rows:
            cache["to_vollstaendig"] = True
            break
        neu = [r for r in rows if r["href"] not in doks]
        for r in rows:
            doks[r["href"]] = r
        if cache.get("to_vollstaendig") and not neu:
            break
        if rows[-1]["veroeff"] and rows[-1]["veroeff"] < grenze:
            cache["to_vollstaendig"] = True
            break
        offset += 10
        time.sleep(0.3)


def sitzungen_aus_dokumenten(doks):
    sitz = {}
    for r in doks.values():
        m = SITZ_RE.search(r["titel"])
        if not m or m.group(3).lower() not in MONATE:
            continue
        nr = int(m.group(1))
        start = datetime(int(m.group(4)), MONATE[m.group(3).lower()], int(m.group(2)),
                         int(m.group(5)), int(m.group(6)))
        z = sitz.setdefault(nr, {"nr": nr, "start": start, "ort": "", "oeffentlich": False, "docs": []})
        z["oeffentlich"] = m.group(8) == "öffentlich"
        if m.group(7):
            z["ort"] = m.group(7).strip()
        art = "Tagesordnung" if re.match(r"\s*\d+\. Sitzung", r["titel"]) else r["titel"].split(" zur ")[0]
        z["docs"].append({"art": art, "href": r["href"], "veroeff": r["veroeff"]})
    for z in sitz.values():
        z["docs"].sort(key=lambda d: (d["art"] != "Tagesordnung", d["veroeff"]))
    return sitz


def crawl_anhoerungen(cfg, cache, heute):
    ahs = cache.setdefault("anhoerungen", {})
    grenze = date(heute.year, 1, 1).isoformat()
    offset = 0
    for _ in range(40):
        h = ajax(cfg["ah_pfad"], offset)
        aktuell, gefunden, neu, letzte = "", 0, 0, ""
        for m in re.finditer(r"<h4>(.*?)</h4>|<a[^>]*title=\"([^\"]*)\"[^>]*href=\"[^\"]*Anhoerungen/(\d+)-", h, re.S):
            if m.group(1) is not None:
                d = datum_de(m.group(1))
                aktuell = d.isoformat() if d else aktuell
            else:
                gefunden += 1
                aid = m.group(3)
                letzte = aktuell
                if aid not in ahs:
                    neu += 1
                    ahs[aid] = {"titel": html.unescape(m.group(2)), "datum": aktuell}
        if not gefunden:
            cache["ah_vollstaendig"] = True
            break
        if cache.get("ah_vollstaendig") and not neu:
            break
        if letzte and letzte < grenze:
            cache["ah_vollstaendig"] = True
            break
        offset += 10
        time.sleep(0.3)


def ics_felder(text):
    text = re.sub(r"\r?\n[ \t]", "", text)
    def feld(name):
        m = re.search(rf"^{name}[^:\n]*:(.*)$", text, re.M)
        if not m:
            return ""
        return re.sub(r"\\(.)", lambda x: "\n" if x.group(1) in "nN" else x.group(1), m.group(1).strip())
    def zeit(name):
        w = feld(name)
        if not w:
            return None
        try:
            if w.endswith("Z"):
                return datetime.strptime(w, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=timezone.utc).astimezone(BERLIN).replace(tzinfo=None)
            return datetime.strptime(w[:15], "%Y%m%dT%H%M%S")
        except ValueError:
            return None
    return {"start": zeit("DTSTART"), "end": zeit("DTEND"), "summary": feld("SUMMARY"),
            "ort": feld("LOCATION"), "beschreibung": feld("DESCRIPTION")}


def parse_anhoerung(aid, ics_text, seite):
    f = ics_felder(ics_text) if ics_text else {}
    docs, gesehen = [], set()
    for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', seite, re.S):
        href = urljoin(BASE, m.group(1))
        if href in gesehen:
            continue
        gesehen.add(href)
        t = re.sub(r"\s*\((?:Dokument|PDF)[^)]*\)\s*$", "", reintext(m.group(2))).strip()
        docs.append({"titel": t or href.rsplit("/", 1)[-1], "href": href})
    anm = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(?:(?!</a>).)*Anmeldung zur Sitzung', seite, re.S)
    text = reintext(seite)
    frist = re.search(r"melden Sie sich bitte bis zum (\d{1,2}\. [A-Za-zäöü]+ \d{4})", text)
    return {"start": f.get("start").isoformat() if f.get("start") else "",
            "end": f.get("end").isoformat() if f.get("end") else "",
            "ort": f.get("ort", ""), "gegenstand": f.get("beschreibung", ""),
            "oeffentlich": "Die Sitzung ist öffentlich" in text,
            "docs": docs, "anmeldung": urljoin(BASE, anm.group(1)) if anm else "",
            "frist": frist.group(1) if frist else ""}


def details_phase(cfg, cache, heute):
    jetzt, geholt = time.time(), 0
    grenze = date(heute.year, 1, 1).isoformat()
    for aid, a in sorted(cache.get("anhoerungen", {}).items(), key=lambda x: x[1]["datum"], reverse=True):
        if a["datum"] and a["datum"] < grenze:
            continue
        aktuell = not a["datum"] or (heute - date.fromisoformat(a["datum"])).days <= 7
        if a.get("daten") and not (aktuell and jetzt - a["ts"] > TTL):
            continue
        if geholt >= MAX_DETAILS_PRO_LAUF:
            break
        try:
            seite = http_get(f"{BASE}/{cfg['ah_seite']}/{aid}-{aid}").decode("utf-8", "ignore")
            try:
                ics = http_get(f"{BASE}/blueprint/servlet/content/{aid}/ics").decode("utf-8", "ignore")
            except RuntimeError:
                ics = ""
            a["daten"] = parse_anhoerung(aid, ics, seite)
            a["ts"] = jetzt
            geholt += 1
        except Exception as e:  # noqa: BLE001
            print(f"Warnung: Anhörung {aid}: {e}", file=sys.stderr)
        time.sleep(0.4)
    return geholt


def ausschuss_events(cfg, cache, heute):
    kurz = cfg["kurz"]
    sitz = sitzungen_aus_dokumenten(cache.get("dokumente", {}))
    grenze = datetime(heute.year, 1, 1)
    ahs = {aid: a for aid, a in cache.get("anhoerungen", {}).items() if a.get("daten")}
    events, verwendet = [], set()
    to_seite = f"{BASE}/{cfg['seite']}"

    def sitzung_zu(start):
        for z in sitz.values():
            if z["oeffentlich"] and abs((z["start"] - start).total_seconds()) <= 2700:
                return z
        return None

    for aid, a in ahs.items():
        d = a["daten"]
        if not d.get("start"):
            continue
        start = datetime.fromisoformat(d["start"])
        if start < grenze:
            continue
        ende = datetime.fromisoformat(d["end"]) if d.get("end") else start + timedelta(minutes=90)
        z = sitzung_zu(start)
        if z:
            verwendet.add(z["nr"])
        zeilen = ["Öffentliche Anhörung" + (f" ({z['nr']}. Sitzung)" if z else "")]
        if d.get("gegenstand"):
            gegenstand = re.sub(r"\s*\((?:Dokument|PDF)[^)]*\)", "", d["gegenstand"])
            if len(gegenstand) > 700:
                gegenstand = gegenstand[:700].rsplit(" ", 1)[0] + " ... (weiter auf der Seite der Anhörung)"
            zeilen += ["", "Gegenstand: " + gegenstand]
        if d.get("frist") or d.get("anmeldung"):
            zeilen += ["", "Anmeldung als Zuschauer" + (f" bis {d['frist']}" if d.get("frist") else "")
                       + (f": {d['anmeldung']}" if d.get("anmeldung") else "")]
        dok_zeilen, anh = [], []
        if z:
            for dk in z["docs"]:
                dok_zeilen.append(f"{dk['art']}: {dk['href']}")
                anh.append((dk["href"], "application/pdf"))
        for dk in d.get("docs", []):
            if z and any(dk["href"] == x["href"] for x in z["docs"]):
                continue
            dok_zeilen.append(f"{dk['titel']}: {dk['href']}")
            anh.append((dk["href"], "application/pdf"))
        for dnr in dict.fromkeys(re.findall(r"(?<![\d/])(\d{2}/\d{2,5})(?![\d/])", d.get("gegenstand", ""))):
            if any(drucksache_pdf(dnr) == x[0] for x in anh):
                continue
            dok_zeilen.append(f"Drucksache {dnr}: {drucksache_pdf(dnr)}")
            anh.append((drucksache_pdf(dnr), "application/pdf"))
        if dok_zeilen:
            zeilen += ["", "Dokumente:"] + dok_zeilen
        zeilen += ["", f"Seite des Ausschusses: {to_seite}",
                   "Übertragung: https://www.bundestag.de/mediathek"]
        events.append({
            "uid": f"ausschuss-{slug(cfg['seite'])}-anhoerung-{aid}@bundestag-kalender",
            "start": start, "end": ende, "summary": f"{kurz}: {a['titel']}",
            "description": "\n".join(zeilen),
            "url": f"{BASE}/{cfg['ah_seite']}/{aid}-{aid}",
            "ort": d.get("ort") or "", "anhaenge": anh[:MAX_ANHAENGE_AUSSCHUSS]})

    for nr, z in sitz.items():
        if nr in verwendet or z["start"] < grenze:
            continue
        art = "öffentlich" if z["oeffentlich"] else "nicht öffentlich"
        zeilen = [f"{nr}. Sitzung des Ausschusses ({art})", "Ende geschätzt.", "", "Tagesordnung und Ergänzungen:"]
        zeilen += [f"{dk['art']}: {dk['href']}" for dk in z["docs"]]
        zeilen += ["", f"Seite des Ausschusses: {to_seite}"]
        events.append({
            "uid": f"ausschuss-{slug(cfg['seite'])}-sitzung-{nr}@bundestag-kalender",
            "start": z["start"], "end": z["start"] + timedelta(minutes=SITZUNG_MINUTEN),
            "summary": f"{kurz}: {nr}. Sitzung ({art})", "description": "\n".join(zeilen),
            "url": to_seite, "ort": z["ort"],
            "anhaenge": [(dk["href"], "application/pdf") for dk in z["docs"]][:MAX_ANHAENGE_AUSSCHUSS]})
    events.sort(key=lambda e: e["start"])
    return events


# ------------------------------------------------- Ausschuss-Zuordnung

RANG = {"textarchiv": 1, "tagesordnung": 2, "dip": 4, "bericht": 5}
QUELLE_TEXT = {
    "dip": "DIP, amtlich",
    "bericht": "Beschlussempfehlung der Tagesordnung, amtlich",
    "tagesordnung": "Überweisungsvorschlag der Tagesordnung",
    "textarchiv": "Vorschlag laut Textarchiv",
}
VORSCHLAG = ("tagesordnung", "textarchiv")


def lade_json(pfad):
    if pfad.exists():
        try:
            return json.loads(pfad.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def speichere_json(pfad, daten):
    CACHE.mkdir(exist_ok=True)
    text = json.dumps(daten, ensure_ascii=False, indent=1, sort_keys=True)
    if not pfad.exists() or pfad.read_text(encoding="utf-8") != text:
        pfad.write_text(text, encoding="utf-8")


def key_fuer(kuerzel, name):
    for key, a in AUSSCHUESSE.items():
        if kuerzel in a["kuerzel"]:
            return key
        if name and any(re.search(p, name) for p in a["alias"]):
            return key
    return None


def setze(res, key, rolle, quelle):
    alt = res.get(key)
    if alt:
        if RANG[quelle] < RANG[alt["quelle"]]:
            return
        if (RANG[quelle] == RANG[alt["quelle"]] and alt["rolle"] == "federführend"
                and rolle != "federführend"):
            return
    res[key] = {"rolle": rolle, "quelle": quelle}


def dip_get(pfad, **params):
    params["apikey"] = DIP_KEY
    return json.loads(http_get(f"{DIP_BASE}/{pfad}?{urllib.parse.urlencode(params)}"))


def dip_positionen(vorgang_id):
    pos, cursor = [], None
    for _ in range(5):
        params = {"f.vorgang": vorgang_id}
        if cursor:
            params["cursor"] = cursor
        d = dip_get("vorgangsposition", **params)
        pos += d.get("documents", [])
        neu_cursor = d.get("cursor")
        if len(pos) >= int(d.get("numFound", 0)) or not neu_cursor or neu_cursor == cursor:
            break
        cursor = neu_cursor
    return pos


def ausschuesse_aus_positionen(positionen):
    """Überweisungen des Bundestags (nicht des Bundesrats), chronologisch zusammengeführt."""
    bt = [p for p in positionen
          if p.get("ueberweisung") and (p.get("fundstelle") or {}).get("herausgeber") == "BT"]
    bt.sort(key=lambda p: p.get("datum", ""))
    res = {}
    for p in bt:
        for u in p["ueberweisung"]:
            kz = u.get("ausschuss_kuerzel") or u.get("ausschuss") or "?"
            fed = bool(u.get("federfuehrung"))
            alt = res.get(kz)
            if alt and alt["rolle"] == "federführend" and not fed:
                continue  # "Änderung der Ausschussüberweisung" nennt nur Zusätze
            res[kz] = {"name": u.get("ausschuss") or kz,
                       "rolle": "federführend" if fed else "mitberatend"}
    return res


def dip_lookup(dnr, vorgangs_cache):
    dr = dip_get("drucksache", **{"f.dokumentnummer": dnr, "f.zuordnung": "BT"})
    docs = dr.get("documents", [])
    if not docs:
        return {"gefunden": False, "ausschuesse": {}}
    res = {}
    for vb in docs[0].get("vorgangsbezug", []):
        vid = vb["id"]
        if vid not in vorgangs_cache:
            vorgangs_cache[vid] = ausschuesse_aus_positionen(dip_positionen(vid))
        for kz, info in vorgangs_cache[vid].items():
            if kz not in res or (info["rolle"] == "federführend"):
                res[kz] = info
    return {"gefunden": True, "typ": docs[0].get("drucksachetyp"), "ausschuesse": res,
            "id": docs[0].get("id"),
            "vorgaenge": [vb["id"] for vb in docs[0].get("vorgangsbezug", [])][:3]}


def dip_phase(events, dipc):
    jetzt = time.time()
    alle = {}
    for ev in events:
        for d in ev["drucksachen"]:
            alle[d] = alle.get(d, False) or ev["aktuell"]
    todo = [d for d, akt in alle.items()
            if d not in dipc or (akt and jetzt - dipc[d]["ts"] > TTL)]
    todo.sort(key=lambda d: (not alle[d], d not in dipc, d))
    vorgangs_cache, fehler, geholt = {}, 0, 0
    for d in todo[:MAX_DIP_PRO_LAUF]:
        try:
            dipc[d] = {**dip_lookup(d, vorgangs_cache), "ts": jetzt}
            geholt += 1
            if geholt % 25 == 0:
                speichere_json(CACHE / "dip.json", dipc)  # Zwischenstand sichern
        except Exception as e:  # noqa: BLE001
            fehler += 1
            print(f"Warnung: DIP {d}: {e}", file=sys.stderr)
            if fehler >= 5:
                print("Warnung: DIP wiederholt fehlgeschlagen, Phase abgebrochen.", file=sys.stderr)
                break
        time.sleep(0.25)
    offen = max(0, len(todo) - geholt)
    return geholt, fehler, offen


def textarchiv_ausschuesse(text):
    """Sätze mit 'federführend' oder 'mitberatend', die einen unserer Ausschüsse nennen."""
    res = {}
    for satz in re.split(r"(?<=[.!?])\s+|\n", text):
        if "Bundesrat" in satz or re.search(r"\bsollte\b", satz):
            continue
        for key, a in AUSSCHUESSE.items():
            for pat in a["alias"]:
                m = re.search(pat, satz)
                if not m:
                    continue
                f = [x.start() for x in re.finditer(r"federführ", satz, re.I)]
                mb = [x.start() for x in re.finditer(r"mitberat", satz, re.I)]
                if not f and not mb:
                    continue
                naechste_f = min((abs(x - m.start()) for x in f), default=10**6)
                naechste_m = min((abs(x - m.start()) for x in mb), default=10**6)
                res[key] = "federführend" if naechste_f <= naechste_m else "mitberatend"
    return res


def holen_textarchiv(link):
    h = http_get(BASE + link).decode("utf-8", "ignore")
    m = re.search(r"<main.*?</main>", h, re.S)
    h = m.group(0) if m else h
    h = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", "\n", h))


def dip_komplett(ev, dipc):
    return bool(ev["drucksachen"]) and all(
        dipc.get(d, {}).get("ausschuesse") for d in ev["drucksachen"])


def textarchiv_phase(events, dipc, tac):
    jetzt = time.time()
    geholt = 0
    for ev in events:
        link = ev["link"]
        if not (ev["erste"] and link) or dip_komplett(ev, dipc):
            continue
        if any(d not in dipc for d in ev["drucksachen"]):
            continue  # DIP noch nicht abgefragt
        eintrag = tac.get(link)
        if eintrag and not (ev["aktuell"] and jetzt - eintrag["ts"] > TTL):
            continue
        if geholt >= MAX_TEXTARCHIV_PRO_LAUF:
            break
        try:
            tac[link] = {"ausschuesse": textarchiv_ausschuesse(holen_textarchiv(link)), "ts": jetzt}
            geholt += 1
        except Exception as e:  # noqa: BLE001
            print(f"Warnung: Textarchiv {link}: {e}", file=sys.stderr)
        time.sleep(0.4)
    return geholt


def url_ok(url):
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def drucksache_pdf(dnr):
    wp, num = dnr.split("/")
    n = f"{int(num):05d}"
    return f"https://dserver.bundestag.de/btd/{wp}/{n[:3]}/{wp}{n}.pdf"


def protokoll_phase(events, prot):
    """Plenarprotokoll-PDF je Sitzung. Erst nach dem Sitzungstag, nur wenn die Datei abrufbar ist."""
    jetzt, heute = time.time(), date.today()
    sitzungen = {}
    for ev in events:
        if ev["sitzung"] is not None:
            sitzungen.setdefault(ev["sitzung"], ev["start"].date())
    geholt = 0
    for nr, tag in sorted(sitzungen.items()):
        if tag >= heute:
            continue
        alt = prot.get(str(nr))
        if alt and (alt.get("pdf") or jetzt - alt["ts"] < TTL):
            continue
        try:
            d = dip_get("plenarprotokoll", **{"f.dokumentnummer": f"{WAHLPERIODE}/{nr}"})
            pdf = None
            for x in d.get("documents", []):
                u = (x.get("fundstelle") or {}).get("pdf_url")
                if u and url_ok(u):
                    pdf = u
            prot[str(nr)] = {"pdf": pdf, "ts": jetzt}
            geholt += 1
            if geholt % 10 == 0:
                speichere_json(CACHE / "protokolle.json", prot)
            if geholt >= 60:
                break
        except Exception as e:  # noqa: BLE001
            print(f"Warnung: Plenarprotokoll {nr}: {e}", file=sys.stderr)
        time.sleep(0.25)
    return geholt


def links(ev, dipc, prot):
    """Textzeilen für die Beschreibung und Anhangs-Links (URL, Dateityp)."""
    zeilen, anhaenge = [], []
    for d in ev["drucksachen"][:20]:
        pdf = drucksache_pdf(d)
        eintrag = dipc.get(d, {})
        typ = f" ({eintrag['typ']})" if eintrag.get("typ") else ""
        z = f"Drucksache {d}{typ}: {pdf}"
        if eintrag.get("id"):
            z += f"\n  DIP: https://dip.bundestag.de/drucksache/-/{eintrag['id']}"
        zeilen.append(z)
        anhaenge.append((pdf, "application/pdf"))
    p = prot.get(str(ev["sitzung"]), {}).get("pdf")
    if p:
        zeilen.append(f"Plenarprotokoll {ev['sitzung']}. Sitzung: {p}")
        anhaenge.append((p, "application/pdf"))
    if ev["url"]:
        zeilen.append(f"Textarchiv: {ev['url']}")
    zeilen.append("Mediathek: https://www.bundestag.de/mediathek/plenarsitzungen")
    zeilen.append("Tagesordnung: https://www.bundestag.de/tagesordnung")
    return zeilen, anhaenge[:MAX_ANHAENGE]


def zuordnen(ev, dipc, tac):
    """Bestimmt je Ausschuss Rolle und Quelle. Rückgabe: key -> {rolle, quelle}."""
    res = {}
    komplett = dip_komplett(ev, dipc)
    if not komplett:
        if ev["link"] in tac:
            for key, rolle in tac[ev["link"]]["ausschuesse"].items():
                setze(res, key, rolle, "textarchiv")
        for key, rolle in ev["agenda_uebw"].items():
            setze(res, key, rolle, "tagesordnung")
    for d in ev["drucksachen"]:
        for kz, info in dipc.get(d, {}).get("ausschuesse", {}).items():
            key = key_fuer(kz, info.get("name"))
            if key:
                setze(res, key, info["rolle"], "dip")
    for key in ev["agenda_bericht"]:
        setze(res, key, "Beschlussempfehlung und Bericht", "bericht")
    return res


def beschreibung(ev, zuo, dipc, prot):
    zeilen = list(ev["kopf"])
    for key, z in zuo.items():
        zeilen.append(f"Ausschuss {AUSSCHUESSE[key]['name']}: {z['rolle']} ({QUELLE_TEXT[z['quelle']]})")
    je_dnr = []
    for d in ev["drucksachen"]:
        teile = []
        for kz, info in dipc.get(d, {}).get("ausschuesse", {}).items():
            if key_fuer(kz, info.get("name")):
                teile.append(f"{info['name']} ({info['rolle']})")
        if teile:
            typ = dipc.get(d, {}).get("typ")
            je_dnr.append(f"{d}{' (' + typ + ')' if typ else ''}: " + ", ".join(teile))
    if je_dnr and len(ev["drucksachen"]) > 1:
        zeilen.append("Zuordnung je Drucksache (DIP):")
        zeilen += [f"  {z}" for z in je_dnr[:12]]
    text = "\n".join(zeilen)
    text += ("\n\n" + ev["detail"] if ev["detail"] else "")
    lz, ev["anhaenge"] = links(ev, dipc, prot)
    return text + "\n\nLinks und Dokumente:\n" + "\n".join(lz)


# ---------------------------------------------------------- Aufbereitung

def html_zu_text(s):
    s = s or ""
    s = re.sub(
        r"<a [^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        lambda m: f"{re.sub(r'<[^>]+>', '', m.group(2)).strip()} ({m.group(1)})",
        s, flags=re.S)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    zeilen = [re.sub(r"[ \t]+", " ", z).strip() for z in s.split("\n")]
    s = "\n".join(zeilen)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def top_label(top):
    teile = [t.strip() for t in (top or "").split(",") if t.strip()]
    return ", ".join(f"TOP {t}" if t.isdigit() else t for t in teile)


def slug(s):
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40]


def konferenz_zu_events(c):
    m = re.search(r"(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s+(\d{4})",
                  (c.get("conferenceDate") or {}).get("date", ""))
    if not m:
        return []
    tag = date(int(m.group(3)), MONATE[m.group(2).lower()], int(m.group(1)))
    nr = c.get("conferenceNumber")
    zeilen, prev = [], None
    for r in c.get("rows", []):
        t = re.search(r"(\d{1,2}):(\d{2})", r.get("time") or "")
        if t:
            dt = datetime(tag.year, tag.month, tag.day, int(t.group(1)), int(t.group(2)))
            if prev and dt < prev:  # Sitzung geht über Mitternacht
                dt += timedelta(days=1)
        elif prev:
            dt = prev
        else:
            continue
        prev = dt
        zeilen.append((dt, r))

    events, benutzt = [], set()
    for i, (start, r) in enumerate(zeilen):
        label = top_label(r.get("top"))
        titel = html_zu_text((r.get("topic") or {}).get("title", "")).replace("\n", " ")
        ist_eroeffnung = not label and any(k in titel.lower() for k in ("eröffnung", "sitzungsende"))
        if ist_eroeffnung:
            ende = start + timedelta(minutes=ERÖFFNUNG_MINUTEN)
        else:
            spaeter = [s for s, _ in zeilen[i + 1:] if s > start]
            ende = spaeter[0] if spaeter else start + timedelta(minutes=LETZTER_TOP_MINUTEN)
        detail = html_zu_text((r.get("topic") or {}).get("detail", ""))
        status = (r.get("status") or {}).get("title", "")
        link = (r.get("topic") or {}).get("link")
        url = (BASE + link) if link and link.startswith("/") else link
        beschr = [f"Status: {status}" if status else "", f"{nr}. Sitzung" if nr else ""]
        beschr = [b for b in beschr if b]
        bericht, uebw = [], {}
        for key, a in AUSSCHUESSE.items():
            n = re.escape(a["name"])
            if re.search(rf"Ausschuss(?:es)? für {n}\s*\({a['nr']}\. Ausschuss\)", detail):
                bericht.append(key)
            m2 = re.search(rf"A\. f\. {n}( \(f\))?", detail)
            if m2:
                uebw[key] = "federführend" if m2.group(1) else "mitberatend"
        drucksachen = list(dict.fromkeys(
            re.findall(r"(?<![\d/])(\d{2}/\d{2,5})(?![\d/])", detail)))
        uid = f"bt-{nr}-{slug(label or 'x')}-{slug(titel)}"
        k = 2
        basis = uid
        while uid in benutzt:
            uid = f"{basis}-{k}"
            k += 1
        benutzt.add(uid)
        events.append({
            "uid": uid + "@bundestag-kalender",
            "start": start, "end": ende,
            "summary": f"{label}: {titel}" if label else titel,
            "kopf": beschr, "detail": detail, "url": url, "link": link,
            "erste": "Erste Beratung" in detail, "drucksachen": drucksachen,
            "agenda_bericht": bericht, "agenda_uebw": uebw,
            "aktuell": (date.today() - start.date()).days <= 7,
            "sitzung": nr,
        })
    return events


# ------------------------------------------------------------------- ICS

def esc(s):
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
             .replace("\r", "").replace("\n", "\\n"))


def fold(line):
    teile, cur, n, limit = [], "", 0, 75
    for ch in line:
        l = len(ch.encode("utf-8"))
        if n + l > limit:
            teile.append(cur)
            cur, n = ch, l + 1
        else:
            cur += ch
            n += l
    teile.append(cur)
    return "\r\n ".join(teile)


def ics_bauen(name, beschreibung, events, wochen):
    jetzt = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//bundestag-kalender//DE", "CALSCALE:GREGORIAN",
        "X-WR-TIMEZONE:Europe/Berlin", f"X-WR-CALNAME:{esc(name)}",
        f"DESCRIPTION:{esc(beschreibung)}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT15M", "X-PUBLISHED-TTL:PT15M",
    ]
    body = []
    for s, e in wochen:
        body += ["BEGIN:VEVENT", f"UID:sw-{s:%Y%m%d}@bundestag-kalender",
                 f"DTSTAMP:{jetzt}", f"DTSTART;VALUE=DATE:{s:%Y%m%d}",
                 f"DTEND;VALUE=DATE:{e:%Y%m%d}", "SUMMARY:Sitzungswoche",
                 "TRANSP:TRANSPARENT", "END:VEVENT"]
    for ev in events:
        body += ["BEGIN:VEVENT", f"UID:{ev['uid']}", f"DTSTAMP:{jetzt}",
                 f"DTSTART;TZID=Europe/Berlin:{ev['start']:%Y%m%dT%H%M%S}",
                 f"DTEND;TZID=Europe/Berlin:{ev['end']:%Y%m%dT%H%M%S}",
                 f"SUMMARY:{esc(ev['summary'])}",
                 f"DESCRIPTION:{esc(ev['description'])}",
                 f"LOCATION:{esc(ev.get('ort') or ORT)}"]
        if ev["url"]:
            body.append(f"URL:{ev['url']}")
        for url, typ in ev.get("anhaenge", []):
            body.append(f"ATTACH;FMTTYPE={typ}:{url}")
        body.append("END:VEVENT")
    text = "\r\n".join(fold(l) for l in out) + "\r\n" + VTIMEZONE
    text += "\r\n".join(fold(l) for l in body) + ("\r\n" if body else "")
    return text + "END:VCALENDAR\r\n"


def schreiben_wenn_geaendert(pfad, neu):
    """Schreibt nur, wenn sich außer DTSTAMP etwas geändert hat (schont die Git-Historie)."""
    def norm(t):
        return re.sub(r"DTSTAMP:\S+", "", t)
    if pfad.exists() and norm(pfad.read_bytes().decode("utf-8")) == norm(neu):
        return False
    pfad.write_text(neu, encoding="utf-8", newline="")
    return True


def index_html(basis, feeds):
    items = ""
    for datei, label in feeds:
        web = (basis + datei).replace("https://", "webcal://")
        items += (f'<li>{html.escape(label)}: <a href="{web}">abonnieren</a> '
                  f'(<a href="{basis + datei}">Link kopieren</a>)</li>\n')
    return f"""<!doctype html>
<html lang="de"><meta charset="utf-8"><title>Bundestag-Kalender</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<body style="font-family:system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem">
<h1>Bundestag-Kalender</h1>
<p>Kalenderabos mit der Tagesordnung des Plenums und den Terminen des Ausschusses für Wirtschaft und Energie
des Deutschen Bundestages. Betrieben von der <a href="{BETREIBER_URL}">{html.escape(BETREIBER)}</a>
als Angebot für die energie- und klimapolitische Informationsarbeit. Alle Daten sind öffentliche Parlamentsdaten.</p>
<p>Aktualisierung automatisch, in Sitzungswochen etwa alle 15 Minuten. Abo-Programme holen oft seltener ab.</p>
<ul>
{items}</ul>
<p>Inoffizielles Angebot, keine Gewähr. Quellen: bundestag.de und das Dokumentations- und Informationssystem DIP.
Endzeiten sind teils geschätzt. Ausschuss-Zuordnungen vor der ersten Beratung sind Vorschläge und im Titel gekennzeichnet.</p>
<p><a href="{IMPRESSUM_URL}">Impressum</a> | <a href="{DATENSCHUTZ_URL}">Datenschutz</a> | <a href="{REPO_URL}">Quellcode</a></p>
</body></html>
"""


# ------------------------------------------------------------------ main

def main():
    heute = date.today()
    wochen = [w for w in sitzungswochen() if w[1] >= date(heute.year, 1, 1)]
    if not wochen:
        print("Keine Sitzungswochen gefunden, Abbruch.", file=sys.stderr)
        return 1

    konferenzen = {}
    zu_holen = {(s.isocalendar()[0], s.isocalendar()[1]): s for s, _ in wochen}
    fehler = 0
    for (jahr, kw), montag in sorted(zu_holen.items()):
        try:
            daten = lade_woche(jahr, kw, montag)
        except Exception as e:  # noqa: BLE001
            fehler += 1
            print(f"Warnung: Woche {jahr}-W{kw}: {e}", file=sys.stderr)
            continue
        for c in daten.get("conferences", []):
            konferenzen[c.get("conferenceNumber")] = c
        time.sleep(0.5)
    # Standardabruf deckt Sondersitzungen außerhalb der Sitzungswochen ab
    try:
        for c in json.loads(http_get(API)).get("conferences", []):
            konferenzen[c.get("conferenceNumber")] = c
    except Exception as e:  # noqa: BLE001
        print("Warnung: Standardabruf:", e, file=sys.stderr)

    if fehler == len(zu_holen):
        print("Alle Abrufe fehlgeschlagen, bestehende Feeds bleiben unverändert.", file=sys.stderr)
        return 1

    events = []
    for c in konferenzen.values():
        events += konferenz_zu_events(c)
    events.sort(key=lambda e: e["start"])

    dipc = lade_json(CACHE / "dip.json")
    tac = lade_json(CACHE / "textarchiv.json")
    d_neu, d_fehler, d_offen = dip_phase(events, dipc)
    t_neu = textarchiv_phase(events, dipc, tac)
    prot = lade_json(CACHE / "protokolle.json")
    p_neu = protokoll_phase(events, prot)
    speichere_json(CACHE / "dip.json", dipc)
    speichere_json(CACHE / "textarchiv.json", tac)
    speichere_json(CACHE / "protokolle.json", prot)

    for ev in events:
        ev["zuo"] = zuordnen(ev, dipc, tac)
        ev["description"] = beschreibung(ev, ev["zuo"], dipc, prot)

    OUT.mkdir(exist_ok=True)
    geaendert = schreiben_wenn_geaendert(OUT / "bundestag.ics", ics_bauen(
        "Tagesordnung Bundestag",
        "Tagesordnung des Plenums des Deutschen Bundestages (inoffiziell, Quelle: bundestag.de)",
        events, wochen))
    anzahl = {}
    feeds = [("bundestag.ics", "Alle Tagesordnungspunkte des Plenums")]
    a_info = []
    for key, a in AUSSCHUESSE.items():
        teil = []
        for e in events:
            z = e["zuo"].get(key)
            if not z or z["rolle"] not in FEED_ROLLEN:
                continue
            e2 = dict(e)
            marken = []
            if z["rolle"] == "mitberatend":
                marken.append("mitberatend")
            if z["quelle"] in VORSCHLAG:
                marken.append("Ausschuss-Vorschlag")
            if marken:
                e2["summary"] += " (" + ", ".join(marken) + ")"
            teil.append(e2)
        anzahl[key] = (len(teil), sum(1 for e in teil if e["zuo"][key]["quelle"] in VORSCHLAG))
        geaendert |= schreiben_wenn_geaendert(OUT / a["datei"], ics_bauen(
            f"Bundestag: Ausschuss {a['name']}",
            f"Plenarpunkte, bei denen der Ausschuss {a['name']} federführend ist (inoffiziell, Quellen: DIP und bundestag.de)",
            teil, wochen))
        feeds.append((a["datei"], f"Plenum: {a['name']}"))
        cfg = a.get("sitzungen")
        if cfg:
            try:
                acache = lade_json(CACHE / f"ausschuss-{key}.json")
                heute_ = date.today()
                crawl_tagesordnungen(cfg, acache, heute_)
                crawl_anhoerungen(cfg, acache, heute_)
                d_neu2 = details_phase(cfg, acache, heute_)
                speichere_json(CACHE / f"ausschuss-{key}.json", acache)
                aev = ausschuss_events(cfg, acache, heute_)
                base = a["datei"][:-4]
                geaendert |= schreiben_wenn_geaendert(OUT / f"{base}-ausschuss.ics", ics_bauen(
                    f"Bundestag: {cfg['kurz']} Sitzungen und Anhörungen",
                    f"Sitzungen und öffentliche Anhörungen des Ausschusses {a['name']} (inoffiziell, Quelle: bundestag.de)",
                    aev, wochen))
                geaendert |= schreiben_wenn_geaendert(OUT / f"{base}-komplett.ics", ics_bauen(
                    f"Bundestag: {cfg['kurz']} komplett",
                    f"Plenarpunkte, Sitzungen und Anhörungen des Ausschusses {a['name']} (inoffiziell)",
                    sorted(teil + aev, key=lambda e: e["start"]), wochen))
                feeds.append((f"{base}-ausschuss.ics", f"Ausschuss-Sitzungen und Anhörungen: {a['name']}"))
                feeds.append((f"{base}-komplett.ics", f"Komplett (Plenum, Sitzungen, Anhörungen): {a['name']}"))
                a_info.append(f"  {key}: {len(aev)} Ausschuss-Termine, {d_neu2} Detailseiten neu gelesen")
            except Exception as e:  # noqa: BLE001
                print(f"Warnung: Ausschussseite {key}: {e}", file=sys.stderr)

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        eigner, name = repo.split("/", 1)
        basis = f"https://{eigner.lower()}.github.io/{name}/"
    else:
        basis = BASIS_URL
    schreiben_wenn_geaendert(OUT / "index.html", index_html(basis, feeds))

    print(f"{len(events)} Termine, {len(wochen)} Sitzungswochen")
    print(f"DIP: {d_neu} Drucksachen abgefragt, {d_fehler} Fehler, {d_offen} noch offen")
    print(f"Textarchiv: {t_neu} Artikel gelesen, Plenarprotokolle: {p_neu} abgefragt")
    for key, (n, v) in anzahl.items():
        print(f"  {key}: {n} Termine, davon {v} nur als Vorschlag")
    for z in a_info:
        print(z)
    print(f"Feeds geändert: {geaendert}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
