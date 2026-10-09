#!/usr/bin/env python3
"""
Apply a forward SQL file (p60_monthly_update.py / p66_ingest_decisions.py output) in
small transactions, checkpointing the write-ahead log as it goes.

Why not one transaction: every insert also updates the full-text index, so a single
transaction over hundreds of thousands of paragraphs makes the WAL grow into the
gigabytes (a 20,000-paragraph load left a 754 MB WAL). On a shared VM with a few
GB free that can fill the disk. Here a transaction covers `--batch-cases` documents,
a PASSIVE checkpoint runs every few batches, and the log is truncated at the end.

A case that is already in the database is skipped together with its paragraphs, so loading
the same file twice changes nothing (the `INSERT OR IGNORE INTO cases` alone would not stop
the paragraph inserts that follow it from doubling).

The file is read statement by statement (sqlite3.complete_statement), so text values
containing newlines or semicolons are handled. The file's own BEGIN/COMMIT lines are
ignored. A load interrupted half way leaves complete documents only; the matching
.rollback file removes exactly the documents that file adds.

Usage
-----
    python3 scripts/apply_sql_batched.py --db /data/echr_search.db --sql /tmp/p66_decisions.sql
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

CASE_START = "INSERT OR IGNORE INTO cases"
CASE_ID = re.compile(r"VALUES \('([^']+)'")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--sql", required=True)
    ap.add_argument("--batch-cases", type=int, default=100)
    ap.add_argument("--checkpoint-every", type=int, default=5, help="batches between checkpoints")
    ap.add_argument("--batch-updates", type=int, default=2000,
                    help="UPDATE/DELETE statements outside a document per transaction (repair files)")
    ap.add_argument("--min-free-gb", type=float, default=3.0)
    args = ap.parse_args()

    db = Path(args.db)
    free_gb = shutil.disk_usage(db.parent).free / 1e9
    if free_gb < args.min_free_gb:
        print(f"ERROR: only {free_gb:.1f} GB free next to the database (need {args.min_free_gb})", file=sys.stderr)
        return 2

    con = sqlite3.connect(db, timeout=600, isolation_level=None)   # we issue BEGIN/COMMIT ourselves
    con.execute("PRAGMA busy_timeout = 600000")
    before = (con.execute("SELECT count(*) FROM cases").fetchone()[0],
              con.execute("SELECT count(*) FROM paragraphs").fetchone()[0])
    wal = Path(str(db) + "-wal")
    t0 = time.time()
    buf, cases, batches, in_tx, peak_wal = "", 0, 0, False, 0
    skipping, skipped = False, 0
    updates = 0
    optimize = None

    def commit_and_maybe_checkpoint():
        nonlocal in_tx, batches
        if in_tx:
            con.execute("COMMIT")
            in_tx = False
            batches += 1
            if batches % args.checkpoint_every == 0:
                con.execute("PRAGMA wal_checkpoint(PASSIVE)")
            if batches % 5 == 0:
                print(f"  {cases:,} documents loaded  ({time.time() - t0:.0f} s, WAL {wal.stat().st_size / 1e6 if wal.exists() else 0:.0f} MB)",
                      flush=True)

    with open(args.sql, encoding="utf-8") as fh:
        for line in fh:
            if not buf and line.strip() in ("BEGIN;", "COMMIT;"):
                continue
            buf += line
            if not sqlite3.complete_statement(buf):
                continue
            stmt, buf = buf, ""
            if stmt.startswith(CASE_START):
                m = CASE_ID.search(stmt)
                skipping = bool(m) and con.execute(
                    "SELECT 1 FROM cases WHERE case_id = ?", (m.group(1),)).fetchone() is not None
                if skipping:
                    skipped += 1
                    continue
                if cases % args.batch_cases == 0:
                    commit_and_maybe_checkpoint()
                    con.execute("BEGIN")
                    in_tx = True
                cases += 1
            elif stmt.lstrip()[:6].upper() in ("UPDATE", "DELETE") and not skipping:
                # repair files: many single-row updates, committed in batches like documents
                if updates % args.batch_updates == 0:
                    commit_and_maybe_checkpoint()
                    con.execute("BEGIN")
                    in_tx = True
                updates += 1
            elif "paragraphs_fts" in stmt[:40]:
                optimize = stmt                     # run once, after the last commit
                continue
            elif skipping:
                continue                            # the rest of a case that is already loaded
            con.execute(stmt)
            if wal.exists():
                peak_wal = max(peak_wal, wal.stat().st_size)
    commit_and_maybe_checkpoint()
    if optimize:
        print("optimising the full-text index ...", flush=True)
        con.execute(optimize)
    print("final checkpoint:", con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
    after = (con.execute("SELECT count(*) FROM cases").fetchone()[0],
             con.execute("SELECT count(*) FROM paragraphs").fetchone()[0])
    if skipped:
        print(f"skipped {skipped:,} documents that were already in the database")
    if updates:
        print(f"{updates:,} update/delete statements applied")
    print(f"cases {before[0]:,} -> {after[0]:,}   paragraphs {before[1]:,} -> {after[1]:,}   "
          f"peak WAL {peak_wal / 1e6:.0f} MB   {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
