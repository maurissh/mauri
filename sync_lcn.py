#!/usr/bin/env python3
"""
sync_lcn.py
-----------
Scarica la numerazione LCN tivusat dal thread di riferimento su
digital-forum.it, ne estrae le coppie (numero -> nome canale) e le
CONFRONTA con la tabella locale lcn_tivusat.json.

Filosofia di sicurezza:
  La pagina sorgente e' testo scritto per umani su un forum: puo' cambiare
  formato o sparire. Per questo lo script NON sovrascrive ciecamente la tua
  tabella curata. Di default opera in modalita' "report": scrive le
  differenze trovate in lcn_changes.md e crea una tabella proposta in
  lcn_tivusat.proposed.json, lasciando intatta quella vera.

  Solo se lanciato con --apply (e se il parsing ha prodotto un numero
  plausibile di canali) aggiorna davvero lcn_tivusat.json.

Uso:
  python sync_lcn.py            # solo report, non tocca la tabella
  python sync_lcn.py --apply    # applica le modifiche alla tabella

Non richiede dipendenze esterne.
"""

import json
import re
import sys
import html as html_lib
import urllib.request
from pathlib import Path

# Numero del thread su digital-forum.it (resta fisso anche se l'URL cambia data).
THREAD_ID = "83950"
# URL "stabile": XenForo reindirizza a quello completo con la data corrente.
SOURCE_URL = f"https://www.digital-forum.it/threads/{THREAD_ID}/"

ROOT = Path(__file__).resolve().parent
MAPPING_FILE = ROOT / "lcn_tivusat.json"
PROPOSED_FILE = ROOT / "lcn_tivusat.proposed.json"
CHANGES_FILE = ROOT / "lcn_changes.md"

# Soglia di sicurezza: se il parsing trova meno di questo numero di canali,
# qualcosa e' andato storto (pagina cambiata, errore di rete) e NON applichiamo.
MIN_PLAUSIBLE = 80

# Range LCN validi per tivusat (1-999). Fuori da qui ignoriamo.
LCN_MIN, LCN_MAX = 1, 999


def fetch_html(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; tivusat-lcn-sync/1.0)"
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    # il forum e' in UTF-8
    return raw.decode("utf-8", errors="replace")


def extract_first_post(html):
    """
    Isola il testo del primo messaggio (quello con la lista completa).
    Su XenForo il corpo dei post sta in <article class="message-body"> o simili;
    per robustezza prendiamo dall'inizio della pagina fino al primo marcatore
    di fine lista. In pratica lavoriamo su tutto l'HTML: il parser per riga
    e' gia' abbastanza selettivo.
    """
    # rimuove i tag HTML lasciando il testo
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    return text


def parse_lcn(text):
    """
    Estrae le coppie numero -> nome canale.
    Ogni riga utile ha forma:  <numero> <Nome Canale> [frequenza...]
    Esempi reali:
        1 Rai 1 HD [11765 V 29900 ...]
        301 Rai 3 TGR Valle d'Aosta $ [11013 H ...]
        610 RTL 102.5 [12149 V ...]
    Strategia: per ogni riga, cerca un numero a inizio riga seguito da un nome.
    Tagliamo via la parte tra parentesi quadre (frequenza) e i marcatori $/().
    """
    mapping = {}
    # cattura: inizio riga, numero (1-3 cifre), spazio, resto della riga
    line_re = re.compile(r"^\s*(\d{1,3})\s+(.+?)\s*$")

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = line_re.match(line)
        if not m:
            continue
        num = int(m.group(1))
        if not (LCN_MIN <= num <= LCN_MAX):
            continue
        name = m.group(2)

        # togli tutto da '[' in poi (frequenza) e da '(' in poi quando e' nota tecnica
        name = re.split(r"[\[\(]", name)[0]
        # togli marcatori di pay '$' e asterischi di nota
        name = name.replace("$", " ").replace("*", " ")
        # normalizza spazi
        name = re.sub(r"\s+", " ", name).strip()

        # scarta righe che chiaramente non sono canali (es. anni, frequenze sfuggite)
        if not name or len(name) < 2:
            continue
        # un nome canale ha almeno una lettera
        if not re.search(r"[A-Za-zÀ-ÿ]", name):
            continue
        # evita di sovrascrivere: tieni la prima occorrenza per ogni numero
        if num not in mapping:
            mapping[num] = name

    return mapping


