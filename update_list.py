#!/usr/bin/env python3
"""
Riordina una playlist IPTV secondo la numerazione ufficiale Tivùsat (LCN).

Strategia di match (in ordine di priorità):
  1. tvg-id  -> identificatore stabile, non dipende dal nome visualizzato
  2. nome normalizzato -> fallback se il tvg-id non è in tabella

Per ogni canale riconosciuto viene riscritto tvg-chno con il numero Tivùsat,
così i player che ordinano per tvg-chno mostrano l'ordine corretto.
I canali non riconosciuti vengono messi in fondo, mantenendo il loro ordine.
"""

import urllib.request
import urllib.error
import re
import sys

URL_SORGENTE = "https://raw.githubusercontent.com/maginetweb-arch/TVITALIA/refs/heads/main/iptvit.m3u"
FILE_OUTPUT = "tivusat_ordinato.m3u"
FILE_LOCALE_FALLBACK = "iptvit.m3u"   # usato se la rete fallisce

# ---------------------------------------------------------------------------
# Tabella Tivùsat per tvg-id (chiave principale, affidabile).
# tvg-id della sorgente  ->  numero LCN Tivùsat
# ---------------------------------------------------------------------------
LCN_PER_ID = {
    "Rai1.it": 1, "Rai2.it": 2, "Rai3.it": 3,
    "Rete4.it": 4, "Canale5.it": 5, "Italia1.it": 6,
    "La7.it": 7, "Tv8.it": 8, "Nove.it": 9,
    "Rai4.it": 10, "Iris.it": 11, "LA5.it": 12, "Rai5.it": 13,
    "RaiMovie.it": 14, "RaiPremium.it": 15, "Italia2.it": 16,
    "MediasetExtra.it": 17, "TV2000.it": 18, "CieloTv.it": 19,
    "Mediaset20.it": 20, "RaiSport.it": 21, "Focus.it": 22,
    "RaiStoria.it": 23, "RaiNews24.it": 24, "TGCom24.it": 25,
    "RaiScuola.it": 26, "Mediaset27Twentyseven.it": 27, "DMAX.it": 28,
    "La7D.it": 29, "RealTime.it": 31, "FoodNetwork.it": 33,
    "Cine34.it": 34, "RTL102.5TV.it": 36, "Discovery.it": 37,
    "GialloTV.it": 38, "TopCrime.it": 39, "Boing.it": 40,
    "Cartoonito.it": 41, "RaiGulp.it": 42, "RaiYoyo.it": 43,
    "Frisbee.it": 44, "K2.it": 46, "Super.it": 47,
    # 48 ARTE, 49 Mezzo, 50 RDS Social TV, 51 EQUtv, 52 ACI Sport non presenti nella sorgente
    "HGTV.it": 56,            # verificato: HGTV Italy = 56
    "MotorTrend.it": 59,      # nella sorgente "Discovery Turbo" tvg-id MotorTrend.it = LCN 59 (Discovery Turbo)
    "RadioItaliaTV.it": 35,   # Radio Italia TV = 35
    "RadioKissKiss.it": 64,   # verificato
    "RadioZeta.it": 65,       # verificato
    "RadioFrecciaTV.it": 66,  # verificato
    "RadioMontecarlo.it": 67, # verificato (RMC)
    "VirginRadio.it": 68,     # verificato
    "Sportitalia.it": 54,     # su Tivùsat è LCN 54 (nome ufficiale "Sportitalia Solo Calcio")
    # --- Non mappati VOLUTAMENTE: questi canali NON esistono nella griglia Tivùsat 1-99 ---
    # "SkyTG24.it"  -> Sky TG24 non è presente nella numerazione satellitare Tivùsat
    # "DeejayTV.it" -> Deejay TV non è presente nella numerazione satellitare Tivùsat
    # Lasciarli in fondo è quindi l'esperienza Tivùsat corretta.
}

# ---------------------------------------------------------------------------
# Fallback per nome normalizzato (se il tvg-id manca o non è in tabella).
# ---------------------------------------------------------------------------
LCN_PER_NOME = {
    "rai 1": 1, "rai 2": 2, "rai 3": 3, "rete 4": 4, "canale 5": 5,
    "italia 1": 6, "la7": 7, "tv8": 8, "nove": 9, "rai 4": 10, "iris": 11,
    "la 5": 12, "la5": 12, "rai 5": 13, "rai movie": 14, "rai premium": 15,
    "italia 2": 16, "mediaset extra": 17, "tv2000": 18, "cielo": 19,
    "20 mediaset": 20, "mediaset 20": 20, "rai sport": 21, "focus": 22,
    "rai storia": 23, "rai news 24": 24, "tgcom 24": 25, "tgcom24": 25,
    "rai scuola": 26, "twentyseven": 27, "twenty seven": 27, "dmax": 28,
    "la7 cinema": 29, "real time": 31, "food network": 33, "cine34": 34,
    "cine 34": 34, "rtl 102.5": 36, "discovery": 37, "giallo": 38,
    "top crime": 39, "boing": 40, "cartoonito": 41, "rai gulp": 42,
    "rai yoyo": 43, "frisbee": 44, "k2": 46, "super!": 47, "hgtv": 56,
    "discovery turbo": 59, "radio italia": 35,
    "radio kiss kiss": 64, "radio zeta": 65, "radiofreccia": 66,
    "rmc": 67, "radio monte carlo": 67, "virgin radio": 68,
    "sportitalia": 54, "solo calcio": 54,
    # rimossi: "sportitalia": 60, "deejay": 69, "sky tg24": 50 -> numeri non corretti su Tivùsat
}
# versione senza spazi per match più tollerante
LCN_PER_NOME_NS = {k.replace(" ", ""): v for k, v in LCN_PER_NOME.items()}

