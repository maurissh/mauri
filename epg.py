#!/usr/bin/env python3
"""
epg.py — costruzione di una guida EPG (XMLTV) filtrata e allineata.

Scarica una guida XMLTV completa, tiene solo i programmi dei canali che sono
nella nostra playlist, e RIALLINEA gli id dei canali al tvg-id che usiamo noi.
Questo e' il punto chiave: cosi' la guida si aggancia anche ai canali presi da
Free-TV (che hanno id tipo "freetv:...") e non solo a quelli di iptv-org.

Il collegamento tra il canale dell'EPG e il nostro canale passa per il nome,
abbinato al numero LCN tramite la stessa tabella lcn_tivusat.json usata per gli
stream. Cosi' la logica di matching e' unica e coerente in tutto il progetto.

Usa solo la libreria standard. Gestisce sia XML semplice sia gzip.
"""

import gzip
import io
import re
import urllib.request
import xml.etree.ElementTree as ET


def fetch_epg_raw(url, timeout=90):
    """Scarica la guida XMLTV. Gestisce anche il caso in cui sia gzip."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "tivusat-builder/1.0",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        enc = resp.headers.get("Content-Encoding", "")

    # se e' gzip (per header o per magic number), decomprimi
    if "gzip" in enc or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def build_filtered_epg(epg_url, entries, normalize, lcn_index, output_path):
    """
    Costruisce un epg.xml filtrato e allineato.

    Parametri:
      epg_url     URL della guida XMLTV completa
      entries     lista dei canali finali in playlist (ognuno con 'id','name','lcn')
      normalize   la funzione di normalizzazione nomi (riusata da build_playlist)
      lcn_index   indice { nome_normalizzato: {lcn, label} } gia' costruito
      output_path Path dove salvare epg.xml

    Restituisce un dict di statistiche, oppure None se fallisce (senza
    far crashare lo script chiamante).
    """
    try:
        raw = fetch_epg_raw(epg_url)
    except Exception as e:
        print(f"  (EPG non raggiungibile: {e} — playlist senza guida)")
        return None

    try:
        root = ET.fromstring(raw)
    except Exception as e:
        print(f"  (EPG malformato, impossibile leggerlo: {e})")
        return None

    # 1) Mappa: LCN -> tvg-id che usiamo NOI nella playlist.
    #    Cosi' sappiamo con quale id riscrivere ogni canale dell'EPG.
    lcn_to_our_id = {}
    our_channels = {}  # tvg-id -> nome (per generare i <channel> in uscita)
    for e in entries:
        lcn = e.get("lcn")
        if lcn is not None:
            lcn_to_our_id[lcn] = e["id"]
            our_channels[e["id"]] = e["name"]

    # 2) Scorri i <channel> dell'EPG, abbina il nome al nostro LCN, e costruisci
    #    la mappa: id_originale_EPG -> nostro_tvg-id
    epg_id_remap = {}
    for ch in root.findall("channel"):
        epg_id = ch.get("id", "")
        # un canale puo' avere piu' <display-name>: provali tutti
        names = [dn.text or "" for dn in ch.findall("display-name")]
        matched_lcn = None
        for nm in names:
            hit = lcn_index.get(normalize(nm))
            if hit:
                matched_lcn = hit["lcn"]
                break
        if matched_lcn is not None and matched_lcn in lcn_to_our_id:
            epg_id_remap[epg_id] = lcn_to_our_id[matched_lcn]

    if not epg_id_remap:
        print("  (EPG: nessun canale abbinato — controlla i nomi in lcn_tivusat.json)")
        return None

    # 3) Costruisci il nuovo XMLTV: un <channel> per ogni nostro canale abbinato,
    #    poi i <programme> riscritti con il nostro id.
    new_root = ET.Element("tv")
    new_root.set("generator-info-name", "tivusat-builder")

    # i <channel> in uscita usano il NOSTRO id e nome
    emitted_ids = set()
    for epg_id, our_id in epg_id_remap.items():
        if our_id in emitted_ids:
            continue
        ch_el = ET.SubElement(new_root, "channel", id=our_id)
        dn = ET.SubElement(ch_el, "display-name")
        dn.text = our_channels.get(our_id, our_id)
        emitted_ids.add(our_id)

    # i <programme>: tieni solo quelli dei canali abbinati, riscrivendo l'id
    prog_count = 0
    for prog in root.findall("programme"):
        epg_ch = prog.get("channel", "")
        our_id = epg_id_remap.get(epg_ch)
        if not our_id:
            continue
        prog.set("channel", our_id)   # riscrive l'id col nostro
        new_root.append(prog)
        prog_count += 1

    # 4) Scrivi su file
    tree = ET.ElementTree(new_root)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

    stats = {
        "channels": len(emitted_ids),
        "programmes": prog_count,
    }
    print(f"  EPG filtrato: {stats['channels']} canali, "
          f"{stats['programmes']} programmi -> {output_path.name}")
    return stats