def load_current():
    if not MAPPING_FILE.exists():
        return {}
    raw = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    # invertiamo in numero -> nome per il confronto
    by_num = {}
    for name, num in raw.items():
        by_num[int(num)] = name
    return by_num


def diff(current_by_num, parsed_by_num):
    """Calcola aggiunte, rimozioni e cambi di nome/numero."""
    cur_nums = set(current_by_num)
    new_nums = set(parsed_by_num)

    added = sorted(new_nums - cur_nums)            # numeri nuovi
    removed = sorted(cur_nums - new_nums)          # numeri spariti
    renamed = []                                   # stesso numero, nome diverso
    for num in sorted(cur_nums & new_nums):
        old = current_by_num[num]
        new = parsed_by_num[num]
        if normalize(old) != normalize(new):
            renamed.append((num, old, new))
    return added, removed, renamed


def normalize(name):
    """Confronto morbido dei nomi (minuscolo, solo alfanumerici)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def write_changes(added, removed, renamed, parsed_by_num, current_by_num):
    lines = ["# Modifiche LCN tivusat rilevate", ""]
    if not (added or removed or renamed):
        lines.append("Nessuna differenza rispetto alla tabella attuale. ✅")
    else:
        if added:
            lines += ["## Canali nuovi (presenti sul forum, assenti in tabella)", ""]
            lines += [f"- **{n}** — {parsed_by_num[n]}" for n in added]
            lines.append("")
        if removed:
            lines += ["## Canali rimossi (in tabella ma non piu' sul forum)", ""]
            lines += [f"- **{n}** — {current_by_num[n]}" for n in removed]
            lines.append("")
        if renamed:
            lines += ["## Canali rinominati (stesso numero, nome diverso)", ""]
            lines += [f"- **{n}**: `{old}` → `{new}`" for n, old, new in renamed]
            lines.append("")
    CHANGES_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_proposed(parsed_by_num):
    """Scrive la tabella proposta (nome -> numero) ordinata per numero."""
    proposed = {}
    for num in sorted(parsed_by_num):
        proposed[parsed_by_num[num]] = num
    PROPOSED_FILE.write_text(
        json.dumps(proposed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    apply = "--apply" in sys.argv

    print(f"Scarico la numerazione LCN da {SOURCE_URL} ...")
    try:
        html = fetch_html(SOURCE_URL)
    except Exception as e:
        print(f"ERRORE di rete: {e}", file=sys.stderr)
        sys.exit(2)

    text = extract_first_post(html)
    parsed_by_num = parse_lcn(text)
    print(f"Canali estratti dal forum: {len(parsed_by_num)}")

    if len(parsed_by_num) < MIN_PLAUSIBLE:
        print(
            f"ATTENZIONE: trovati solo {len(parsed_by_num)} canali "
            f"(soglia minima {MIN_PLAUSIBLE}). Il formato della pagina "
            f"potrebbe essere cambiato. Non applico nulla.",
            file=sys.stderr,
        )
        # scriviamo comunque il proposed per ispezione manuale
        write_proposed(parsed_by_num)
        sys.exit(3)

    current_by_num = load_current()
    added, removed, renamed = diff(current_by_num, parsed_by_num)

    write_changes(added, removed, renamed, parsed_by_num, current_by_num)
    write_proposed(parsed_by_num)

    print(f"  nuovi: {len(added)} | rimossi: {len(removed)} | rinominati: {len(renamed)}")
    print(f"  Report scritto in {CHANGES_FILE.name}")
    print(f"  Tabella proposta in {PROPOSED_FILE.name}")

    if apply:
        if not (added or removed or renamed):
            print("Nessuna modifica da applicare.")
            return
        # applica: la proposta diventa la tabella ufficiale
        PROPOSED_FILE.replace(MAPPING_FILE)
        print(f"  --apply: {MAPPING_FILE.name} aggiornato dalla proposta.")
    else:
        print("  Modalita' report (nessuna scrittura su lcn_tivusat.json).")
        print("  Per applicare: python sync_lcn.py --apply")


if __name__ == "__main__":
    main()
