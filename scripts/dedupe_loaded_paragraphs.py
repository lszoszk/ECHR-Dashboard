#!/usr/bin/env python3
"""
Remove the second copy of paragraphs that a forward SQL file inserted twice.

`INSERT OR IGNORE INTO cases` ignores a second load of the same case, but the
paragraph inserts that follow it do not, so loading one file twice doubles the
paragraphs of every case in it. This script repairs that.

It expects the SQL file that was loaded, counts the paragraph rows it holds per case,
and for each case compares that with the database:

  * database count == file count      -> clean, left alone
  * database count == 2 x file count  -> delete the later copy of each identical row
  * anything else                     -> stop without changing anything

After deleting it checks that every case is back to the file's count; if not, the
transaction is rolled back. The full-text index follows through the delete trigger.
Without --apply it only reports.

    python3 scripts/dedupe_loaded_paragraphs.py --db /data/echr_search.db --sql /tmp/x.sql          # report
    python3 scripts/dedupe_loaded_paragraphs.py --db /data/echr_search.db --sql /tmp/x.sql --apply
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter

ROW_RE = re.compile(r"^INSERT INTO paragraphs \([^)]*\) VALUES \('([^']+)'")
CONTENT = ("para_idx, section, hudoc_para_no, numbering_block, row_role, "
           "logical_para_idx, display_para_no, text")


def expected_counts(sql_path: str) -> Counter:
    counts: Counter = Counter()
    with open(sql_path, encoding="utf-8") as fh:
        for line in fh:
            m = ROW_RE.match(line)
            if m:
                counts[m.group(1)] += 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--sql", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    expected = expected_counts(args.sql)
    if not expected:
        print("no paragraph inserts found in the SQL file", file=sys.stderr)
        return 2
    con = sqlite3.connect(args.db, timeout=600, isolation_level=None)
    con.execute("PRAGMA busy_timeout = 600000")

    plan, clean = [], 0
    for case_id, want in sorted(expected.items()):
        have = con.execute("SELECT count(*) FROM paragraphs WHERE case_id = ?", (case_id,)).fetchone()[0]
        if have == want:
            clean += 1
        elif have == 2 * want:
            plan.append((case_id, want, have))
        else:
            print(f"STOP: {case_id} has {have} paragraphs; the file holds {want} (neither 1x nor 2x). Nothing changed.",
                  file=sys.stderr)
            return 3
    print(f"{len(expected)} cases in the file: {clean} clean, {len(plan)} doubled")
    for case_id, want, have in plan:
        print(f"  {case_id}: {have} -> {want}")
    if not plan or not args.apply:
        print("dry run: nothing changed" if plan else "nothing to do")
        return 0

    con.execute("BEGIN")
    try:
        for case_id, want, _ in plan:
            con.execute(
                f"DELETE FROM paragraphs WHERE case_id = ? AND rowid NOT IN "
                f"(SELECT min(rowid) FROM paragraphs WHERE case_id = ? GROUP BY {CONTENT})",
                (case_id, case_id))
            now = con.execute("SELECT count(*) FROM paragraphs WHERE case_id = ?", (case_id,)).fetchone()[0]
            if now != want:
                raise RuntimeError(f"{case_id}: {now} paragraphs left, expected {want}")
        con.execute("COMMIT")
    except Exception as exc:                                              # noqa: BLE001
        con.execute("ROLLBACK")
        print(f"ROLLED BACK: {exc}", file=sys.stderr)
        return 1
    print("done:", sum(have - want for _, want, have in plan), "duplicate paragraphs removed")
    print("checkpoint:", con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
    return 0


if __name__ == "__main__":
    sys.exit(main())
