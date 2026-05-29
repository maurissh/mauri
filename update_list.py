import urllib.request
import re

# Configurazione
URL_SORGENTE = "https://raw.githubusercontent.com/maginetweb-arch/TVITALIA/refs/heads/main/iptvit.m3u"
FILE_OUTPUT = "tivusat_ordinato.m3u"

# Numerazione LCN Tivùsat (i principali, espandibile a piacimento)
LCN_TIVUSAT = {
    "rai 1": 1, "rai 2": 2, "rai 3": 3, "rete 4": 4, "canale 5": 5, "italia 1": 6,
    "la7": 7, "tv8": 8, "nove": 9, "20 mediaset": 20, "rai 4": 21, "iris": 22,
    "rai 5": 23, "rai movie": 24, "rai premium": 25, "cielo": 26, "twentyseven": 27,
    "27 twentyseven": 27, "la7d": 28, "cine34": 29, "la5": 30, "real time": 31,
    "qvc": 32, "food network": 33, "warner tv": 34, "focus": 35, "rtl 102.5": 36,
    "giallo": 37, "top crime": 38, "dmax": 39, "boing": 40, "k2": 41, "frisbee": 42,
    "rai gulp": 43, "rai yoyo": 44, "cartoonito": 46, "super!": 47,
    "rai news 24": 48, "tgcom24": 51, "rai storia": 54, "mediaset extra": 55, 
    "hgtv": 56, "motor trend": 59, "sportitalia": 60, "rai sport": 61, 
    "supertennis": 64, "radio 105": 66, "r101": 67, "virgin radio": 68, 
    "radio italia": 70, "kiss kiss": 72, "radionorba tv": 73, "rtl 102.5 news": 74, 
    "radio zeta": 75, "freccia": 76, "rds social tv": 50, "vh1": 22, "paramount": 27
}

def normalizza_nome(nome_grezzo):
    """Pulisce il nome del canale per un matching perfetto con l'LCN."""
    nome = nome_grezzo.lower()
    # Rimuove tag tra parentesi quadre o tonde es: [FHD], (IT)
    nome = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}', '', nome)
    # Rimuove artefatti e diciture di qualità
    da_rimuovere = ["hd", "fhd", "4k", "it:", "tv", "hevc"]
    for parola in da_rimuovere:
        nome = nome.replace(parola, "")
    return nome.strip()

def processa_m3u():
    print("[*] Scaricamento della lista da GitHub in corso...")
    req = urllib.request.Request(URL_SORGENTE, headers={'User-Agent': 'Mozilla/5.0'})
    
    with urllib.request.urlopen(req) as response:
        linee = response.read().decode('utf-8').splitlines()

    canali = []
    blocco_corrente = []
    
    print("[*] Estrazione e analisi dei canali (DRM, EPG, Picons inclusi)...")
    for linea in linee:
        linea = linea.strip()
        if non linea: continue
        
        if linea.startswith("#EXTM3U"):
            continue # Lo saltiamo qui, lo aggiungiamo in cima alla fine
            
        if linea.startswith("#EXTINF"):
            if blocco_corrente:
                canali.append(blocco_corrente)
            blocco_corrente = [linea]
        elif blocco_corrente:
            blocco_corrente.append(linea)
            if not linea.startswith("#"):
                # URL trovato, fine del blocco canale
                canali.append(blocco_corrente)
                blocco_corrente = []

    # Se l'ultimo blocco non si è chiuso
    if blocco_corrente:
        canali.append(blocco_corrente)

    canali_ordinati = []
    canali_non_mappati = []

    for blocco in canali:
        extinf_line = blocco[0]
        # Il nome del canale è tutto ciò che c'è dopo l'ultima virgola
        nome_grezzo = extinf_line.split(',')[-1].strip()
        nome_pulito = normalizza_nome(nome_grezzo)
        
        # Cerca il nome pulito nel dizionario LCN
        lcn = LCN_TIVUSAT.get(nome_pulito, 9999) # 9999 per spingerli in fondo se non trovati
        
        if lcn != 9999:
            canali_ordinati.append((lcn, blocco))
        else:
            canali_non_mappati.append((lcn, blocco))

    # Ordina i canali trovati per LCN
    canali_ordinati.sort(key=lambda x: x[0])
    
    # Unisce le liste (prima i Tivusat ordinati, poi il resto)
    lista_finale = canali_ordinati + canali_non_mappati

    print("[*] Generazione del file M3U finale...")
    with open(FILE_OUTPUT, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for lcn, blocco in lista_finale:
            f.write("\n".join(blocco) + "\n")

    print(f"[+] Lavoro completato. Lista salvata come: {FILE_OUTPUT}")

if __name__ == "__main__":
    processa_m3u()
    
