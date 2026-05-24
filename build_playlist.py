#!/usr/bin/env python3
"""
Generatore automatico playlist M3U italiana ordinata per LCN TivùSat.
Combina i flussi di IPTV-org (o altre fonti) con la mappatura ufficiale dei numeri LCN.
"""

import json
import os
import re
import sys
from difflib import SequenceMatcher

import requests

# ---------- CONFIGURAZIONE ----------
# Fonti dati
IPTV_CHANNELS_URL = "https://iptv-org.github.io/api/channels.json?country=IT"
IPTV_STREAMS_URL  = "https://iptv-org.github.io/api/streams.json?country=IT"
TIVUSAT_MAP_FILE  = "tivusat_channels.json"   # file con [{"name":"Rai 1 HD","lcn":1}, ...]
FREE_TV_FILE      = "free_tv.json"            # (opzionale) canali aggiuntivi
OUTPUT_M3U        = "italian_channels_tivusat.m3u"

# Parametri fuzzy matching
SIMILARITY_THRESHOLD = 0.92   # percentuale minima per accettare un match
MIN_CORE_SIMILARITY  = 0.85   # soglia dopo pulizia (senza HD/SD)

# ---------- FUNZIONI DI SUPPORTO ----------
def load_json_from_url(url):
    """Scarica e decodifica un JSON da URL."""
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[ERR] Download fallito {url}: {e}")
        return None

def load_json_file(path):
    """Carica un file JSON locale."""
    if not os.path.exists(path):
        print(f"[WARN] File {path} non trovato, lo salto.")
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERR] Lettura {path}: {e}")
        return None

def normalize_name(name):
    """Rimuove suffissi HD, SD, 4K, ecc. e spazi doppi."""
    n = name.lower()
    n = re.sub(r'\b(hd|sd|4k|fhd|uhd|hevc|h\.264)\b', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n

def similarity(a, b):
    """Similarità semplice tra due stringhe."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def core_similarity(a, b):
    """Similarità dopo normalizzazione (ignorando HD/SD)."""
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()

def fuzzy_match(name, candidates, threshold, min_core):
    """
    Cerca il miglior candidato fra 'candidates' (lista di dict con 'name')
    Restituisce il candidato se supera entrambe le soglie, altrimenti None.
    """
    best_candidate = None
    best_full = 0.0
    for cand in candidates:
        full_sim = similarity(name, cand['name'])
        core_sim = core_similarity(name, cand['name'])
        if full_sim > best_full and core_sim >= min_core:
            best_full = full_sim
            best_candidate = cand
    if best_candidate and best_full >= threshold:
        return best_candidate
    return None

# ---------- FUNZIONE PRINCIPALE ----------
def build():
    print("=== Avvio generazione playlist ===")

    # 1. Carica mappatura LCN TivùSat
    tivusat_list = load_json_file(TIVUSAT_MAP_FILE)
    if not tivusat_list:
        print("[ERR] File tivusat_channels.json indispensabile. Esco.")
        sys.exit(1)
    print(f"Canali TivùSat di riferimento: {len(tivusat_list)}")

    # 2. Scarica flussi e metadati da IPTV-org
    channels_data = load_json_from_url(IPTV_CHANNELS_URL)
    streams_data  = load_json_from_url(IPTV_STREAMS_URL)

    if not channels_data:
        print("[ERR] Impossibile ottenere la lista canali IPTV-org.")
        sys.exit(1)

    # Crea un dizionario id -> url per i flussi
    streams_dict = {}
    if streams_data:
        for s in streams_data:
            ch_id = s.get('channel')
            url = s.get('url')
            if ch_id and url:
                streams_dict[ch_id] = url
    print(f"Flussi IPTV-org disponibili: {len(streams_dict)}")

    # 3. (Opzionale) Carica canali aggiuntivi da Free-TV
    free_tv_list = load_json_file(FREE_TV_FILE)
    if free_tv_list:
        print(f"Free-TV: {len(free_tv_list)} voci caricate.")

    # 4. Combina tutte le fonti (IPTV-org + Free-TV)
    all_channels = []
    # Aggiungo i canali IPTV-org
    for ch in channels_data:
        ch_id = ch.get('id', '')
        name  = ch.get('name', '')
        logo  = ch.get('logo', '')
        url   = streams_dict.get(ch_id, '')
        categories = ch.get('categories', [])
        if not isinstance(categories, list):
            categories = []
        all_channels.append({
            'id': ch_id,
            'name': name,
            'logo': logo,
            'url': url,
            'categories': categories,
            'source': 'iptv-org'
        })

    # Se esiste free_tv_list, la aggiungo (supponendo abbia stessa struttura)
    if free_tv_list:
        for item in free_tv_list:
            # Assicuriamo che i campi obbligatori esistano
            if 'name' not in item:
                continue
            all_channels.append({
                'id': item.get('id', ''),
                'name': item['name'],
                'logo': item.get('logo', ''),
                'url': item.get('url', ''),
                'categories': item.get('categories', []),
                'source': 'free-tv'
            })

    print(f"Canali totali da elaborare: {len(all_channels)}")

    # 5. Mappatura LCN
    matched_entries = []
    lcn_used = set()

    for ch in all_channels:
        match = fuzzy_match(ch['name'], tivusat_list, SIMILARITY_THRESHOLD, MIN_CORE_SIMILARITY)
        if not match:
            continue
        lcn = match['lcn']
        if lcn in lcn_used:
            continue   # evito duplicati LCN
        lcn_used.add(lcn)
        matched_entries.append({
            'name': ch['name'],
            'lcn': lcn,
            'logo': ch['logo'],
            'url': ch['url'],
            'categories': ch['categories']
        })

    # Ordina per LCN
    matched_entries.sort(key=lambda x: int(x['lcn']))
    print(f"Canali con LCN assegnato: {len(matched_entries)}")

    # 6. Scrittura file M3U
    with open(OUTPUT_M3U, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        for entry in matched_entries:
            # Gestione categorie: se la lista è vuota o assente, uso "Italia"
            cats = entry.get('categories')
            if not cats or not isinstance(cats, list) or len(cats) == 0:
                group = "Italia"
            else:
                group = cats[0]   # prendo la prima categoria
            # Costruzione riga EXTINF
            extinf = (
                f'#EXTINF:-1'
                f' tvg-logo="{entry.get("logo", "")}"'
                f' tvg-chno="{entry["lcn"]}"'
                f' group-title="{group}"'
                f',{entry["name"]}\n'
            )
            f.write(extinf)
            url = entry.get('url', '')
            if url:
                f.write(url + '\n')
            else:
                f.write('\n')   # riga vuota se manca URL (canale senza flusso)

    print(f"Playlist generata: {OUTPUT_M3U}")

if __name__ == "__main__":
    build()
