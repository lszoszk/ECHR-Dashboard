#!/usr/bin/env python3
"""P37 schema migration for source-exact paragraph rows.

Adds optional columns used by the current API/build pipeline to an existing
SQLite DB.  Safe to run repeatedly.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


CASE_COLUMNS = {
    "strasbourg_caselaw": "TEXT",
    "domestic_law": "TEXT",
    "international_law": "TEXT",
    "rules_of_court": "TEXT",
}

PARAGRAPH_COLUMNS = {
    "hudoc_para_no": "INTEGER",
    "numbering_block": "TEXT",
    "row_role": "TEXT",
}


def add_missing(cur: sqlite3.Cursor, table: str, columns: dict[str, str]) -> list[str]:
    existing = {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
    added = []
    for name, sql_type in columns.items():
        if name not in existing:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
            added.append(f"{table}.{name}")
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/echr_search.db")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}")
        return 2

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    added = []
    try:
        cur.execute("BEGIN")
        added.extend(add_missing(cur, "cases", CASE_COLUMNS))
        added.extend(add_missing(cur, "paragraphs", PARAGRAPH_COLUMNS))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    if added:
        print("added columns:")
        for col in added:
            print(f"  {col}")
    else:
        print("schema already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
