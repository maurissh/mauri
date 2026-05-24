#!/usr/bin/env python3
"""
build_playlist.py
-----------------
Scarica i canali italiani dal database pubblico iptv-org, li abbina ai
numeri LCN della piattaforma tivusat tramite una tabella di mapping locale
(lcn_tivusat.json) e genera una playlist M3U ordinata per numero di canale.

Non richiede dipendenze esterne: usa solo la libreria standard di Python 3.

Dati sorgente (aggiornati quotidianamente da iptv-org):
  - https://iptv-org.github.io/api/channels.json   (anagrafica canali)
  - https://iptv-org.github.io/api/streams.json     (URL degli stream)
  - https://iptv-org.github.io/api/feeds.json        (segnali/feed per canale)
"""

import json
import re
import sys
import unicodedata
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# --- Configurazione ---------------------------------------------------------

API_BASE = "https://iptv-org.github.io/api"
CHANNELS_URL = f"{API_BASE}/channels.json"
STREAMS_URL = f"{API_BASE}/streams.json"

COUNTRY = "IT"  # codice ISO 3166-1 alpha-2 del paese da estrarre

# Seconda fonte: la playlist Italia di Free-TV/IPTV. A differenza di iptv-org
# (che punta alla copertura), Free-TV cura e testa i suoi stream tenendo un solo
# URL per canale. Per questo, sui canali presenti in ENTRAMBE le fonti, diamo
# priorita' a Free-TV (stream piu' affidabile); iptv-org resta la rete di
# copertura per tutti gli altri canali (regionali, radio, nicchie).
# Se Free-TV e' irraggiungibile o malformata, lo script prosegue con iptv-org.
FALLBACK_ENABLED = True
FALLBACK_URL = "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_italy.m3u8"

# --- Validazione stream -----------------------------------------------------
# Prima di pubblicare, lo script puo' testare ogni URL e scartare i canali morti,
# cosi' la playlist contiene solo stream vivi al momento della generazione.
VALIDATE_STREAMS = True
VALIDATE_TIMEOUT = 8        # secondi max di attesa per stream
VALIDATE_WORKERS = 12       # quanti stream testare in parallelo
# Alcuni stream sono geo-bloccati all'Italia: dal server GitHub (spesso fuori IT)
# risulterebbero "morti" pur funzionando da casa tua. I canali il cui URL contiene
# uno di questi frammenti NON vengono scartati anche se il test fallisce.
GEOBLOCK_WHITELIST = (
    "cloudfront.net",      # bouquet Discovery (geo-IT)
    "mediaset",            # Mediaset Infinity (geo-IT)
    "rai.it",              # Rai (a volte geo-IT)
    "akamaized.net",       # vari broadcaster IT
)

ROOT = Path(__file__).resolve().parent
MAPPING_FILE = ROOT / "lcn_tivusat.json"
OUTPUT_FILE = ROOT / "tivusat.m3u"
REPORT_FILE = ROOT / "report.md"
# File opzionale con stream da fonti diverse da iptv-org (es. bouquet Discovery,
# che iptv-org non copre). Formato: { "Nome Canale": "https://url-stream", ... }
OVERRIDES_FILE = ROOT / "overrides.json"

# Numero da cui partire per i canali italiani NON presenti nella tabella LCN.
# Vengono accodati in fondo, in ordine alfabetico, a partire da questo valore.
UNMAPPED_START = 9000


# --- Utility ----------------------------------------------------------------

