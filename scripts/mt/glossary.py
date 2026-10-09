#!/usr/bin/env python3
"""
French → English terminology of the Court, checked against its own translations.

CORE lists candidate pairs from the Court's usage (HUDOC keyword lists, judgments). `validate`
measures each pair on the parallel corpus: of the aligned paragraphs whose French side contains the
French term, in how many does the official English side contain the English term. Only pairs that
are consistent (default ≥ 90 % over ≥ 5 occurrences) go into the glossary given to the translator;
the others are reported so they can be corrected.

    python3 scripts/mt/glossary.py --parallel mt/parallel.sqlite --out mt/glossary.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys

# French term (lower case, matched on word boundaries) -> English term as the Court writes it.
CORE = {
    "requérant": "applicant", "requérante": "applicant", "requérants": "applicants",
    "requérantes": "applicants", "le gouvernement": "the Government",
    "gouvernement défendeur": "respondent Government", "état défendeur": "respondent State",
    "grief": "complaint", "griefs": "complaints", "ingérence": "interference",
    "marge d'appréciation": "margin of appreciation", "dommage moral": "non-pecuniary damage",
    "préjudice moral": "non-pecuniary damage", "dommage matériel": "pecuniary damage",
    "préjudice matériel": "pecuniary damage", "frais et dépens": "costs and expenses",
    "satisfaction équitable": "just satisfaction", "voies de recours internes": "domestic remedies",
    "épuisement des voies de recours internes": "exhaustion of domestic remedies",
    "manifestement mal fondé": "manifestly ill-founded", "délai raisonnable": "reasonable time",
    "prévue par la loi": "prescribed by law", "prévues par la loi": "prescribed by law",
    "nécessaire dans une société démocratique": "necessary in a democratic society",
    "besoin social impérieux": "pressing social need", "but légitime": "legitimate aim",
    "proportionnalité": "proportionality", "qualité de victime": "victim status",
    "recours effectif": "effective remedy", "procès équitable": "fair trial",
    "tribunal indépendant et impartial": "independent and impartial tribunal",
    "égalité des armes": "equality of arms", "présomption d'innocence": "presumption of innocence",
    "obligations positives": "positive obligations", "obligation positive": "positive obligation",
    "traitements inhumains ou dégradants": "inhuman or degrading treatment",
    "détention provisoire": "pre-trial detention", "garde à vue": "police custody",
    "vie privée et familiale": "private and family life", "liberté d'expression": "freedom of expression",
    "liberté de réunion": "freedom of assembly", "liberté d'association": "freedom of association",
    "respect de ses biens": "peaceful enjoyment of his possessions",
    "Cour de cassation": "Court of Cassation", "Conseil d'État": "Conseil d'État",
    "cour d'appel": "Court of Appeal", "tribunal de grande instance": "tribunal de grande instance",
    "parquet": "public prosecutor's office", "procureur": "prosecutor", "juge d'instruction": "investigating judge",
    "partie civile": "civil party", "irrecevable": "inadmissible", "recevable": "admissible",
    "la chambre": "the Chamber", "la grande chambre": "the Grand Chamber", "le comité": "the Committee",
    "arrêt": "judgment", "décision": "decision", "requête": "application", "requêtes": "applications",
}


def validate(parallel_db: str, min_n: int = 5, min_share: float = 0.9) -> dict:
    con = sqlite3.connect(f"file:{parallel_db}?mode=ro", uri=True)
    rows = con.execute("SELECT p.fr, p.en FROM pairs p JOIN docs d ON d.en_id = p.en_id WHERE d.split = 'tm'").fetchall()
    result = {}
    for fr, en in CORE.items():
        pat = re.compile(r"(?<!\w)" + re.escape(fr) + r"(?!\w)", re.IGNORECASE)
        hits = [e for f, e in rows if pat.search(f.replace("’", "'"))]
        ok = sum(1 for e in hits if en.lower() in e.lower())
        result[fr] = {"en": en, "n": len(hits), "consistent": ok,
                      "share": round(ok / len(hits), 3) if hits else None,
                      "keep": len(hits) >= min_n and ok / len(hits) >= min_share}
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parallel", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-n", type=int, default=5)
    ap.add_argument("--min-share", type=float, default=0.9)
    args = ap.parse_args()
    res = validate(args.parallel, args.min_n, args.min_share)
    kept = {fr: v["en"] for fr, v in res.items() if v["keep"]}
    json.dump({"terms": kept, "validation": res}, open(args.out, "w"), ensure_ascii=False, indent=1)
    print(f"{len(kept)} of {len(res)} terms kept")
    for fr, v in sorted(res.items(), key=lambda kv: (kv[1]["keep"], kv[1]["share"] or 0)):
        if not v["keep"]:
            print(f"  dropped  {fr!r:45} -> {v['en']!r:35} {v['consistent']}/{v['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
