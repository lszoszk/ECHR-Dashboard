#!/usr/bin/env python3
"""
The most cited judgments counted as the Search page counts them, for the Statistics page.

Search's *Cited by* is the judgments that cite a case in case_citations (built by
p29_extract_citations.py from the judgments' text and HUDOC's metadata; machine translations are
cited there but never citing), plus the judgments HUDOC publishes only in French that cite it
according to HUDOC's metadata (french_only_citations), whether or not they have been machine-
translated. This script applies the same rule to every judgment and writes the top of the ranking,
with the citing judgments of each, as JSON:

    {"source": ..., "ranking": [{case_id, title, date, ecli, collection, cited_by_count,
                                  cited_by_french_only}, ...],
     "citing_by_target": {case_id: [citing_id, ...]},
     "citing_judgments": {citing_id: {title, date, ecli, french_only}},
     "coverage": {...}}

Run it where the database is, e.g. inside the API container (read-only):

    docker exec -i echr-api python3 - --db /data/echr_search.db --top 20 < scripts/export_search_citations.py > search_citations.json

then merge it into the Statistics snapshot with scripts/merge_search_citations.py.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict


def iso(ddmmyyyy: str) -> str:
    d = (ddmmyyyy or "").strip()
    return f"{d[6:10]}-{d[3:5]}-{d[0:2]}" if len(d) == 10 and d[2] == "/" else d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/data/echr_search.db")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    cols = [r[1] for r in con.execute("PRAGMA table_info(cases)")]
    origin = "COALESCE(text_origin, '')" if "text_origin" in cols else "''"
    meta = {r[0]: r[1:] for r in con.execute(
        f"SELECT case_id, title, judgment_date, ecli, document_type, originating_body, {origin} FROM cases")}
    official = {cid for cid, m in meta.items() if m[5] != "machine_translation"}

    citers: dict[str, set] = defaultdict(set)
    for citing, cited in con.execute("SELECT DISTINCT citing_case_id, cited_case_id FROM case_citations"):
        citers[cited].add(citing)
    french: dict[str, set] = defaultdict(set)
    try:
        for citing, cited in con.execute("SELECT DISTINCT citing_case_id, cited_case_id FROM french_only_citations"):
            if citing not in official:            # as the API: not in the corpus, or only as a translation
                french[cited].add(citing)
    except sqlite3.OperationalError:
        pass
    french_meta = {}
    try:
        french_meta = {r[0]: r[1:] for r in con.execute(
            "SELECT case_id, title, judgment_date, ecli FROM french_only_cases")}
    except sqlite3.OperationalError:
        pass

    def is_judgment(cid: str) -> bool:
        m = meta.get(cid)
        return bool(m) and not (m[3] or "").startswith("Decision")

    totals = {cid: len(citers[cid] | french[cid]) for cid in set(citers) | set(french) if is_judgment(cid)}
    top = sorted(totals, key=lambda c: (-totals[c], c))[: args.top]

    def collection(m) -> str:
        body = m[4] or ""
        return ("GRANDCHAMBER" if "Grand Chamber" in body or m[3] == "Judgment (Grand Chamber)"
                else "COMMITTEE" if "Committee" in body or body in ("25", "26", "27", "28", "29") else "CHAMBER")

    ranking, by_target, citing_meta = [], {}, {}
    for cid in top:
        m = meta[cid]
        ranking.append({"case_id": cid, "title": (m[0] or "").replace("CASE OF ", ""), "date": iso(m[1]),
                        "ecli": m[2] or "", "collection": collection(m), "cited_by_count": totals[cid],
                        "cited_by_french_only": len(french[cid] - citers[cid])})
        ids = citers[cid] | french[cid]
        for x in ids:
            if x in citing_meta:
                continue
            fm = meta.get(x) if x in official else None
            src = fm if fm else (french_meta.get(x) or meta.get(x) or ("", "", ""))
            citing_meta[x] = {"title": (src[0] or "").replace("CASE OF ", ""), "date": iso(src[1]),
                              "ecli": src[2] or "", "french_only": x not in official}
        by_target[cid] = sorted(ids, key=lambda x: citing_meta[x]["date"], reverse=True)

    json.dump({
        "source": "Search's Cited by: case_citations (judgments' text and HUDOC metadata) plus French-only "
                  "judgments citing it according to HUDOC's metadata",
        "ranking": ranking, "citing_by_target": by_target, "citing_judgments": citing_meta,
        "coverage": {"cited_judgments": len(totals),
                     "citation_pairs": sum(len(v) for v in citers.values()),
                     "french_only_pairs": sum(len(v) for v in french.values())},
    }, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
