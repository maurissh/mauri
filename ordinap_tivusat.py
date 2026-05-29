#!/usr/bin/env python3
"""
Scarica la playlist IPTV da GitHub, la ordina in base al tvg-chno (LCN Tivùsat)
e stampa il risultato. I canali senza LCN finiscono in coda, nessuno viene escluso.
"""

import re
import sys
import urllib.request

URL = "https://raw.githubusercontent.com/maginetweb-arch/TVITALIA/refs/heads/main/iptvit.m3u"

def estrai_lcn(extinf):
    """Restituisce il numero LCN come intero, oppure 99999 se assente."""
    # cerca tvg-chno tra virgolette: tvg-chno="123"
    m = re.search(r'tvg-chno="(\d+)"', extinf)
    if m:
        return int(m.group(1))
    # cerca senza virgolette: tvg-chno=123
    m = re.search(r'tvg-chno=(\d+)', extinf)
    if m:
        return int(m.group(1))
    return 99999  # valore molto alto -> va in fondo

def main():
    # Scarica la playlist
    with urllib.request.urlopen(URL) as f:
        contenuto = f.read().decode('utf-8')

    righe = contenuto.splitlines(keepends=True)  # mantiene i \n

    header = []
    canali = []   # lista di tuple (riga_extinf, riga_url)
    i = 0
    while i < len(righe):
        riga = righe[i]
        if riga.startswith('#EXTINF'):
            extinf = riga
            i += 1
            if i < len(righe):
                url = righe[i]
                canali.append((extinf, url))
                i += 1
            else:
                break
        elif riga.startswith('#EXTM3U') or riga.startswith('#') or riga.strip() == '':
            header.append(riga)
            i += 1
        else:
            # riga anomala (senza EXTINF), la mettiamo nell'header per sicurezza
            header.append(riga)
            i += 1

    # Ordinamento stabile in base al LCN
    canali_ordinati = sorted(canali, key=lambda x: estrai_lcn(x[0]))

    # Output: prima l'header, poi i canali ordinati
    sys.stdout.writelines(header)
    for extinf, url in canali_ordinati:
        sys.stdout.write(extinf)
        sys.stdout.write(url)

if __name__ == '__main__':
    main()
