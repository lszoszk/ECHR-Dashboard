#!/usr/bin/env python3
"""
P22 — normalize case_articles compound rows into individual article tokens.

Background
----------
HUDOC's `ar` field for many cases is exported as a comma-separated list
("34, 6 § 1, 13, 35 § 3, 41").  Earlier ingest paths inserted those values
verbatim into `case_articles`, leaving the table with a mix of clean rows
("8") and compound rows ("34, 8, 41, 44 § 2") for the same case.

The /api/facets endpoint then surfaced 4,000+ "article" values in the
filter rail, dominated by 3,900 compound junk strings.  The frontend
patched display by client-side splitting; the backend filters needed the
EXISTS+LIKE workaround in `_build_case_filter_sql`.  Both are stop-gaps.

This pass replaces the compound rows with individual tokens.

Usage
-----
    python3 scripts/p22_normalize_case_articles.py [--db PATH] [--apply]

Without --apply, the script runs in dry-run mode and prints stats only.
With --apply, it backs up current case_articles to `_p22_backup` then
rewrites the table in a single transaction.

Idempotent: running twice does nothing on the second pass.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

_WS_RE = re.compile(r"\s+")

# Valid ECHR article reference: main convention articles 1-59 with optional
# sub-clauses (numeric "-1", "§ 1", or letter "-a"); protocol articles
# P1 through P16 with mandatory leading sub-clause.  Anything outside this
# (e.g. "1469 § 5", "509 § 10") is a domestic-law reference that escaped
# from the case text into the `ar` field during legacy ingest and has no
# place in a "Convention article" filter.
_ECHR_ARTICLE_RE = re.compile(
    r"""^(?:
        P(?:[1-9]|1[0-6])-\d{1,2}(?:-\d{1,2})?(?:-[a-z])?    # protocol
        |
        (?:[1-9]|[1-5][0-9])                                  # main 1-59
            (?:-\d{1,2})?
            (?:\s*§\s*\d{1,2})?
            (?:-[a-z])?
    )$""",
    re.VERBOSE,
)


def is_valid_echr_article(token: str) -> bool:
    return bool(_ECHR_ARTICLE_RE.match(token or ""))


def split_article_values(raw: str) -> list[str]:
    """Mirror of backend/main.py::_split_article_values — keep these aligned."""
    if not raw:
        return []
    cleaned = _WS_RE.sub(" ", str(raw).strip())
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--db",
        default="data/echr_search.db",
        help="Path to the SQLite DB (default: data/echr_search.db).",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Actually rewrite the table.  Without this flag, the script "
        "only reports what would change.",
    )
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("SELECT count(*) AS n FROM case_articles")
    total_rows = cur.fetchone()["n"]
    print(f"case_articles rows: {total_rows:,}")

    cur.execute(
        "SELECT count(*) AS n FROM case_articles WHERE article LIKE '%,%'"
    )
    compound_rows = cur.fetchone()["n"]
    print(f"compound rows (contain ','): {compound_rows:,}")

    if compound_rows == 0:
        print("Already normalized — nothing to do.")
        return 0

    cur.execute("SELECT case_id, article FROM case_articles")
    rows = cur.fetchall()

    new_pairs: set[tuple[str, str]] = set()
    dropped_tokens: dict[str, int] = {}
    for r in rows:
        for tok in split_article_values(r["article"]):
            if is_valid_echr_article(tok):
                new_pairs.add((r["case_id"], tok))
            else:
                dropped_tokens[tok] = dropped_tokens.get(tok, 0) + 1

    print(f"distinct (case_id, article) pairs after split + filter: {len(new_pairs):,}")
    print(
        f"net change: {len(new_pairs) - total_rows:+,} rows "
        f"({(len(new_pairs) - total_rows) / total_rows * 100:+.1f}%)"
    )

    cur.execute(
        "SELECT count(DISTINCT article) AS n FROM case_articles"
    )
    distinct_before = cur.fetchone()["n"]
    distinct_after = len({tok for _, tok in new_pairs})
    print(f"distinct article values: {distinct_before:,} → {distinct_after:,}")

    if dropped_tokens:
        print(f"\ndropped {sum(dropped_tokens.values()):,} occurrences of "
              f"{len(dropped_tokens):,} non-ECHR tokens "
              f"(domestic-law refs etc.).  Top 10:")
        for tok, n in sorted(dropped_tokens.items(), key=lambda kv: -kv[1])[:10]:
            print(f"  {n:>6,}× {tok!r}")

    if not args.apply:
        print("\n(dry run — pass --apply to rewrite)")
        return 0

    print("\napplying…")
    try:
        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS _p22_backup")
        cur.execute(
            "CREATE TABLE _p22_backup AS SELECT * FROM case_articles"
        )
        cur.execute("DELETE FROM case_articles")
        cur.executemany(
            "INSERT INTO case_articles (case_id, article) VALUES (?, ?)",
            sorted(new_pairs),
        )
        con.commit()
    except Exception as exc:
        con.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"done.  Backup retained as `_p22_backup` ({total_rows:,} rows).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
