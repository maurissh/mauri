#!/usr/bin/env python3
"""
build_playlist.py
-----------------
Genera una playlist M3U ordinata per LCN tivusat usando come fonte primaria
la playlist Free-TV/IPTV (playlist_italy.m3u8). Per i canali mancanti può
usare iptv-org come fallback. Integra la guida EPG di iptv-org.

Configurazione rapida:
  - PRIMARY_SOURCE: "free-tv" (predefinita) oppure "iptv-org"
  - EPG_URL: imposta l'URL della guida XMLTV (default iptv-org)
  - MAPPING_FILE: lcn_tivusat.json
  - EPG_MAP_FILE: epg_map.json (facoltativo, per associare nomi a tvg-id EPG)
"""

import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# --- Configurazione ---------------------------------------------------------

PRIMARY_SOURCE = "free-tv"          # "free-tv" o "iptv-org"
IPTV_ORG_FALLBACK_ENABLED = True    # solo se PRIMARY_SOURCE="free-tv"

# URL EPG (guida elettronica ai programmi)
EPG_URL = "https://iptv-org.github.io/epg/guides/it.xml"
# EPG alternativo (es. epgshare01), decommenta per usarlo:
# EPG_URL = "https://epgshare01.online/epgshare01/epg_ripper_IT1.xml.gz"

# Fonti dati
FREE_TV_URL = "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_italy.m3u8"
API_BASE = "https://iptv-org.github.io/api"
CHANNELS_URL = f"{API_BASE}/channels.json"
STREAMS_URL = f"{API_BASE}/streams.json"

COUNTRY = "IT"
ROOT = Path(__file__).resolve().parent
MAPPING_FILE = ROOT / "lcn_tivusat.json"
OUTPUT_FILE = ROOT / "tivusat.m3u"
REPORT_FILE = ROOT / "report.md"
OVERRIDES_FILE = ROOT / "overrides.json"
EPG_MAP_FILE = ROOT / "epg_map.json"   # facoltativo: {"Rai 1": "Rai1.it", ...}

UNMAPPED_START = 9000


# --- Utility ----------------------------------------------------------------

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "tivusat-builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "tivusat-builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")

def parse_m3u(text):
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
    if not MAPPING_FILE.exists():
        print(f"ERRORE: manca il file di mapping {MAPPING_FILE}", file=sys.stderr)
        sys.exit(1)
    raw = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    index = {}
    for channel_name, lcn in raw.items():
        index[normalize(channel_name)] = {"lcn": int(lcn), "label": channel_name}
    return raw, index

def load_overrides():
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

def load_epg_map():
    """
    Carica un mapping esplicito nome canale -> tvg-id EPG.
    Il file epg_map.json è facoltativo. Se assente, restituisce {}.
    """
    if not EPG_MAP_FILE.exists():
        return {}
    raw = json.loads(EPG_MAP_FILE.read_text(encoding="utf-8"))
    # normalizziamo le chiavi per un lookup più robusto
    return {normalize(k): v for k, v in raw.items()}


# --- Logica EPG -------------------------------------------------------------

