#!/usr/bin/env python3
"""
build_playlist.py
-----------------
Scarica i canali italiani da una fonte primaria (Free-TV/IPTV o iptv-org),
li abbina ai numeri LCN della piattaforma tivusat tramite una tabella di
mapping locale (lcn_tivusat.json) e genera una playlist M3U ordinata per
numero di canale.

Non richiede dipendenze esterne: usa solo la libreria standard di Python 3.

Fonti utilizzabili:
  - https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_italy.m3u8
  - https://iptv-org.github.io/api/          (channels.json, streams.json)
"""

import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# --- Configurazione ---------------------------------------------------------

# Scegli la fonte primaria: "free-tv" oppure "iptv-org"
PRIMARY_SOURCE = "free-tv"

# Se usi "free-tv" come primaria, puoi attivare iptv-org come fonte secondaria
# per coprire gli LCN che Free-TV non ha fornito.
IPTV_ORG_FALLBACK_ENABLED = True

# Parametri per iptv-org (usati sia come primaria sia come secondaria)
API_BASE = "https://iptv-org.github.io/api"
CHANNELS_URL = f"{API_BASE}/channels.json"
STREAMS_URL = f"{API_BASE}/streams.json"

COUNTRY = "IT"  # codice ISO 3166-1 alpha-2 del paese da estrarre

# Playlist di Free-TV (usata come primaria o come fallback a seconda di PRIMARY_SOURCE)
FREE_TV_URL = "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_italy.m3u8"

ROOT = Path(__file__).resolve().parent
MAPPING_FILE = ROOT / "lcn_tivusat.json"
OUTPUT_FILE = ROOT / "tivusat.m3u"
REPORT_FILE = ROOT / "report.md"
OVERRIDES_FILE = ROOT / "overrides.json"

UNMAPPED_START = 9000


# --- Utility ----------------------------------------------------------------

def fetch_json(url):
    """Scarica e decodifica un file JSON da un URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "tivusat-builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_text(url):
    """Scarica testo grezzo da un URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "tivusat-builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_m3u(text):
    """
    Parsa una playlist M3U e restituisce una lista di dict {name, logo, url}.
    """
    entries = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            tvg_name = re.search(r'tvg-name="([^"]*)"', line)
            logo = re.search(r'tvg-logo="([^"]*)"', line)
            after_comma = line.split(",", 1)
            name = (tvg_name.group(1) if tvg_name
                    else (after_comma[1].strip() if len(after_comma) > 1 else ""))
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


def normalize(name):
    """
    Normalizza il nome di un canale per il confronto.
    """
    if not name:
        return ""
    name = re.sub(r"\([^)]*\)", " ", name)
    name = re.sub(r"\[[^\]]*\]", " ", name)
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    for token in (" hd", " fhd", " uhd", " 4k", " sd", " full hd"):
        name = name.replace(token, " ")
    name = re.sub(r"[^a-z0-9]+", "", name)
    return name


# --- Caricamento tabelle ----------------------------------------------------

