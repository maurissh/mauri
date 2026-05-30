import urllib.request
import re

URL_SORGENTE = "https://raw.githubusercontent.com/maginetweb-arch/TVITALIA/refs/heads/main/iptvit.m3u"
FILE_OUTPUT = "tivusat_ordinato.m3u"

LCN_TIVUSAT = {
    "rai 1": 1, "rai 2": 2, "rai 3": 3, "rete 4": 4, "canale 5": 5, "italia 1": 6,
    "la7": 7, "tv8": 8, "nove": 9, "rai 4": 10, "iris": 11, "la 5": 12, "la5": 12, "rai 5": 13,
    "rai movie": 14, "rai premium": 15, "italia 2": 16, "mediaset extra": 17,
    "tv2000": 18, "cielo": 19, "20 mediaset": 20, "mediaset 20": 20, "rai sport": 21,
    "focus": 22, "rai storia": 23, "rai news 24": 24, "tgcom 24": 25, "tgcom24": 25,
    "rai scuola": 26, "twentyseven": 27, "27 twentyseven": 27, "twenty seven": 27, "dmax": 28,
    "la7d": 29, "la7 cinema": 29, "real time": 31, "food network": 33,
    "cine 34": 34, "cine34": 34, "radio italia": 35, "rtl 102.5": 36, "discovery": 37,
    "giallo": 38, "top crime": 39, "boing": 40, "cartoonito": 41, "rai gulp": 42,
    "rai yoyo": 43, "frisbee": 44, "k2": 46, "super!": 47, "arte": 48, "mezzo": 49,
    "rds social": 50, "rds social tv": 50, "equ": 51, "equ tv": 51, "aci sport": 52,
    "aci sport tv": 52, "sportitalia": 54, "hgtv": 56, "euronews": 58,
    "motor trend": 59, "discovery turbo": 59, "radio italia live": 63, "kiss kiss": 64,
    "radio kiss kiss": 64, "radio zeta": 65, "freccia": 66, "radiofreccia": 66,
    "radio monte carlo": 67, "virgin radio": 68, "deejay": 69, "warner": 54, "warner tv": 54,
    "sky tg24": 0,
}

# versione delle chiavi senza spazi, per match robusto
LCN_NO_SPACE = {k.replace(" ", ""): v for k, v in LCN_TIVUSAT.items()}

def normalizza_nome(nome_grezzo):
    nome = nome_grezzo.lower()
    nome = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}', '', nome)
    nome = nome.replace("it:", "").replace("it |", "").replace("it-", "")
    parole_da_rimuovere = ["hd", "fhd", "4k", "hevc", "1080p", "720p", "h265", "tv", "ita"]
    parole_pulite = [p for p in nome.split() if p not in parole_da_rimuovere]
    return " ".join(parole_pulite).strip()

def trova_lcn(nome_pulito):
    if nome_pulito in LCN_TIVUSAT:
        return LCN_TIVUSAT[nome_pulito]
    senza_spazi = nome_pulito.replace(" ", "")
    if senza_spazi in LCN_NO_SPACE:
        return LCN_NO_SPACE[senza_spazi]
    return 9999

def processa_m3u():
    print("[*] Scaricamento della lista da GitHub...")
    req = urllib.request.Request(URL_SORGENTE, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        linee = response.read().decode('utf-8').splitlines()

    canali = []
    blocco_corrente = []
    print("[*] Estrazione blocchi (DRM/EPG/Picons intatti)...")
    for linea in linee:
        linea = linea.strip()
        if not linea:
            continue
        if linea.startswith("#EXTM3U"):
            continue
        if linea.startswith("#EXTINF"):
            if blocco_corrente:
                canali.append(blocco_corrente)
            blocco_corrente = [linea]
        elif blocco_corrente:
            blocco_corrente.append(linea)
            if not linea.startswith("#"):
                canali.append(blocco_corrente)
                blocco_corrente = []
    if blocco_corrente:
        canali.append(blocco_corrente)

    canali_ordinati = []
    canali_non_mappati = []
    for blocco in canali:
        nome_grezzo = blocco[0].split(',')[-1].strip()
        nome_pulito = normalizza_nome(nome_grezzo)
        lcn = trova_lcn(nome_pulito)
        if lcn != 9999:
            canali_ordinati.append((lcn, blocco))
        else:
            canali_non_mappati.append((lcn, blocco))

    canali_ordinati.sort(key=lambda x: x[0])
    lista_finale = canali_ordinati + canali_non_mappati

    print("[*] Generazione del file M3U...")
    with open(FILE_OUTPUT, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for lcn, blocco in lista_finale:
            f.write("\n".join(blocco) + "\n")

    print(f"[+] Completato! {len(canali_ordinati)} canali associati a Tivusat. Salvato come: {FILE_OUTPUT}")

if __name__ == "__main__":
    processa_m3u()