def build_epg_id_map(lcn_index, raw_map):
    """
    Crea un dizionario { nome_normalizzato: tvg-id_epg } basato su:
    - corrispondenze note tra nomi LCN e tvg-id di iptv-org (es. "rai 1" -> "Rai1.it")
    - il file epg_map.json (prioritario)
    - regole automatiche di fallback (es. nomelcanal.it)
    """
    # Mappatura statica di base (copre la maggior parte dei canali italiani)
    base_map = {
        "rai1": "Rai1.it", "rai2": "Rai2.it", "rai3": "Rai3.it",
        "rete4": "Retequattro.it", "canale5": "Canale5.it", "italia1": "Italia1.it",
        "la7": "La7.it", "la7d": "La7d.it",
        "tv8": "TV8.it", "nove": "Nove.it",
        "real time": "RealTime.it", "dmax": "DMAX.it", "frisbee": "Frisbee.it",
        "supertennis": "SuperTennis.it", "radioitalia": "RadioItaliaTV.it",
        "radio 105": "Radio105TV.it", "r101": "R101TV.it",
        "virgin radio": "VirginRadioTV.it",
        "mtv": "MTV.it", "mtv music": "MTVMusic.it",
        "sky tg24": "SkyTG24.it", "tgcom24": "TgCom24.it",
        "rai news 24": "RaiNews24.it", "rainews24": "RaiNews24.it",
        "rai sport": "RaiSport.it", "rai sport+": "RaiSportPiù.it",
        "italia 2": "Italia2.it", "cielo": "Cielo.it", "tv2000": "TV2000.it",
        "focus": "Focus.it", "giallo": "Giallo.it", "top crime": "TopCrime.it",
        "la5": "La5.it", "boing": "Boing.it", "cartoonito": "Cartoonito.it",
        "k2": "K2.it", "deakids": "DeAKids.it", "deajunior": "DeAJunior.it",
    }
    # Integriamo con le chiavi normalizzate della tabella LCN
    epg_map = {}
    for norm_name, info in lcn_index.items():
        # prima guarda se il nome è nel mapping base
        if norm_name in base_map:
            epg_map[norm_name] = base_map[norm_name]
        else:
            # fallback: genera "NomeCanale.it" prendendo il label pulito
            label = info["label"]
            # rimuovi spazi, apostrofi, ecc.
            clean = re.sub(r"[^a-zA-Z0-9]+", "", label)
            epg_map[norm_name] = f"{clean}.it"

    # Il file epg_map.json sovrascrive i valori precedenti
    file_map = load_epg_map()
    for norm_name, epg_id in file_map.items():
        epg_map[norm_name] = epg_id

    return epg_map


# --- Costruzione playlist ---------------------------------------------------

def build():
    raw_map, lcn_index = load_mapping()
    overrides = load_overrides()
    epg_id_map = build_epg_id_map(lcn_index, raw_map)

    entries = []          # canali con LCN
    unmapped = []         # canali senza LCN
    matched_lcns = set()

    # 1) Fonte primaria
    if PRIMARY_SOURCE == "free-tv":
        print("Fonte primaria: Free-TV/IPTV")
        free_entries = fetch_free_tv_entries()
        for fe in free_entries:
            hit = lcn_index.get(normalize(fe["name"]))
            record = {
                "name": fe["name"],
                "logo": fe.get("logo", ""),
                "categories": ["Italia"],
                "url": fe["url"],
                "source": "free-tv",
            }
            if hit:
                lcn = hit["lcn"]
                if lcn not in matched_lcns:
                    matched_lcns.add(lcn)
                    record["lcn"] = lcn
                    record["name"] = hit["label"]   # nome canonico
                    # assegna tvg-id EPG
                    norm = normalize(hit["label"])
                    record["tvg_id"] = epg_id_map.get(norm, f"free-tv:{norm}")
                    entries.append(record)
            else:
                # canale senza LCN: assegniamo un id fittizio per EPG
                norm = normalize(fe["name"])
                record["tvg_id"] = f"free-tv:{norm}"
                unmapped.append(record)

        print(f"Free-TV: {len(free_entries)} voci, "
              f"{len(entries)} abbinate a un LCN, "
              f"{len(unmapped)} senza LCN")

        # 2) Fallback iptv-org per i LCN mancanti
        if IPTV_ORG_FALLBACK_ENABLED:
            missing_lcns = set(raw_map.values()) - matched_lcns
            if missing_lcns:
                print("Cerco i LCN mancanti su iptv-org...")
                it_channels, streams_by_channel = load_iptv_org_data()
                for cid, ch in it_channels.items():
                    ch_streams = streams_by_channel.get(cid)
                    if not ch_streams:
                        continue
                    stream = ch_streams[0]
                    name = ch.get("name", cid)
                    hit = lcn_index.get(normalize(name))
                    if not hit:
                        # prova con alt_names
                        for alt in ch.get("alt_names", []):
                            hit = lcn_index.get(normalize(alt))
                            if hit:
                                break
                    if hit and hit["lcn"] in missing_lcns and hit["lcn"] not in matched_lcns:
                        lcn = hit["lcn"]
                        record = {
                            "name": hit["label"],
                            "logo": ch.get("logo", ""),
                            "categories": ch.get("categories", ["Italia"]),
                            "url": stream["url"],
                            "lcn": lcn,
                            "source": "iptv-org",
                            "tvg_id": cid,   # iptv-org fornisce già l'id EPG
                        }
                        entries.append(record)
                        matched_lcns.add(lcn)
                print(f"  Aggiunti da iptv-org: {len(entries) - len(matched_lcns)} canali")

    else:   # PRIMARY_SOURCE == "iptv-org"
        print("Fonte primaria: iptv-org")
        it_channels, streams_by_channel = load_iptv_org_data()
        for cid, ch in it_channels.items():
            ch_streams = streams_by_channel.get(cid)
            if not ch_streams:
                continue
            stream = ch_streams[0]
            name = ch.get("name", cid)
            hit = lcn_index.get(normalize(name))
            if not hit:
                for alt in ch.get("alt_names", []):
                    hit = lcn_index.get(normalize(alt))
                    if hit:
                        break
            record = {
                "name": hit["label"] if hit else name,
                "logo": ch.get("logo", ""),
                "categories": ch.get("categories", ["Italia"]),
                "url": stream["url"],
                "source": "iptv-org",
                "tvg_id": cid,
            }
            if hit:
                lcn = hit["lcn"]
                if lcn not in matched_lcns:
                    matched_lcns.add(lcn)
                    record["lcn"] = lcn
                    entries.append(record)
            else:
                unmapped.append(record)

        print(f"iptv-org: {len(it_channels)} canali, "
              f"{len(entries)} abbinate a un LCN, "
              f"{len(unmapped)} senza LCN")

        # Fallback Free-TV per LCN mancanti (comportamento originale)
        print("Controllo la seconda fonte (Free-TV) per i canali mancanti...")
        fallback = load_fallback_by_lcn_legacy(lcn_index, matched_lcns)
        for lcn, fb in fallback.items():
            if lcn not in matched_lcns:
                record = {
                    "name": fb["name"],
                    "logo": fb.get("logo", ""),
                    "categories": ["Discovery" if lcn in (9,28,31,33,37,38,44,46,56,59) else "Italia"],
                    "url": fb["url"],
                    "lcn": lcn,
                    "source": "free-tv",
                    "tvg_id": f"free-tv:{normalize(fb['name'])}",
                }
                entries.append(record)
                matched_lcns.add(lcn)
        if fallback:
            print(f"  Aggiunti da Free-TV: {len(fallback)} canali")

    # 3) Applica override (sostituisce o aggiunge canali)
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
                "name": hit["label"],
                "logo": "",
                "categories": ["Discovery" if lcn in (9,28,31,33,37,38,44,46,56,59) else "Italia"],
                "url": ov["url"],
                "lcn": lcn,
                "override": True,
                "source": "override",
                "tvg_id": epg_id_map.get(normalize(hit["label"]), f"override:{normalize(ov['name'])}"),
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
    entries.sort(key=lambda r: r.get("lcn", 99999))
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