def load_mapping():
    """Carica la tabella LCN tivusat e costruisce un indice normalizzato."""
    if not MAPPING_FILE.exists():
        print(f"ERRORE: manca il file di mapping {MAPPING_FILE}", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    index = {}
    for channel_name, lcn in raw.items():
        index[normalize(channel_name)] = {"lcn": int(lcn), "label": channel_name}
    return raw, index


def load_overrides():
    """
    Carica gli stream manuali da overrides.json, se presente.
    Restituisce una lista di dict { "name", "url" }.
    """
    if not OVERRIDES_FILE.exists():
        return []
    raw = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
    result = []
    for name, url in raw.items():
        if name.startswith("_"):
            continue
        if url:
            result.append({"name": name, "url": url})
    return result


# --- Funzioni per le fonti --------------------------------------------------

def fetch_free_tv_entries(lcn_index):
    """
    Scarica e restituisce TUTTE le entry della playlist Free-TV,
    già ripulite dal carattere 'Ⓖ' (se presente).
    Ogni entry è un dict: {name, logo, url}.
    """
    try:
        text = fetch_text(FREE_TV_URL)
    except Exception as e:
        print(f"ERRORE: impossibile scaricare Free-TV: {e}")
        sys.exit(1)

    parsed = parse_m3u(text)
    if len(parsed) < 10:
        print(f"ERRORE: playlist Free-TV malformata ({len(parsed)} voci)")
        sys.exit(1)

    for entry in parsed:
        entry["name"] = entry["name"].replace("Ⓖ", "").strip()
    return parsed


def fetch_iptv_org_entries(it_channels, streams_by_channel, lcn_index):
    """
    Dati i dizionari degli stream e canali iptv-org, restituisce una lista
    di dict analoghi a quelli restituiti da fetch_free_tv_entries.
    """
    entries = []
    for cid, ch in it_channels.items():
        ch_streams = streams_by_channel.get(cid)
        if not ch_streams:
            continue
        stream = ch_streams[0]
        name = ch.get("name", cid)
        entries.append({
            "name": name,
            "logo": ch.get("logo", ""),
            "url": stream["url"],
        })
    return entries


def load_iptv_org_data():
    """Scarica e prepara i dati da iptv-org."""
    channels = fetch_json(CHANNELS_URL)
    streams = fetch_json(STREAMS_URL)

    it_channels = {
        ch["id"]: ch
        for ch in channels
        if ch.get("country") == COUNTRY and not ch.get("closed")
    }
    streams_by_channel = {}
    for st in streams:
        cid = st.get("channel")
        url = st.get("url")
        if not cid or not url or cid not in it_channels:
            continue
        streams_by_channel.setdefault(cid, []).append(st)
    return it_channels, streams_by_channel


# --- Costruzione playlist ---------------------------------------------------

def build():
    raw_map, lcn_index = load_mapping()
    overrides = load_overrides()

    entries = []          # canali con LCN
    unmapped = []         # canali senza LCN
    matched_lcns = set()

    # 1) Fonte primaria
    if PRIMARY_SOURCE == "free-tv":
        print("Fonte primaria: Free-TV/IPTV")
        free_entries = fetch_free_tv_entries(lcn_index)
        for fe in free_entries:
            hit = lcn_index.get(normalize(fe["name"]))
            record = {
                "id": f"freetv:{normalize(fe['name'])}",
                "name": fe["name"],
                "logo": fe.get("logo", ""),
                "categories": ["Italia"],
                "url": fe["url"],
                "source": "free-tv",
            }
            if hit:
                record["lcn"] = hit["lcn"]
                # se LCN già presente, teniamo la prima occorrenza
                if hit["lcn"] not in matched_lcns:
                    matched_lcns.add(hit["lcn"])
                    record["name"] = hit["label"]   # nome canonico dalla tabella
                    entries.append(record)
            else:
                unmapped.append(record)

        print(f"Free-TV: {len(free_entries)} voci, "
              f"{len(entries)} abbinate a un LCN, "
              f"{len(unmapped)} senza LCN")

        # 2) Eventuale fonte secondaria iptv-org per i LCN mancanti
        if IPTV_ORG_FALLBACK_ENABLED:
            missing_lcns = set(raw_map.values()) - matched_lcns
            if missing_lcns:
                print("Cerco i LCN mancanti su iptv-org...")
                it_channels, streams_by_channel = load_iptv_org_data()
                iptv_entries = fetch_iptv_org_entries(it_channels, streams_by_channel, lcn_index)
                added = 0
                for ie in iptv_entries:
                    hit = lcn_index.get(normalize(ie["name"]))
                    if hit and hit["lcn"] in missing_lcns and hit["lcn"] not in matched_lcns:
                        record = {
                            "id": f"iptvorg:{normalize(ie['name'])}",
                            "name": hit["label"],
                            "logo": ie.get("logo", ""),
                            "categories": ["Italia"],
                            "url": ie["url"],
                            "lcn": hit["lcn"],
                            "source": "iptv-org",
                        }
                        entries.append(record)
                        matched_lcns.add(hit["lcn"])
                        added += 1
                print(f"  Aggiunti da iptv-org: {added} canali")

    else:  # PRIMARY_SOURCE == "iptv-org" (comportamento originale)
        print("Fonte primaria: iptv-org")
        it_channels, streams_by_channel = load_iptv_org_data()
        iptv_entries = fetch_iptv_org_entries(it_channels, streams_by_channel, lcn_index)

        for ie in iptv_entries:
            hit = lcn_index.get(normalize(ie["name"]))
            record = {
                "id": f"iptvorg:{normalize(ie['name'])}",
                "name": ie["name"],
                "logo": ie.get("logo", ""),
                "categories": ["Italia"],
                "url": ie["url"],
                "source": "iptv-org",
            }
            if hit:
                record["lcn"] = hit["lcn"]
                if hit["lcn"] not in matched_lcns:
                    matched_lcns.add(hit["lcn"])
                    record["name"] = hit["label"]
                    entries.append(record)
            else:
                unmapped.append(record)

        print(f"iptv-org: {len(iptv_entries)} canali, "
              f"{len(entries)} abbinate a un LCN, "
              f"{len(unmapped)} senza LCN")

        # Fallback Free-TV per i LCN mancanti (comportamento originale)
        print("Controllo la seconda fonte (Free-TV) per i canali mancanti...")
        fallback = load_fallback_by_lcn_legacy(lcn_index, matched_lcns)
        for lcn, fb in fallback.items():
            if lcn not in matched_lcns:
                entries.append({
                    "id": f"freetv:{normalize(fb['name'])}",
                    "name": fb["name"],
                    "logo": fb.get("logo", ""),
                    "categories": ["Discovery" if lcn in (9, 28, 31, 33, 37, 38, 44, 46, 56, 59) else "Italia"],
                    "url": fb["url"],
                    "lcn": lcn,
                    "source": "free-tv",
                })
                matched_lcns.add(lcn)
        if fallback:
            print(f"  Aggiunti da Free-TV: {len(fallback)} canali")

    # 3) Applica gli override
    override_applied = []
    if overrides:
        by_lcn = {r["lcn"]: r for r in entries if "lcn" in r}
        for ov in overrides:
            hit = lcn_index.get(normalize(ov["name"]))
            if not hit:
                override_applied.append((ov["name"], None, "nome non in tabella"))
                continue
            lcn = hit["lcn"]
            record = {
                "id": f"override:{normalize(ov['name'])}",
                "name": hit["label"],
                "logo": "",
                "categories": ["Discovery" if lcn in (9, 28, 31, 33, 37, 38, 44, 46, 56, 59) else "Italia"],
                "url": ov["url"],
                "lcn": lcn,
                "override": True,
            }
            if lcn in by_lcn:
                idx = entries.index(by_lcn[lcn])
                entries[idx] = record
                override_applied.append((hit["label"], lcn, "sostituito"))
            else:
                entries.append(record)
                matched_lcns.add(lcn)
                override_applied.append((hit["label"], lcn, "aggiunto"))
            by_lcn[lcn] = record

    # 4) Ordina e accoda gli unmapped
    entries.sort(key=lambda r: r["lcn"])
    unmapped.sort(key=lambda r: r["name"].lower())
    for i, rec in enumerate(unmapped):
        rec["lcn"] = UNMAPPED_START + i
        entries.append(rec)

    # 5) Scrivi output
    write_m3u(entries)
    write_report(raw_map, entries, unmapped, override_applied, PRIMARY_SOURCE)

    print(f"\nFatto. Playlist scritta in {OUTPUT_FILE.name} ({len(entries)} canali).")
    print(f"  - con LCN tivusat: {len(entries) - len(unmapped)}")
    print(f"  - senza LCN (accodati): {len(unmapped)}")
    if override_applied:
        print(f"  - override applicati: {len(override_applied)}")
        for name, lcn, what in override_applied:
            num = lcn if lcn is not None else "?"
            print(f"      [{num}] {name}: {what}")


def load_fallback_by_lcn_legacy(lcn_index, matched_lcns):
    """
    Versione legacy del fallback Free-TV (usata quando la primaria è iptv-org).
    Restituisce un dict { lcn: {name, logo, url} } per i canali che interessano.
    """
    try:
        text = fetch_text(FREE_TV_URL)
    except Exception as e:
        print(f"  (fallback non raggiungibile: {e})")
        return {}
    parsed = parse_m3u(text)
    if len(parsed) < 10:
        print(f"  (fallback malformato: solo {len(parsed)} voci)")
        return {}
    by_lcn = {}
    for entry in parsed:
        clean = entry["name"].replace("Ⓖ", "").strip()
        hit = lcn_index.get(normalize(clean))
        if hit:
            lcn = hit["lcn"]
            if lcn not in by_lcn:
                by_lcn[lcn] = {
                    "name": hit["label"],
                    "logo": entry["logo"],
                    "url": entry["url"],
                }
    return by_lcn


# --- Scrittura file ---------------------------------------------------------

def write_m3u(entries):
    """Scrive la playlist M3U con il tag tvg-chno (numero LCN)."""
    lines = ['#EXTM3U']
    for r in entries:
        group = r.get("categories", ["Italia"])[0]
        attrs = (
            f'tvg-id="{r["id"]}" '
            f'tvg-chno="{r["lcn"]}" '
            f'tvg-logo="{r["logo"]}" '
            f'group-title="{group}"'
        )
        title = f'{r["lcn"]:>3} {r["name"]}'
        lines.append(f'#EXTINF:-1 {attrs},{title}')
        lines.append(r["url"])
    OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(raw_map, entries, unmapped, override_applied, source):
    """Genera un report markdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mapped_count = len(entries) - len(unmapped)

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
        f"Fonte primaria: **{source}**",
        "",
        "## Riepilogo",
        "",
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
            "## Canali senza LCN tivusat",
            "",
            "Aggiungi questi nomi a `lcn_tivusat.json` se vuoi assegnare loro un numero:",
            "",
        ]
        lines += [f'- `"{r["name"]}"`' for r in unmapped]
        lines.append("")

    if override_applied:
        lines += [
            "## Override applicati",
            "",
        ]
        lines += [f"- [{lcn}] {name}: {what}" for name, lcn, what in override_applied]
        lines.append("")

    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
