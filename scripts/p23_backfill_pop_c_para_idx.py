#!/usr/bin/env python3
"""
P23 — backfill `para_idx` for Population C committee judgments.

Background
----------
The Pop C ingest path (post-2021 committee judgments, ~6,240 cases) has
historically left `paragraphs.para_idx` as NULL on every row, while the
older Pop A/B ingest populates it correctly.  Without `para_idx`:

  * the dashboard frontend's orphan-row fallback ("¶ 1*") collapses every
    unnumbered fragment in a case to the same display label;
  * search-result ordering inside a section depends on rowid, which the
    cleanup passes (P9, P11, P14, P16, P17, P19) have shuffled;
  * any future export needs a stable ordering field.

This pass assigns `para_idx` = the 0-based position within the case, taken
in (current) rowid order.  Run AFTER P21 so the dedup deletions don't
leave gaps in the eventual numbering.

Usage
-----
    python3 scripts/p23_backfill_pop_c_para_idx.py [--db PATH] [--apply]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/echr_search.db",
                    help="SQLite DB to operate on (default: data/echr_search.db).")
    ap.add_argument("--apply", action="store_true",
                    help="Apply the backfill.  Without this flag, dry-run only.")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute(
        "SELECT count(*) AS n FROM paragraphs WHERE para_idx IS NULL"
    )
    null_rows = cur.fetchone()["n"]
    print(f"rows with para_idx IS NULL: {null_rows:,}")
    if null_rows == 0:
        print("nothing to do.")
        return 0

    # Find affected cases.
    cur.execute(
        "SELECT case_id, count(*) AS n FROM paragraphs "
        "WHERE para_idx IS NULL GROUP BY case_id"
    )
    affected = cur.fetchall()
    print(f"affected cases: {len(affected):,}")

    if not args.apply:
        # Show a sample
        sample = sorted(affected, key=lambda r: -r["n"])[:5]
        print("top 5 by row count:")
        for r in sample:
            print(f"  {r['case_id']}  {r['n']:,} rows")
        print("\n(dry run — pass --apply to actually rewrite)")
        return 0

    print("\napplying — assigning para_idx by rowid order within each case…")
    try:
        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS _p23_backup")
        cur.execute(
            "CREATE TABLE _p23_backup ("
            "rowid INTEGER PRIMARY KEY, old_para_idx INTEGER)"
        )
        # Snapshot current para_idx values for rows we're about to change.
        cur.execute(
            "INSERT INTO _p23_backup (rowid, old_para_idx) "
            "SELECT rowid, para_idx FROM paragraphs "
            "WHERE case_id IN (SELECT case_id FROM paragraphs WHERE para_idx IS NULL)"
        )
        # Use SQLite's row_number() per case to assign a stable index.
        cur.execute(
            "WITH ranked AS ("
            "  SELECT rowid, ROW_NUMBER() OVER ("
            "    PARTITION BY case_id ORDER BY rowid"
            "  ) - 1 AS new_idx "
            "  FROM paragraphs "
            "  WHERE case_id IN (SELECT case_id FROM paragraphs WHERE para_idx IS NULL)"
            ") "
            "UPDATE paragraphs "
            "SET para_idx = (SELECT new_idx FROM ranked WHERE ranked.rowid = paragraphs.rowid) "
            "WHERE rowid IN (SELECT rowid FROM ranked)"
        )
        con.commit()
    except Exception as exc:
        con.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    cur.execute("SELECT count(*) AS n FROM paragraphs WHERE para_idx IS NULL")
    remaining = cur.fetchone()["n"]
    print(f"done.  remaining para_idx IS NULL rows: {remaining:,}")
    print("backup retained as `_p23_backup`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