# --- Funzioni di supporto per le fonti --------------------------------------

def fetch_free_tv_entries():
    text = fetch_text(FREE_TV_URL)
    parsed = parse_m3u(text)
    if len(parsed) < 10:
        print(f"ERRORE: playlist Free-TV malformata ({len(parsed)} voci)")
        sys.exit(1)
    for entry in parsed:
        entry["name"] = entry["name"].replace("Ⓖ", "").strip()
    return parsed

def load_iptv_org_data():
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

def load_fallback_by_lcn_legacy(lcn_index, matched_lcns):
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
    lines = [
        '#EXTM3U',
        f'#EXTVLCOPT:url-tvg="{EPG_URL}"',
    ]
    for r in entries:
        group = r.get("categories", ["Italia"])[0]
        tvg_id = r.get("tvg_id", r.get("id", ""))
        attrs = (
            f'tvg-id="{tvg_id}" '
            f'tvg-chno="{r["lcn"]}" '
            f'tvg-logo="{r.get("logo", "")}" '
            f'group-title="{group}"'
        )
        title = f'{r["lcn"]:>3} {r["name"]}'
        lines.append(f'#EXTINF:-1 {attrs},{title}')
        lines.append(r["url"])
    OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

def write_report(raw_map, entries, unmapped, override_applied, source):
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
        f"EPG: {EPG_URL}",
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
        ]
        lines += [f"- {lcn} — {label}" for lcn, label in missing]
        lines.append("")
    if unmapped:
        lines += [
            "## Canali senza LCN tivusat",
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
