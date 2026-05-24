import requests
import json
import os
import re
from difflib import SequenceMatcher

# --- Configurazione ---
IPTV_API_CHANNELS = "https://iptv-org.github.io/api/channels.json?country=IT"
IPTV_API_STREAMS  = "https://iptv-org.github.io/api/streams.json?country=IT"
TIVUSAT_FILE      = "tivusat_channels.json"
OUTPUT_FILE       = "italian_channels_tivusat.m3u"
SIMILARITY_THRESHOLD = 0.92          # soglia percentuale (0-1)
MIN_CORE_SIMILARITY  = 0.85          # soglia per il nome base (senza HD/SD)

def load_json_from_url(url):
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"ERRORE download {url}: {e}")
        return None

def load_tivusat_channels(filepath):
    if not os.path.exists(filepath):
        print(f"ERRORE: file {filepath} non trovato.")
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def normalize_name(name):
    """Rimuove suffissi HD, SD, 4K, FHD e spazi duplicati."""
    name = name.lower()
    name = re.sub(r'\b(hd|sd|4k|fhd|uhd|h\.264|hevc)\b', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def core_similarity(name1, name2):
    """Similarità dopo normalizzazione dei nomi."""
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)
    return SequenceMatcher(None, n1, n2).ratio()

def fuzzy_match(name, candidates, threshold, min_core):
    """
    Cerca il miglior candidato combinando:
    1. Similarità completa (name intero)
    2. Similarità sul nome base (senza HD/SD)
    Accetta solo se entrambe le condizioni sono sopra le soglie.
    """
    best = None
    best_full = 0
    best_core = 0
    for cand in candidates:
        full_sim = SequenceMatcher(None, name.lower(), cand['name'].lower()).ratio()
        core_sim = core_similarity(name, cand['name'])
        if full_sim > best_full and core_sim >= min_core:
            best_full = full_sim
            best_core = core_sim
            best = cand
    if best and best_full >= threshold:
        return best
    return None

def main():
    print("Avvio sincronizzazione...")

    # 1. Carica elenco TivùSat (nome, lcn)
    tivusat_list = load_tivusat_channels(TIVUSAT_FILE)
    if not tivusat_list:
        print("Nessun canale TivùSat caricato.")
        return
    print(f"Canali TivùSat caricati: {len(tivusat_list)}")

    # 2. Scarica canali IPTV Italia
    channels_data = load_json_from_url(IPTV_API_CHANNELS)
    if not channels_data:
        return
    print(f"Canali IPTV Italia: {len(channels_data)}")

    # 3. Scarica flussi streaming
    streams_data = load_json_from_url(IPTV_API_STREAMS)
    streams_dict = {}
    if streams_data:
        for s in streams_data:
            ch_id = s.get('channel', '')
            url = s.get('url', '')
            if ch_id and url:
                streams_dict[ch_id] = url
    print(f"Stream disponibili: {len(streams_dict)}")

    # 4. Mappatura con fuzzy matching migliorato
    matched = []
    used_lcns = set()
    for ch in channels_data:
        ch_id = ch.get('id', '')
        ch_name = ch.get('name', '')
        logo = ch.get('logo', '')
        stream_url = streams_dict.get(ch_id, '')

        match = fuzzy_match(ch_name, tivusat_list, SIMILARITY_THRESHOLD, MIN_CORE_SIMILARITY)
        if not match:
            print(f"WARNING: nessun match per '{ch_name}'")
            continue

        lcn = match['lcn']
        if lcn in used_lcns:
            print(f"INFO: LCN {lcn} già assegnato, ignoro '{ch_name}'")
            continue

        used_lcns.add(lcn)
        matched.append({
            'name': ch_name,        # nome originale IPTV
            'lcn': lcn,
            'logo': logo,
            'url': stream_url
        })
        if not stream_url:
            print(f"AVVISO: nessun URL per '{ch_name}'")

    # Ordina per LCN
    matched.sort(key=lambda x: int(x['lcn']))
    print(f"Canali mappati senza duplicati: {len(matched)}")

    # 5. Genera file M3U valido
    m3u = "#EXTM3U\n"
    for ch in matched:
        extinf = f'#EXTINF:-1 tvg-logo="{ch["logo"]}" tvg-chno="{ch["lcn"]}",{ch["name"]}\n'
        url_line = ch['url'] + '\n' if ch['url'] else '\n'
        m3u += extinf + url_line

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(m3u)
    print(f"File '{OUTPUT_FILE}' generato con successo.")

if __name__ == "__main__":
    main()
