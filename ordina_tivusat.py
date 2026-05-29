#!/usr/bin/env python3
"""
Scarica la playlist IPTV da GitHub, la ordina in base al tvg-chno (LCN Tivùsat)
e stampa il risultato. Nessun canale viene escluso, anche in presenza di commenti
o righe vuote.
"""

import re
import sys
import urllib.request

URL = "https://raw.githubusercontent.com/maginetweb-arch/TVITALIA/refs/heads/main/iptvit.m3u"

def estrai_lcn(extinf):
    """Restituisce il numero LCN come intero, oppure 99999 se assente."""
    m = re.search(r'tvg-chno="(\d+)"', extinf)
    if m:
        return int(m.group(1))
    m = re.search(r'tvg-chno=(\d+)', extinf)
    if m:
        return int(m.group(1))
    return 99999

def main():
    with urllib.request.urlopen(URL) as f:
        contenuto = f.read().decode('utf-8')

    righe = contenuto.splitlines(keepends=True)

    header = []
    canali = []   # lista di tuple (extinf, url)

    i = 0
    while i < len(righe):
        riga = righe[i]
        s = riga.strip()

        # Riga #EXTM3U -> sempre nell'header
        if s.startswith('#EXTM3U'):
            header.append(riga)
            i += 1
            continue

        # Riga #EXTINF -> cattura l'EXTINF e cerca l'URL sulla prossima riga non vuota/non commento
        if s.startswith('#EXTINF'):
            extinf = riga
            i += 1
            # Salta eventuali righe vuote o commenti (righe che iniziano con '#' ma non #EXTINF e non #EXTM3U)
            while i < len(righe) and (righe[i].strip() == '' or (righe[i].strip().startswith('#') and not righe[i].strip().startswith('#EXTINF') and not righe[i].strip().startswith('#EXTM3U'))):
                # possiamo salvare questi commenti nell'header? No, meglio ignorarli per non sporcare, ma se si volesse conservarli andrebbero legati al canale.
                # Per semplicità li scartiamo, dato che non contengono dati essenziali.
                i += 1
            if i < len(righe):
                url = righe[i]
                canali.append((extinf, url))
                i += 1
            else:
                # EXTINF senza URL: lo mettiamo lo stesso con URL vuoto? O lo ignoriamo? In una playlist normale non dovrebbe accadere, ma per sicurezza lo aggiungiamo con url=''
                canali.append((extinf, ''))
            continue

        # Qualunque altra riga (commenti fuori posto, righe vuote prima di un EXTINF) -> la conserviamo nell'header
        # ma solo se non siamo nel bel mezzo di un blocco EXTINF+URL. Siccome il ciclo è sequenziale, qui ci arrivano solo righe che non seguono immediatamente un EXTINF.
        header.append(riga)
        i += 1

    # Ordinamento stabile in base al LCN
    canali_ordinati = sorted(canali, key=lambda x: estrai_lcn(x[0]))

    # Output
    sys.stdout.writelines(header)
    for extinf, url in canali_ordinati:
        sys.stdout.write(extinf)
        sys.stdout.write(url)

    # Messaggio di debug su stderr per non sporcare l'output M3U
    print(f"\n\n[INFO] Canali totali ordinati: {len(canali_ordinati)}", file=sys.stderr)

if __name__ == '__main__':
    main()
