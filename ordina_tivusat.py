#!/usr/bin/env python3
"""
Scarica la playlist IPTV, la ordina per tvg-chno (LCN Tivùsat) preservando
TUTTE le righe di commento (es. #KODIPROP, #EXTVLCOPT) associate a ciascun canale.
Nessun canale viene escluso e il DRM rimane funzionante.
"""

import re
import sys
import urllib.request

URL = "https://raw.githubusercontent.com/maginetweb-arch/TVITALIA/refs/heads/main/iptvit.m3u"

def estrai_lcn(blocco):
    """Restituisce il numero LCN dal primo #EXTINF del blocco, o 99999 se assente."""
    for line in blocco:
        if line.startswith('#EXTINF'):
            m = re.search(r'tvg-chno="(\d+)"', line)
            if m:
                return int(m.group(1))
            m = re.search(r'tvg-chno=(\d+)', line)
            if m:
                return int(m.group(1))
    return 99999

def main():
    with urllib.request.urlopen(URL) as f:
        contenuto = f.read().decode('utf-8')

    righe = contenuto.splitlines(keepends=True)

    # Separiamo header (tutto prima del primo #EXTINF) e blocchi canale
    header = []
    blocchi = []   # ogni blocco è una lista di righe: [#EXTINF, (commenti...), URL]

    i = 0
    # Aggiungi tutte le righe prima del primo #EXTINF all'header
    while i < len(righe) and not righe[i].strip().startswith('#EXTINF'):
        header.append(righe[i])
        i += 1

    # Ora processiamo i blocchi canale
    while i < len(righe):
        blocco = []
        # La riga corrente è sicuramente un #EXTINF
        blocco.append(righe[i])
        i += 1

        # Raccogli eventuali righe di commento (iniziano con '#', ma non sono nuovi #EXTINF o #EXTM3U)
        while i < len(righe) and righe[i].strip().startswith('#') and not righe[i].strip().startswith('#EXTINF') and not righe[i].strip().startswith('#EXTM3U'):
            blocco.append(righe[i])
            i += 1

        # Ora ci aspettiamo l'URL (prima riga senza '#')
        if i < len(righe) and not righe[i].strip().startswith('#'):
            blocco.append(righe[i])
            i += 1
        else:
            # Caso anomalo: EXTINF senza URL (ignoriamo o aggiungiamo URL vuoto)
            if i < len(righe) and righe[i].strip().startswith('#'):
                # Potrebbe essere un nuovo EXTINF senza URL precedente? Lo gestiamo forzando un URL vuoto.
                pass  # terremo il blocco senza URL (poi sotto lo aggiungiamo con stringa vuota se assente)

        blocchi.append(blocco)

    # Ordinamento stabile per LCN
    blocchi_ordinati = sorted(blocchi, key=lambda b: estrai_lcn(b))

    # Output
    sys.stdout.writelines(header)
    for blocco in blocchi_ordinati:
        sys.stdout.writelines(blocco)

    print(f"\n[INFO] Canali totali ordinati: {len(blocchi)}", file=sys.stderr)

if __name__ == '__main__':
    main()