NON_MAPPATO = 9999


def normalizza_nome(nome_grezzo: str) -> str:
    nome = nome_grezzo.lower()
    nome = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}', '', nome)
    nome = nome.replace("it:", "").replace("it |", "").replace("it-", "")
    rimuovi = {"hd", "fhd", "4k", "hevc", "1080p", "720p", "h265", "tv", "ita"}
    parole = [p for p in nome.split() if p not in rimuovi]
    return " ".join(parole).strip()


def estrai_tvg_id(extinf: str) -> str | None:
    m = re.search(r'tvg-id="([^"]*)"', extinf)
    return m.group(1) if m and m.group(1) else None


def estrai_nome(extinf: str) -> str:
    return extinf.split(',')[-1].strip()


def trova_lcn(extinf: str) -> int:
    # 1) match sul tvg-id
    tid = estrai_tvg_id(extinf)
    if tid and tid in LCN_PER_ID:
        return LCN_PER_ID[tid]
    # 2) fallback sul nome
    nome = normalizza_nome(estrai_nome(extinf))
    if nome in LCN_PER_NOME:
        return LCN_PER_NOME[nome]
    if nome.replace(" ", "") in LCN_PER_NOME_NS:
        return LCN_PER_NOME_NS[nome.replace(" ", "")]
    return NON_MAPPATO


def imposta_tvg_chno(extinf: str, lcn: int) -> str:
    """Riscrive tvg-chno=... col numero Tivùsat; lo aggiunge se assente."""
    if 'tvg-chno="' in extinf:
        return re.sub(r'tvg-chno="[^"]*"', f'tvg-chno="{lcn}"', extinf)
    # inserisce tvg-chno subito dopo #EXTINF:-1
    return re.sub(r'(#EXTINF:-1)', rf'\1 tvg-chno="{lcn}"', extinf, count=1)


def carica_lista() -> list[str]:
    try:
        print("[*] Scaricamento della lista da GitHub...")
        req = urllib.request.Request(URL_SORGENTE, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode('utf-8').splitlines()
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"[!] Rete non disponibile ({e}). Provo il file locale '{FILE_LOCALE_FALLBACK}'...")
        try:
            with open(FILE_LOCALE_FALLBACK, encoding='utf-8') as f:
                return f.read().splitlines()
        except FileNotFoundError:
            sys.exit("[X] Impossibile scaricare la lista e nessun file locale disponibile.")


def raggruppa_in_blocchi(linee: list[str]) -> list[list[str]]:
    """Un blocco inizia con #EXTINF e include tutte le righe fino al prossimo #EXTINF."""
    blocchi, corrente = [], []
    for linea in linee:
        linea = linea.strip()
        if not linea or linea.startswith("#EXTM3U"):
            continue
        if linea.startswith("#EXTINF"):
            if corrente:
                blocchi.append(corrente)
            corrente = [linea]
        elif corrente:
            corrente.append(linea)
    if corrente:
        blocchi.append(corrente)
    return blocchi


def processa():
    linee = carica_lista()
    print("[*] Estrazione blocchi (DRM/EPG/loghi intatti)...")
    blocchi = raggruppa_in_blocchi(linee)

    mappati, non_mappati = [], []
    for blocco in blocchi:
        lcn = trova_lcn(blocco[0])
        if lcn != NON_MAPPATO:
            blocco[0] = imposta_tvg_chno(blocco[0], lcn)
            mappati.append((lcn, blocco))
        else:
            non_mappati.append(blocco)

    mappati.sort(key=lambda x: x[0])

    # Ai canali non Tivùsat assegno numeri progressivi nell'arco 900+,
    # così restano in fondo e il loro tvg-chno non si confonde con la griglia ufficiale.
    INIZIO_EXTRA = 900
    for i, blocco in enumerate(non_mappati):
        blocco[0] = imposta_tvg_chno(blocco[0], INIZIO_EXTRA + i)

    print("[*] Generazione del file M3U...")
    with open(FILE_OUTPUT, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for _, blocco in mappati:
            f.write("\n".join(blocco) + "\n")
        for blocco in non_mappati:
            f.write("\n".join(blocco) + "\n")

    print(f"[+] Completato!")
    print(f"    {len(mappati)} canali associati a Tivùsat (ordinati + tvg-chno aggiornato)")
    print(f"    {len(non_mappati)} canali non mappati messi in fondo")
    print(f"    File: {FILE_OUTPUT}")


if __name__ == "__main__":
    processa()
