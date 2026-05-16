"""P59 — Rebuild the FTS5 full-text index.

`paragraphs_fts` is an **external-content** FTS5 table (``content =
'paragraphs'``) kept in sync with `paragraphs` by AFTER INSERT / UPDATE
/ DELETE triggers.  That trigger-sync is fragile: the external-content
``'delete'`` command requires the *old* column values handed to it to
exactly match what is indexed.  Once a single desync occurs — e.g. a
P34 source-exact rebuild (`DELETE` + `INSERT`, which reassigns
rowids), or a P5x heal `UPDATE` applied while the index had already
drifted — stale postings stop being removed and accumulate.

The visible symptom is a search hit joining to the WRONG paragraph:
`MATCH` finds rowid R in the (stale) inverted index, but
`JOIN paragraphs p ON p.rowid = pf.rowid` lands on whatever row now
holds rowid R — e.g. an elision-only "..." quote row surfacing as the
top match for a content query.

`'rebuild'` re-derives the entire FTS index from the current content
table in one pass; `'optimize'` then merges the b-tree segments;
`'integrity-check'` verifies the result.  Run P59 after ANY bulk
mutation of `paragraphs` (P34 rebuilds, P5x heals).  Idempotent.
"""
from __future__ import annotations

import argparse
import sqlite3
import time

DB = "/data/echr_search.db"


def run(dry_run: bool, db_path: str) -> None:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode = WAL")

    n_para = con.execute("SELECT count(*) FROM paragraphs").fetchone()[0]
    n_fts = con.execute("SELECT count(*) FROM paragraphs_fts").fetchone()[0]
    print(f"paragraphs rows:  {n_para:,}")
    print(f"FTS rows:         {n_fts:,}")

    if dry_run:
        print("\nDRY RUN — no rebuild applied.")
        return

    print("\nrebuilding FTS index...", flush=True)
    t = time.time()
    con.execute("INSERT INTO paragraphs_fts(paragraphs_fts) VALUES('rebuild')")
    con.commit()
    print(f"  rebuilt in {time.time() - t:.1f}s", flush=True)

    print("optimizing...", flush=True)
    t = time.time()
    con.execute("INSERT INTO paragraphs_fts(paragraphs_fts) VALUES('optimize')")
    con.commit()
    print(f"  optimized in {time.time() - t:.1f}s", flush=True)

    try:
        con.execute("INSERT INTO paragraphs_fts(paragraphs_fts) VALUES('integrity-check')")
        print("integrity-check:  OK")
    except sqlite3.DatabaseError as exc:
        print(f"integrity-check:  FAILED — {exc}")
    print("done.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(args.dry_run, args.db)


if __name__ == "__main__":
    main()
