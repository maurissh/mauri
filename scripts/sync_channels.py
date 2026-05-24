import requests
import json
import os
from difflib import SequenceMatcher

# --- Configurazione ---
IPTV_API_CHANNELS = "https://iptv-org.github.io/api/channels.json?country=IT"
IPTV_API_STREAMS  = "https://iptv-org.github.io/api/streams.json?country=IT"
TIVUSAT_FILE      = "tivusat_channels.json"
OUTPUT_FILE       = "italian_channels_tivusat.m3u"
SIMILARITY_THRESHOLD = 0.9  # soglia per il fuzzy matching (0-1)

def load_json_from_url(url):
    """Scarica e restituisce un JSON da un URL."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"ERRORE download {url}: {e}")
        return None

def load_tivusat_channels(filepath):
    """Carica la lista dei canali TivùSat (nome, lcn)."""
    if not os.path.exists(filepath):
        print(f"ERRORE: file {filepath} non trovato.")
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def fuzzy_match(name, candidates, threshold):
    """Trova il miglior match tra 'name' e una lista di candidati usando fuzzy matching."""
    best_score = 0
    best_candidate = None
    for candidate in candidates:
        score = SequenceMatcher(None, name.lower(), candidate['name'].lower()).ratio()
        if score > best_score:
            best_score = score
            best_candidate = candidate
    if best_score >= threshold:
        return best_candidate
    return None

def main():
    print("Avvio sincronizzazione...")

    # 1. Carica canali TivùSat
    tivusat_list = load_tivusat_channels(TIVUSAT_FILE)
    if not tivusat_list:
        print("Nessun canale TivùSat caricato. Uscita.")
        return

    # 2. Scarica canali italiani da IPTV-org
    channels_data = load_json_from_url(IPTV_API_CHANNELS)
    if not channels_data:
        return
    print(f"Canali IPTV Italia: {len(channels_data)}")

    # 3. Scarica flussi streaming
    streams_data = load_json_from_url(IPTV_API_STREAMS)
    if not streams_data:
        print("Impossibile scaricare flussi. Genero playlist senza URL.")
        streams_data = []
    streams_dict = {s['channel']: s['url'] for s in streams_data}
    print(f"Stream disponibili: {len(streams_dict)}")

    # 4. Abbinamento automatico via fuzzy matching
    matched = []
    for ch in channels_data:
        ch_name = ch.get('name', '')
        ch_id = ch.get('id', '')
        logo = ch.get('logo', '')
        stream_url = streams_dict.get(ch_id, '')

        match = fuzzy_match(ch_name, tivusat_list, SIMILARITY_THRESHOLD)
        if match:
            matched.append({
                'name': ch_name,
                'lcn': match['lcn'],
                'logo': logo,
                'url': stream_url
            })
        else:
            print(f"WARNING: nessun match per '{ch_name}'")

    # Ordina per LCN
    matched.sort(key=lambda x: int(x['lcn']))
    print(f"Canali mappati con LCN: {len(matched)}")

    # 5. Genera file M3U
    m3u = "#EXTM3U\n"
    for ch in matched:
        m3u += f'#EXTINF:-1 tvg-logo="{ch["logo"]}" tvg-chno="{ch["lcn"]}",{ch["name"]}\n'
        if ch["url"]:
            m3u += f'{ch["url"]}\n'
        else:
            m3u += '\n'  # riga vuota se manca URL

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(m3u)
    print(f"File '{OUTPUT_FILE}' generato con successo.")

if __name__ == "__main__":
    main()
