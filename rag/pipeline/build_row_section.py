#!/usr/bin/env python3
"""Regenerate rag/app/data/row_section.tsv — the RAG's rowid -> section map.

WHY THIS EXISTS SEPARATELY FROM THE INDEX

The semantic-search service keeps section labels in a plain `rowid<TAB>section`
file that `rag_api.py` loads at startup (ROWSEC_FILE) and uses both to filter
results and to build the UI's section facets. It is NOT part of the FAISS
index and shares no state with the embeddings — so the section taxonomy can be
refreshed without re-embedding anything.

That matters because P63/P64 (31 July 2026) split the Facts family into
Procedure / Circumstances / Subject Matter, and the RAG was still advertising
the pre-split taxonomy: its facet list offered `Facts`, `Facts Background` and
`Introduction`, labels the main Search page no longer shows and the database no
longer contains. Users filtering the two tabs saw different vocabularies.

WHY THE ROWIDS STILL LINE UP

The keys are `paragraphs.rowid` from the production database — the same space
`extract_corpus.py` emits, so the same space the index was built over. P63, P64
and P66 were all UPDATE-only (each verifies a row-count invariant before
writing), so every rowid the May index knows about still exists and still
points at the same paragraph; only the `section` value moved. The monthly
corpus update INSERTs new rows, which appear here with new rowids the index
does not contain — harmless, since this is a lookup table and unknown keys are
simply never queried.

The row filter is copied verbatim from extract_corpus.py so the two stay in
step. Note that the Facts-family rows it used to admit are still admitted after
the split: Procedure / Circumstances / Subject Matter are not in the excluded
set, so no row silently drops out of the corpus.

Usage (inside the echr-api container, where /data is mounted):
    python3 build_row_section.py > /tmp/row_section.tsv
    python3 build_row_section.py --compare /data/rag/row_section.tsv
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import Counter

DB = os.environ.get("ECHR_DB_PATH", "/data/echr_search.db")

# Verbatim from rag/pipeline/extract_corpus.py — keep in step.
QUERY = (
    "SELECT rowid, COALESCE(section,'') FROM paragraphs "
    "WHERE row_role='paragraph' AND text IS NOT NULL AND TRIM(text)<>'' "
    "AND COALESCE(section,'') NOT IN ('Header','Appendix','Summary')"
)


def load(conn):
    return {rid: sec for rid, sec in conn.execute(QUERY)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--compare", metavar="OLD_TSV",
                    help="report the diff against an existing file instead of "
                         "emitting a new one")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = load(conn)

    if not args.compare:
        out = sys.stdout
        for rid in sorted(rows):
            out.write(f"{rid}\t{rows[rid]}\n")
        print(f"[done] {len(rows):,} rows", file=sys.stderr)
        return

    old = {}
    with open(args.compare, encoding="utf-8") as f:
        for line in f:
            a, _, b = line.rstrip("\n").partition("\t")
            if a:
                old[int(a)] = b

    changed = Counter()
    added = 0
    removed = 0
    for rid, sec in rows.items():
        if rid not in old:
            added += 1
        elif old[rid] != sec:
            changed[(old[rid], sec)] += 1
    for rid in old:
        if rid not in rows:
            removed += 1

    print(f"old file : {len(old):,} rows")
    print(f"new query: {len(rows):,} rows")
    print(f"  added   (new corpus rows, not in the index): {added:,}")
    print(f"  removed (in the file, no longer qualifying): {removed:,}")
    print(f"  relabelled: {sum(changed.values()):,}")
    for (o, n), k in changed.most_common(20):
        print("    %-22s -> %-22s %9s" % (o or "(blank)", n or "(blank)", f"{k:,}"))
    print()
    print("resulting facet list (what the UI will offer):")
    for sec, k in Counter(rows.values()).most_common():
        print("    %-22s %9s" % (sec or "(blank)", f"{k:,}"))


if __name__ == "__main__":
    main()
