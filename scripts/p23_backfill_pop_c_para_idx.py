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
    # Pull every (case_id, rowid) pair for affected cases in one shot, sort
    # in Python, build the (new_idx, rowid) update list, then push it back
    # via executemany.  An earlier draft did this with a correlated
    # subquery on a CTE; that took >15 min on the VM and never converged.
    # The two-step approach below finishes in ~30 s for ~480k rows.
    affected_case_ids = [r["case_id"] for r in affected]
    print(f"  loading rowids for {len(affected_case_ids):,} cases…")
    placeholders = ",".join("?" for _ in affected_case_ids)
    cur.execute(
        f"SELECT rowid, case_id, para_idx FROM paragraphs "
        f"WHERE case_id IN ({placeholders}) "
        f"ORDER BY case_id, rowid",
        affected_case_ids,
    )
    rows = cur.fetchall()
    print(f"  computing per-case indices over {len(rows):,} rows…")
    update_pairs = []           # (new_idx, rowid)
    backup_pairs = []           # (rowid, old_para_idx)
    last_case = None
    idx = 0
    for r in rows:
        if r["case_id"] != last_case:
            last_case = r["case_id"]
            idx = 0
        update_pairs.append((idx, r["rowid"]))
        backup_pairs.append((r["rowid"], r["para_idx"]))
        idx += 1
    try:
        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS _p23_backup")
        cur.execute(
            "CREATE TABLE _p23_backup ("
            "rowid INTEGER PRIMARY KEY, old_para_idx INTEGER)"
        )
        cur.executemany(
            "INSERT INTO _p23_backup (rowid, old_para_idx) VALUES (?, ?)",
            backup_pairs,
        )
        cur.executemany(
            "UPDATE paragraphs SET para_idx = ? WHERE rowid = ?",
            update_pairs,
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
