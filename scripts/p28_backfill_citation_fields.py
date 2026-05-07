#!/usr/bin/env python3
"""
P28 — backfill citation fields into the `cases` table from the source JSONL.

Background
----------
The source JSONL (`docs/data/echr_cases.jsonl`) carries rich citation
metadata for ~7,800 of the older judgments:

  * strasbourg_caselaw    — list of cited Strasbourg cases (free text)
  * domestic_law          — list of cited domestic provisions
  * international_law     — list of cited international instruments
  * rules_of_court        — list of cited Rules of Court provisions

The original SQLite ingest dropped these columns, so the API never
exposed them.  The dashboard's `c.__citationRefs` and `c.__citedByCount`
machinery has been quietly reading empty arrays since switch to server
mode — every case shows "0 cites / 0 cited by" regardless of reality.

This pass adds the four columns to the `cases` schema (idempotent ALTER)
and populates them by streaming the JSONL.

Idempotent: re-running on a populated table is a no-op for unchanged
records.  Backups: `_p28_backup` snapshots only the rows we touched.

Usage
-----
    python3 scripts/p28_backfill_citation_fields.py \\
            [--db data/echr_search.db] \\
            [--jsonl data/echr_cases.jsonl] \\
            [--apply]

Without --apply, runs in dry-run mode and reports stats.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

CITATION_COLUMNS = [
    "strasbourg_caselaw",
    "domestic_law",
    "international_law",
    "rules_of_court",
]


def add_columns_if_missing(cur: sqlite3.Cursor) -> list[str]:
    """ALTER TABLE add columns that don't exist.  Returns the list added."""
    existing = {r[1] for r in cur.execute("PRAGMA table_info(cases)").fetchall()}
    added: list[str] = []
    for col in CITATION_COLUMNS:
        if col not in existing:
            # Stored as JSON arrays serialised to TEXT, mirroring the
            # convention used for `violation`, `non_violation`, `keywords`,
            # `originating_body` etc. in the existing schema.
            cur.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT")
            added.append(col)
    return added


def normalise_field(v) -> str | None:
    """Serialise list-of-strings to JSON; pass through None."""
    if v is None:
        return None
    if isinstance(v, list):
        cleaned = [str(x).strip() for x in v if str(x).strip()]
        if not cleaned:
            return None
        return json.dumps(cleaned, ensure_ascii=False)
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return json.dumps(v, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--db", default="data/echr_search.db")
    ap.add_argument("--jsonl", default="data/echr_cases.jsonl")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    jsonl_path = Path(args.jsonl).resolve()
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2
    if not jsonl_path.exists():
        print(f"ERROR: JSONL not found at {jsonl_path}", file=sys.stderr)
        return 2

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    if args.apply:
        added = add_columns_if_missing(cur)
        if added:
            print(f"added columns: {', '.join(added)}")
        con.commit()
    else:
        existing = {r[1] for r in cur.execute("PRAGMA table_info(cases)").fetchall()}
        missing = [c for c in CITATION_COLUMNS if c not in existing]
        print(f"would add columns: {', '.join(missing) if missing else '(none — schema already up to date)'}")

    print(f"\nstreaming {jsonl_path.name}…")
    plan: list[tuple] = []  # (case_id, sc, dl, il, rc)
    n_records = 0
    n_with_any = 0
    n_skipped_no_case_id = 0
    n_not_in_db = 0
    cur.execute("SELECT case_id FROM cases")
    in_db = {r["case_id"] for r in cur.fetchall()}

    with jsonl_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            n_records += 1
            cid = d.get("case_id")
            if not cid:
                n_skipped_no_case_id += 1
                continue
            if cid not in in_db:
                n_not_in_db += 1
                continue
            sc = normalise_field(d.get("strasbourg_caselaw"))
            dl = normalise_field(d.get("domestic_law"))
            il = normalise_field(d.get("international_law"))
            rc = normalise_field(d.get("rules_of_court"))
            if any(v is not None for v in (sc, dl, il, rc)):
                n_with_any += 1
                plan.append((cid, sc, dl, il, rc))

    print(f"  total JSONL records:       {n_records:,}")
    print(f"  no case_id (skipped):      {n_skipped_no_case_id:,}")
    print(f"  case_id not in DB:         {n_not_in_db:,}")
    print(f"  records with any citation: {n_with_any:,}")
    print(f"  rows queued for backfill:  {len(plan):,}")

    if not args.apply:
        sample = plan[:3]
        if sample:
            print("\nsample plan rows:")
            for row in sample:
                cid, sc, dl, il, rc = row
                print(f"  {cid}  sc={'Y' if sc else '.'} dl={'Y' if dl else '.'} "
                      f"il={'Y' if il else '.'} rc={'Y' if rc else '.'}")
        print("\n(dry run — pass --apply to commit)")
        return 0

    print("\napplying…")
    try:
        cur.execute("BEGIN")
        # Backup only rows that currently have at least one citation field
        # already populated (would only be the case on a re-run).  First
        # pass through a virgin schema, the backup is empty.
        cur.execute("DROP TABLE IF EXISTS _p28_backup")
        cur.execute(
            "CREATE TABLE _p28_backup ("
            "case_id TEXT PRIMARY KEY, "
            "old_strasbourg_caselaw TEXT, old_domestic_law TEXT, "
            "old_international_law TEXT, old_rules_of_court TEXT)"
        )
        for row in plan:
            cid, sc, dl, il, rc = row
            cur.execute(
                "INSERT INTO _p28_backup SELECT case_id, "
                "strasbourg_caselaw, domestic_law, international_law, "
                "rules_of_court FROM cases WHERE case_id = ?",
                [cid],
            )
        cur.executemany(
            "UPDATE cases SET strasbourg_caselaw = ?, domestic_law = ?, "
            "international_law = ?, rules_of_court = ? "
            "WHERE case_id = ?",
            [(sc, dl, il, rc, cid) for cid, sc, dl, il, rc in plan],
        )
        con.commit()
    except Exception as exc:
        con.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Quick post-conditions
    cur.execute(
        "SELECT count(*) FROM cases WHERE strasbourg_caselaw IS NOT NULL"
    )
    after = cur.fetchone()[0]
    print(f"\ndone.  rows now with strasbourg_caselaw: {after:,}")
    print("backup: `_p28_backup` (snapshots prior values for the touched rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