def fetch_json(url):
    """Scarica e decodifica un file JSON da un URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "tivusat-builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_text(url):
    """Scarica testo grezzo da un URL (per la playlist M3U di fallback)."""
    req = urllib.request.Request(url, headers={"User-Agent": "tivusat-builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_m3u(text):
    """
    Parsa una playlist M3U e restituisce una lista di dict {name, logo, url}.
    Estrae il nome dal testo dopo la virgola di #EXTINF e l'eventuale tvg-name.
    """
    entries = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            # nome: preferisci tvg-name se c'e', altrimenti il testo dopo la virgola
            tvg_name = re.search(r'tvg-name="([^"]*)"', line)
            logo = re.search(r'tvg-logo="([^"]*)"', line)
            after_comma = line.split(",", 1)
            name = (tvg_name.group(1) if tvg_name
                    else (after_comma[1].strip() if len(after_comma) > 1 else ""))
            # l'URL e' sulla prima riga non-commento successiva
            url = ""
            j = i + 1
            while j < len(lines):
                cand = lines[j].strip()
                if cand and not cand.startswith("#"):
                    url = cand
                    break
                j += 1
            if name and url:
                entries.append({
                    "name": name,
                    "logo": logo.group(1) if logo else "",
                    "url": url,
                })
            i = j
        i += 1
    return entries


def is_geoblock_whitelisted(url):
    """True se l'URL appartiene a un broadcaster geo-bloccato all'Italia:
    questi non vanno scartati anche se il test dal server GitHub fallisce."""
    low = url.lower()
    return any(frag in low for frag in GEOBLOCK_WHITELIST)


def check_stream(url):
    """
    Verifica se uno stream risponde. Restituisce True se sembra vivo.
    Strategia: richiesta GET con timeout breve; per le playlist .m3u8 basta
    che il server risponda con codice 200 e un po' di contenuto.
    Non scarica il video: legge solo i primi byte.
    """
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (tivusat-builder stream-check)"
        })
        with urllib.request.urlopen(req, timeout=VALIDATE_TIMEOUT) as resp:
            code = resp.getcode()
            if code != 200:
                return False
            # legge un piccolo campione per confermare che arrivano dati
            chunk = resp.read(256)
            return bool(chunk)
    except Exception:
        return False


def validate_entries(entries):
    """
    Testa in parallelo gli stream di tutte le entries e restituisce due liste:
    (vivi, scartati). I canali in whitelist geo-block restano sempre tra i vivi
    anche se il test fallisce (potrebbero funzionare da casa, in Italia).
    """
    if not VALIDATE_STREAMS or not entries:
        return entries, []

    print(f"Verifico {len(entries)} stream (timeout {VALIDATE_TIMEOUT}s, "
          f"{VALIDATE_WORKERS} in parallelo)... puo' richiedere qualche minuto.")

    urls = [e["url"] for e in entries]
    with ThreadPoolExecutor(max_workers=VALIDATE_WORKERS) as pool:
        results = list(pool.map(check_stream, urls))

    alive, dropped = [], []
    for entry, ok in zip(entries, results):
        if ok:
            alive.append(entry)
        elif is_geoblock_whitelisted(entry["url"]):
            # test fallito ma e' geo-IT: lo teniamo e lo marchiamo
            entry["geo_kept"] = True
            alive.append(entry)
        else:
            dropped.append(entry)

    kept_geo = sum(1 for e in alive if e.get("geo_kept"))
    print(f"  Vivi: {len(alive)} (di cui {kept_geo} geo-IT tenuti per fiducia) "
          f"| Scartati: {len(dropped)}")
    return alive, dropped


def load_fallback_by_lcn(lcn_index):
    """
    Scarica la playlist di fallback e la indicizza per numero LCN, usando la
    tabella per riconoscere quali canali ci interessano. Restituisce
    { lcn: {name, logo, url} }. In caso di errore restituisce {} senza far
    fallire lo script.
    """
    if not FALLBACK_ENABLED:
        return {}
    try:
        text = fetch_text(FALLBACK_URL)
    except Exception as e:
        print(f"  (fallback non raggiungibile: {e} — proseguo con sola iptv-org)")
        return {}

    parsed = parse_m3u(text)
    if len(parsed) < 10:
        print(f"  (fallback malformato: solo {len(parsed)} voci — ignorato)")
        return {}

    by_lcn = {}
    for entry in parsed:
        # ripulisci il nome da simboli tipo "Ⓖ" che Free-TV aggiunge
        clean = entry["name"].replace("Ⓖ", "").strip()
        hit = lcn_index.get(normalize(clean))
        if hit:
            lcn = hit["lcn"]
            # tieni la prima occorrenza per ogni LCN
            if lcn not in by_lcn:
                by_lcn[lcn] = {
                    "name": hit["label"],
                    "logo": entry["logo"],
                    "url": entry["url"],
                }
    print(f"  Fallback Free-TV: {len(parsed)} canali totali, "
          f"{len(by_lcn)} abbinati a un LCN tivusat")
    return by_lcn


def normalize(name):
    """
    Normalizza il nome di un canale per il confronto:
    - minuscolo
    - rimuove accenti
    - rimuove suffissi tipo (1080p), [Geo-blocked], HD, ecc.
    - tiene solo lettere e numeri
    """
    if not name:
        return ""
    # toglie il contenuto tra parentesi tonde e quadre
    name = re.sub(r"\([^)]*\)", " ", name)
    name = re.sub(r"\[[^\]]*\]", " ", name)
    # rimuove accenti
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    # rimuove marcatori comuni di qualita / varianti
    for token in (" hd", " fhd", " uhd", " 4k", " sd", " full hd"):
        name = name.replace(token, " ")
    # tiene solo alfanumerici
    name = re.sub(r"[^a-z0-9]+", "", name)
    return name


# --- Logica principale ------------------------------------------------------

def load_mapping():
    """Carica la tabella LCN tivusat e costruisce un indice normalizzato."""
    if not MAPPING_FILE.exists():
        print(f"ERRORE: manca il file di mapping {MAPPING_FILE}", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    # raw e' { "Rai 1": 101, "Rai 2": 102, ... }
    index = {}
    for channel_name, lcn in raw.items():
        index[normalize(channel_name)] = {"lcn": int(lcn), "label": channel_name}
    return raw, index


def load_overrides():
    """
    Carica gli stream manuali da overrides.json, se presente.
    Restituisce una lista di dict { "name", "url" }.
    Serve per i canali che iptv-org non copre (es. bouquet Discovery free).
    """
    if not OVERRIDES_FILE.exists():
        return []
    raw = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
    result = []
    for name, url in raw.items():
        if name.startswith("_"):
            continue  # chiavi di commento/documentazione
        if url:  # ignora voci vuote
            result.append({"name": name, "url": url})
    return result


def build():
    print("Scarico i dati da iptv-org...")
    channels = fetch_json(CHANNELS_URL)
    streams = fetch_json(STREAMS_URL)

    # Filtra solo i canali del paese richiesto e non chiusi
    it_channels = {
        ch["id"]: ch
        for ch in channels
        if ch.get("country") == COUNTRY and not ch.get("closed")
    }
    print(f"Canali {COUNTRY} trovati nell'anagrafica: {len(it_channels)}")

    # Indicizza gli stream per channel id (puo' essercene piu' di uno: prendo il primo valido)
    streams_by_channel = {}
    for st in streams:
        cid = st.get("channel")
        url = st.get("url")
        if not cid or not url:
            continue
        if cid in it_channels:
            streams_by_channel.setdefault(cid, []).append(st)

    print(f"Canali {COUNTRY} con almeno uno stream: {len(streams_by_channel)}")

    raw_map, lcn_index = load_mapping()

    entries = []        # canali abbinati a un LCN
    unmapped = []       # canali italiani senza LCN noto
    matched_lcns = set()

    for cid, ch in it_channels.items():
        ch_streams = streams_by_channel.get(cid)
        if not ch_streams:
            continue  # nessuno stream disponibile: salto

        stream = ch_streams[0]
        name = ch.get("name", cid)

        # prova a matchare sul nome e sugli alt_names
        candidates = [name] + ch.get("alt_names", [])
        lcn_info = None
        for cand in candidates:
            hit = lcn_index.get(normalize(cand))
            if hit:
                lcn_info = hit
                break

        record = {
            "id": cid,
            "name": name,
            "logo": ch.get("logo", ""),
            "categories": ch.get("categories", []),
            "url": stream["url"],
        }

        if lcn_info:
            record["lcn"] = lcn_info["lcn"]
            matched_lcns.add(lcn_info["lcn"])
            entries.append(record)
        else:
            unmapped.append(record)

    # --- Seconda fonte (Free-TV) -------------------------------------------
    # Free-TV cura e testa i suoi stream: dove un canale e' in ENTRAMBE le fonti
    # preferiamo Free-TV (piu' affidabile), e usiamo Free-TV anche per i canali
    # che iptv-org non copre (es. bouquet Discovery). iptv-org resta la copertura
    # per tutto il resto (regionali, radio, nicchie).
    print("Controllo la seconda fonte (Free-TV)...")
    fallback_by_lcn = load_fallback_by_lcn(lcn_index)
    by_lcn = {r["lcn"]: r for r in entries}
    fallback_added = []      # canali NUOVI presi da Free-TV (iptv-org non li aveva)
    fallback_preferred = []  # canali per cui Free-TV ha sostituito iptv-org
    for lcn, fb in fallback_by_lcn.items():
        record = {
            "id": f"freetv:{normalize(fb['name'])}",
            "name": fb["name"],
            "logo": fb.get("logo", ""),
            "categories": ["Discovery" if lcn in (9, 28, 31, 33, 37, 38, 44, 46, 56, 59) else "Italia"],
            "url": fb["url"],
            "lcn": lcn,
            "source": "free-tv",
        }
        if lcn in by_lcn:
            # doppione: Free-TV vince, sostituiamo lo stream iptv-org
            idx = entries.index(by_lcn[lcn])
            entries[idx] = record
            fallback_preferred.append((fb["name"], lcn))
        else:
            entries.append(record)
            matched_lcns.add(lcn)
            fallback_added.append((fb["name"], lcn))
        by_lcn[lcn] = record
    if fallback_added:
        print(f"  Nuovi da Free-TV (assenti in iptv-org): {len(fallback_added)} "
              f"(tra cui il bouquet Discovery se presente)")
    if fallback_preferred:
        print(f"  Preferiti da Free-TV su iptv-org (doppioni): {len(fallback_preferred)}")

    # --- Applica gli override (stream manuali da fonti diverse da iptv-org) ---
    overrides = load_overrides()
    override_applied = []
    if overrides:
        # indicizza le entries esistenti per LCN, cosi' possiamo sostituirle
        by_lcn = {r["lcn"]: r for r in entries}
        for ov in overrides:
            hit = lcn_index.get(normalize(ov["name"]))
            if not hit:
                # l'override punta a un canale che non e' nella tabella LCN: lo segnaliamo
                override_applied.append((ov["name"], None, "nome non in lcn_tivusat.json"))
                continue
            lcn = hit["lcn"]
            record = {
                "id": f"override:{normalize(ov['name'])}",
                "name": hit["label"],   # usa il nome canonico della tabella
                "logo": "",
                "categories": ["Discovery" if lcn in (9, 28, 31, 33, 37, 38, 44, 46, 56, 59) else "Italia"],
                "url": ov["url"],
                "lcn": lcn,
                "override": True,
            }
            if lcn in by_lcn:
                # sostituisce il canale gia' presente con lo stream dell'override
                idx = entries.index(by_lcn[lcn])
                entries[idx] = record
                override_applied.append((hit["label"], lcn, "sostituito"))
            else:
                entries.append(record)
                matched_lcns.add(lcn)
                override_applied.append((hit["label"], lcn, "aggiunto"))
            by_lcn[lcn] = record

    # Ordina i canali mappati per numero LCN
    entries.sort(key=lambda r: r["lcn"])

    # Accoda i canali non mappati in ordine alfabetico, numerandoli da UNMAPPED_START
    unmapped.sort(key=lambda r: r["name"].lower())
    for i, record in enumerate(unmapped):
        record["lcn"] = UNMAPPED_START + i
        entries.append(record)

    # --- Valida gli stream: scarta i canali morti ---
    entries, dropped = validate_entries(entries)
    # ri-ordina dopo la validazione (l'ordine per LCN si mantiene comunque)
    entries.sort(key=lambda r: r["lcn"])

    write_m3u(entries)
    write_report(raw_map, entries, unmapped, it_channels, streams_by_channel)

    print(f"\nFatto. Playlist scritta in {OUTPUT_FILE.name} ({len(entries)} canali vivi).")
    if dropped:
        print(f"  - scartati perche' morti: {len(dropped)}")
    if fallback_added:
        print(f"  - nuovi da Free-TV: {len(fallback_added)}")
        for name, lcn in sorted(fallback_added, key=lambda x: x[1]):
            print(f"      [{lcn}] {name}")
    if fallback_preferred:
        print(f"  - preferiti da Free-TV (doppioni): {len(fallback_preferred)}")
    if override_applied:
        print(f"  - override applicati: {len(override_applied)}")
        for name, lcn, what in override_applied:
            num = lcn if lcn is not None else "?"
            print(f"      [{num}] {name}: {what}")


def write_m3u(entries):
    """Scrive la playlist M3U con il tag tvg-chno (numero LCN)."""
    lines = ['#EXTM3U']
    for r in entries:
        group = r["categories"][0] if r["categories"] else "Italia"
        attrs = (
            f'tvg-id="{r["id"]}" '
            f'tvg-chno="{r["lcn"]}" '
            f'tvg-logo="{r["logo"]}" '
            f'group-title="{group}"'
        )
        # nel titolo metto il numero davanti per leggibilita' nei player che non leggono tvg-chno
        title = f'{r["lcn"]:>3} {r["name"]}'
        lines.append(f'#EXTINF:-1 {attrs},{title}')
        lines.append(r["url"])
    OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(raw_map, entries, unmapped, it_channels, streams_by_channel):
    """Genera un piccolo report markdown sullo stato della generazione."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mapped_count = len(entries) - len(unmapped)

    # canali presenti nella tabella LCN ma non trovati negli stream di oggi
    found_names = {normalize(r["name"]) for r in entries}
    missing = []
    for label in raw_map:
        if normalize(label) not in found_names:
            missing.append((raw_map[label], label))
    missing.sort()

    lines = [
        "# Report playlist tivusat",
        "",
        f"Ultimo aggiornamento: **{now}**",
        "",
        "## Riepilogo",
        "",
        f"- Canali {COUNTRY} nell'anagrafica iptv-org: **{len(it_channels)}**",
        f"- Canali {COUNTRY} con stream disponibile: **{len(streams_by_channel)}**",
        f"- Canali abbinati a un LCN tivusat: **{mapped_count}**",
        f"- Canali senza LCN (accodati da {UNMAPPED_START}): **{len(unmapped)}**",
        "",
    ]

    if missing:
        lines += [
            "## Canali in tabella LCN ma senza stream oggi",
            "",
            "(numero — nome: lo stream potrebbe essere temporaneamente assente)",
            "",
        ]
        lines += [f"- {lcn} — {label}" for lcn, label in missing]
        lines.append("")

    if unmapped:
        lines += [
            "## Canali italiani senza LCN tivusat",
            "",
            "Aggiungi questi nomi a `lcn_tivusat.json` se vuoi assegnare loro un numero:",
            "",
        ]
        lines += [f'- `"{r["name"]}"`' for r in unmapped]
        lines.append("")

    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
