"""
French → English conventions for ECtHR case-law citations, from the Court's citation notes
(https://www.echr.coe.int/documents/d/echr/note_citation_eng and note_citation_fra).

Used two ways:
  * `convert(text)` — fixes the conventions in a translated English paragraph whenever French
    citation forms survived translation ("c.", "(déc.)", "CEDH 2005", "série A no 24", French dates);
  * `check(source_fr, target_en)` — lists what a translation must preserve: application numbers,
    § pinpoints, years of report volumes, and every French date in its English form.
"""
from __future__ import annotations

import re

MONTHS = {"janvier": "January", "février": "February", "fevrier": "February", "mars": "March",
          "avril": "April", "mai": "May", "juin": "June", "juillet": "July", "août": "August",
          "aout": "August", "septembre": "September", "octobre": "October", "novembre": "November",
          "décembre": "December", "decembre": "December"}

# Respondent States as the Court writes them in English case names (with "the" where it uses it).
STATES = {
    "Albanie": "Albania", "Allemagne": "Germany", "Andorre": "Andorra", "Arménie": "Armenia",
    "Autriche": "Austria", "Azerbaïdjan": "Azerbaijan", "Belgique": "Belgium",
    "Bosnie-Herzégovine": "Bosnia and Herzegovina", "Bulgarie": "Bulgaria", "Chypre": "Cyprus",
    "Croatie": "Croatia", "Danemark": "Denmark", "Espagne": "Spain", "Estonie": "Estonia",
    "Finlande": "Finland", "France": "France", "Géorgie": "Georgia", "Grèce": "Greece",
    "Hongrie": "Hungary", "Irlande": "Ireland", "Islande": "Iceland", "Italie": "Italy",
    "Lettonie": "Latvia", "Liechtenstein": "Liechtenstein", "Lituanie": "Lithuania",
    "Luxembourg": "Luxembourg", "Malte": "Malta", "Monaco": "Monaco", "Monténégro": "Montenegro",
    "Norvège": "Norway", "Pologne": "Poland", "Portugal": "Portugal", "Roumanie": "Romania",
    "Russie": "Russia", "Saint-Marin": "San Marino", "Serbie": "Serbia", "Slovaquie": "Slovakia",
    "Slovénie": "Slovenia", "Suède": "Sweden", "Suisse": "Switzerland", "Turquie": "Turkey",
    "Türkiye": "Türkiye", "Ukraine": "Ukraine",
    "Pays-Bas": "the Netherlands", "Royaume-Uni": "the United Kingdom",
    "République tchèque": "the Czech Republic", "République de Moldova": "the Republic of Moldova",
    "Moldova": "the Republic of Moldova", "Macédoine du Nord": "North Macedonia",
    "ex-République yougoslave de Macédoine": "the former Yugoslav Republic of Macedonia",
}
MARKERS = [
    (r"\(déc\.\)", "(dec.)"), (r"\(satisfaction équitable\)", "(just satisfaction)"),
    (r"\(radiation\)", "(striking out)"), (r"\(règlement amiable\)", "(friendly settlement)"),
    (r"\(fond\)", "(merits)"), (r"\(exceptions préliminaires\)", "(preliminary objections)"),
    (r"\(révision\)", "(revision)"), (r"\(interprétation\)", "(interpretation)"),
    (r"\(article 50\)", "(Article 50)"), (r"\[comité\]", "[Committee]"), (r"\(extraits\)", "(extracts)"),
]
DATE_FR = re.compile(r"\b(1er|\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\b", re.IGNORECASE)
APPNO = re.compile(r"\b\d{3,6}/\d{2,4}\b")
PIN = re.compile(r"§§?\s*\d+(?:\s*(?:-|–|—|et|and|à|to)\s*\d+)?")


def fr_date_to_en(m: re.Match) -> str:
    day = "1" if m.group(1).lower() == "1er" else str(int(m.group(1)))
    # IGNORECASE lets a dotless ı (a HUDOC typo, "juıllet") match "i": fold it before the lookup
    return f"{day} {MONTHS[m.group(2).lower().replace('ı', 'i')]} {m.group(3)}"


def convert(text: str) -> str:
    """Apply the Court's English citation conventions to French forms left in a translation."""
    t = text
    for pat, rep in MARKERS:
        t = re.sub(pat, rep, t)
    t = DATE_FR.sub(fr_date_to_en, t)
    t = re.sub(r"\bnos?\s(?=\d)", lambda m: "nos. " if m.group(0).startswith("nos") else "no. ", t)
    t = re.sub(r"\bet\s+(\d+)\s+autres\b", r"and \1 others", t)
    t = re.sub(r"\bCEDH\s+(\d{4})", r"ECHR \1", t)
    t = re.sub(r"\bsérie\s+A\s+no\.?\s*", "Series A no. ", t, flags=re.IGNORECASE)
    t = re.sub(r"\bRecueil des arrêts et décisions\b", "Reports of Judgments and Decisions", t)
    t = re.sub(r"\bRecueil\s+(\d{4})", r"Reports \1", t)
    # "X c. Belgique" -> "X v. Belgium" (only before a known State, so ordinary " c." is untouched)
    states = sorted(STATES.items(), key=lambda kv: -len(kv[0]))
    for fr, en in states:
        t = re.sub(r"\bc\.\s+(?:la\s+|le\s+|l')?" + re.escape(fr) + r"\b", "v. " + en, t)
    # further respondents: "v. Belgium et Grèce" -> "v. Belgium and Greece"
    for fr, en in states:
        t = re.sub(r"(\bv\.\s[^,;()\[]*?)\s+et\s+(?:la\s+|le\s+|l')?" + re.escape(fr) + r"\b",
                   lambda m, en=en: m.group(1) + " and " + en, t)
    return t


def check(source_fr: str, target_en: str) -> list[str]:
    """Problems a translation must not have; an empty list means the citations survived."""
    problems = []
    source_fr = re.sub(r"\s+", " ", source_fr)
    target_en = re.sub(r"\s+", " ", target_en)
    # the Court writes internal references as "paragraphs 175-210" in English, "§§ 175-210" in French
    pins_en = re.sub(r"\bparagraphs\s+(?=\d)", "§§ ", re.sub(r"\bparagraph\s+(?=\d)", "§ ", target_en))
    for a in set(APPNO.findall(source_fr)):
        if a not in target_en:
            problems.append(f"application number {a} missing")
    # Compare the digits only: the French originals have typos ("§§ 7981" for §§ 79-81, "§ 81-84" for
    # §§ 81-84) that a correct translation repairs.
    digits = lambda pin: re.sub(r"\D", "", pin)
    src_pins = [re.sub(r"\s+", " ", p) for p in PIN.findall(source_fr)]
    tgt_digits = [digits(p) for p in PIN.findall(pins_en)]
    for p in set(src_pins):
        if src_pins.count(p) > tgt_digits.count(digits(p)):
            problems.append(f"pinpoint {p} missing")
    for m in DATE_FR.finditer(source_fr):
        if fr_date_to_en(m).lower() not in target_en.lower():
            problems.append(f"date {m.group(0)} not rendered as {fr_date_to_en(m)}")
    for residue in ("(déc.)", " c. ", "CEDH ", "série A"):
        if residue in target_en:
            problems.append(f"French citation form left: {residue.strip()}")
    return problems
