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
from datetime import datetime, timezone
from pathlib import Path

# --- Configurazione ---------------------------------------------------------

API_BASE = "https://iptv-org.github.io/api"
CHANNELS_URL = f"{API_BASE}/channels.json"
STREAMS_URL = f"{API_BASE}/streams.json"

COUNTRY = "IT"  # codice ISO 3166-1 alpha-2 del paese da estrarre

ROOT = Path(__file__).resolve().parent
MAPPING_FILE = ROOT / "lcn_tivusat.json"
OUTPUT_FILE = ROOT / "tivusat.m3u"
REPORT_FILE = ROOT / "report.md"

# Numero da cui partire per i canali italiani NON presenti nella tabella LCN.
# Vengono accodati in fondo, in ordine alfabetico, a partire da questo valore.
UNMAPPED_START = 9000


# --- Utility ----------------------------------------------------------------

def fetch_json(url):
    """Scarica e decodifica un file JSON da un URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "tivusat-builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


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

    # Ordina i canali mappati per numero LCN
    entries.sort(key=lambda r: r["lcn"])

    # Accoda i canali non mappati in ordine alfabetico, numerandoli da UNMAPPED_START
    unmapped.sort(key=lambda r: r["name"].lower())
    for i, record in enumerate(unmapped):
        record["lcn"] = UNMAPPED_START + i
        entries.append(record)

    write_m3u(entries)
    write_report(raw_map, entries, unmapped, it_channels, streams_by_channel)

    print(f"\nFatto. Playlist scritta in {OUTPUT_FILE.name} ({len(entries)} canali).")
    print(f"  - con LCN tivusat: {len(entries) - len(unmapped)}")
    print(f"  - senza LCN (accodati): {len(unmapped)}")


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
