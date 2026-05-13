#!/usr/bin/env python3
"""Apply P38 batch-enrichment TSV onto the live `paragraphs` table.

Runs on the VM (or wherever the SQLite DB lives) after `scp`-ing the
enrichment TSV produced by `p38_batch_enrich.py`.

Pipeline:

    (local) p38_batch_enrich.py  ──►  TSV
    TSV  ──►  scp to VM  ──►  this script  ──►  UPDATE paragraphs

Strategy:
  1.  Ensure the three new columns (role_top, role_score, confidence_band)
      and a join helper column (text_hash) exist on `paragraphs`.
  2.  Populate text_hash for every row whose hash is NULL (one-time cost;
      idempotent — re-runs are no-ops).
  3.  Load the enrichment TSV into a side table indexed by
      (case_id, text_hash).
  4.  Run a single JOIN-driven UPDATE that fills role_top/role_score/band
      for every paragraph whose (case_id, text_hash) appears in the TSV.

Why text_hash, not para_idx:
  para_idx may drift between P37 rebuild iterations (e.g. if a row is
  filtered or merged); text_hash is stable as long as the text itself
  doesn't change.  Per-case scoping eliminates cross-case collisions.

Usage (on the VM):
    python3 p38_apply_enrichment_vm.py \\
        /home/amuvmuser/echr/data/echr_search.db \\
        /tmp/p38_enrichment.tsv

Idempotent: safe to re-run.  Existing role_top values are overwritten
only for rows where the TSV provides new values.
"""
from __future__ import annotations
import argparse
import hashlib
import re
import sqlite3
import sys
import time
from pathlib import Path


WHITESPACE_RE = re.compile(r"\s+")


def hash_text(text: str) -> str:
    """Same normalization + hash as p38_batch_enrich.py.  Output is the
    first 16 hex chars of sha1(normalize(text))."""
    norm = WHITESPACE_RE.sub(" ", (text or "").strip()).lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def ensure_schema(con: sqlite3.Connection) -> None:
    cur = con.execute("PRAGMA table_info(paragraphs)")
    existing = {row[1] for row in cur.fetchall()}
    for col, typ in [
        ("text_hash", "TEXT"),
        ("role_top", "TEXT"),
        ("role_score", "REAL"),
        ("confidence_band", "TEXT"),
    ]:
        if col not in existing:
            con.execute(f"ALTER TABLE paragraphs ADD COLUMN {col} {typ}")
            print(f"  + added column paragraphs.{col} {typ}")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_paragraphs_hash "
        "ON paragraphs(case_id, text_hash)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_paragraphs_role "
        "ON paragraphs(role_top, confidence_band)"
    )
    con.commit()


def populate_hashes(con: sqlite3.Connection, batch_size: int = 10000) -> int:
    """Fill text_hash for every row where it's currently NULL.
    Returns the number of rows hashed."""
    cur = con.execute("SELECT COUNT(*) FROM paragraphs WHERE text_hash IS NULL")
    pending = cur.fetchone()[0]
    if pending == 0:
        print("  text_hash already populated for every row")
        return 0
    print(f"  hashing {pending:,} rows…")
    done = 0
    start = time.time()
    while True:
        rows = con.execute(
            "SELECT rowid, text FROM paragraphs "
            "WHERE text_hash IS NULL LIMIT ?",
            (batch_size,),
        ).fetchall()
        if not rows:
            break
        updates = [(hash_text(t or ""), rid) for rid, t in rows]
        con.executemany(
            "UPDATE paragraphs SET text_hash = ? WHERE rowid = ?",
            updates,
        )
        con.commit()
        done += len(rows)
        if done % (batch_size * 5) == 0 or len(rows) < batch_size:
            elapsed = time.time() - start
            rate = done / elapsed if elapsed else 0
            print(
                f"    hashed {done:,}/{pending:,}  "
                f"rate={rate:,.0f} rows/s",
                flush=True,
            )
    return done


def load_enrichment(con: sqlite3.Connection, tsv: Path) -> int:
    """Load TSV into a permanent side table _p38_lookup
    keyed by (case_id, text_hash).  Returns row count."""
    con.execute("DROP TABLE IF EXISTS _p38_lookup")
    con.execute(
        """
        CREATE TABLE _p38_lookup (
            case_id TEXT NOT NULL,
            text_hash TEXT NOT NULL,
            role_top TEXT,
            role_score REAL,
            confidence_band TEXT,
            PRIMARY KEY (case_id, text_hash)
        ) WITHOUT ROWID
        """
    )
    inserted = 0
    skipped = 0
    with tsv.open(encoding="utf-8") as f:
        first = f.readline()
        # Detect header
        if first.startswith("case_id"):
            pass
        else:
            # No header — first line is data, rewind
            f.seek(0)
        batch = []
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 7:
                skipped += 1
                continue
            cid, _block_idx, text_hash, _snippet, role, score, band = parts[:7]
            try:
                score_f = float(score)
            except ValueError:
                skipped += 1
                continue
            batch.append((cid, text_hash, role, score_f, band))
            if len(batch) >= 50000:
                con.executemany(
                    "INSERT OR REPLACE INTO _p38_lookup VALUES (?,?,?,?,?)",
                    batch,
                )
                inserted += len(batch)
                batch.clear()
        if batch:
            con.executemany(
                "INSERT OR REPLACE INTO _p38_lookup VALUES (?,?,?,?,?)",
                batch,
            )
            inserted += len(batch)
    con.commit()
    print(f"  loaded {inserted:,} enrichment rows  (skipped {skipped:,} malformed)")
    return inserted


def apply_enrichment(con: sqlite3.Connection) -> tuple[int, int]:
    """JOIN-update paragraphs.role_top/score/band from _p38_lookup.
    Returns (updated, unmatched)."""
    con.execute(
        """
        UPDATE paragraphs
           SET role_top        = (SELECT role_top        FROM _p38_lookup
                                   WHERE _p38_lookup.case_id = paragraphs.case_id
                                     AND _p38_lookup.text_hash = paragraphs.text_hash),
               role_score      = (SELECT role_score      FROM _p38_lookup
                                   WHERE _p38_lookup.case_id = paragraphs.case_id
                                     AND _p38_lookup.text_hash = paragraphs.text_hash),
               confidence_band = (SELECT confidence_band FROM _p38_lookup
                                   WHERE _p38_lookup.case_id = paragraphs.case_id
                                     AND _p38_lookup.text_hash = paragraphs.text_hash)
         WHERE EXISTS (SELECT 1 FROM _p38_lookup
                        WHERE _p38_lookup.case_id = paragraphs.case_id
                          AND _p38_lookup.text_hash = paragraphs.text_hash)
        """
    )
    con.commit()
    updated = con.execute(
        "SELECT COUNT(*) FROM paragraphs WHERE role_top IS NOT NULL"
    ).fetchone()[0]
    unmatched = con.execute(
        "SELECT COUNT(*) FROM _p38_lookup l "
        "WHERE NOT EXISTS (SELECT 1 FROM paragraphs p "
        "WHERE p.case_id = l.case_id AND p.text_hash = l.text_hash)"
    ).fetchone()[0]
    return updated, unmatched


def summary(con: sqlite3.Connection) -> None:
    print("\n--- enrichment summary ---")
    rows = con.execute(
        "SELECT role_top, confidence_band, COUNT(*) "
        "FROM paragraphs WHERE role_top IS NOT NULL "
        "GROUP BY role_top, confidence_band ORDER BY 3 DESC"
    ).fetchall()
    for role, band, n in rows:
        print(f"  {role:20s} {band:10s} {n:>10,}")
    null_count = con.execute(
        "SELECT COUNT(*) FROM paragraphs WHERE role_top IS NULL"
    ).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0]
    print(f"\n  total paragraphs:   {total:,}")
    print(f"  with role_top set:  {total - null_count:,}")
    print(f"  unmatched (NULL):   {null_count:,}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", type=Path, help="Path to echr_search.db")
    ap.add_argument("tsv", type=Path, help="P38 enrichment TSV")
    ap.add_argument("--keep-lookup", action="store_true",
                    help="Keep _p38_lookup table after apply (default: drop)")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"ERROR: db not found: {args.db}", file=sys.stderr)
        return 2
    if not args.tsv.exists():
        print(f"ERROR: tsv not found: {args.tsv}", file=sys.stderr)
        return 2

    con = sqlite3.connect(str(args.db))
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")

    print(f"db:  {args.db}")
    print(f"tsv: {args.tsv}")

    print("\n[1/4] schema check + index creation")
    ensure_schema(con)

    print("\n[2/4] populate text_hash on existing rows")
    populate_hashes(con)

    print("\n[3/4] load enrichment TSV")
    load_enrichment(con, args.tsv)

    print("\n[4/4] apply enrichment (UPDATE JOIN _p38_lookup)")
    updated, unmatched = apply_enrichment(con)
    print(f"  paragraphs with role_top set: {updated:,}")
    print(f"  enrichment rows that didn't match any paragraph: {unmatched:,}")

    summary(con)

    if not args.keep_lookup:
        con.execute("DROP TABLE _p38_lookup")
        con.commit()

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
