#!/usr/bin/env python3
"""
Put back the non-breaking hyphens that the DOCX parser dropped.

Word stores "non‑pecuniary", "ill‑founded", "co‑accused" with a <w:noBreakHyphen/> element instead of a
character. p34_rebuild_from_hudoc.para_text_full ignored that element until 9 October 2026, so every
paragraph it produced read "nonpecuniary", "illfounded", "coaccused", and a search for "non-pecuniary
damage" or "manifestly ill-founded" missed it (about 2,000 judgments for "nonpecuniary" alone).

For each case this re-parses HUDOC's DOCX with the fixed parser (local cache, P34_DOCX_CACHE_DIR) and
changes a stored row only when the fixed text is the stored text plus hyphens: removing every "-" from
both gives the same string, and the fixed text has more hyphens. Nothing else in a row can change.
text_hash is recomputed as p38 computes it. The full-text index follows through the update trigger.

The SQL updates rows by (case_id, para_idx) and only while the text is still the old one, so it is safe to
run on the production database and to run twice. Rollback restores the old text the same way.

    python3 scripts/p71_restore_hyphens.py --db echr.db --sql-out p71.sql            # writes p71.sql(.rollback)
    python3 scripts/p71_restore_hyphens.py --db echr.db --apply                      # local copy
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def restored(stored: str, fixed: str) -> bool:
    """True when `fixed` is `stored` with hyphens put back (and only that)."""
    return (fixed != stored and fixed.replace("-", "") == stored.replace("-", "")
            and fixed.count("-") > stored.count("-"))


def _parser():
    import p60_monthly_update as p60
    return p60._load_module(p60.P34_PATH, "p34_rebuild_from_hudoc")


def case_changes(args: tuple[str, list[tuple[int, str]]]) -> tuple[str, list[tuple[int, str, str]], str | None]:
    """(case_id, [(para_idx, stored text)]) -> (case_id, [(para_idx, old, new)], error)."""
    cid, rows = args
    p34 = _parser()
    cache = Path(p34._DOCX_CACHE_DIR) / f"{cid}.docx"
    if not cache.exists():
        return cid, [], "not in the DOCX cache"
    try:
        parsed, _ = p34.parse_docx(cache.read_bytes())
    except Exception as exc:                                    # noqa: BLE001 - report and go on
        return cid, [], f"parse failed: {str(exc)[:80]}"
    by_plain: dict[str, str] = {}
    for r in parsed:
        text = r.get("text") or ""
        if "-" in text:
            by_plain.setdefault(text.replace("-", ""), text)
    out = []
    for idx, stored in rows:
        fixed = by_plain.get((stored or "").replace("-", ""))
        if fixed and restored(stored, fixed):
            out.append((idx, stored, fixed))
    return cid, out, None


def quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--sql-out", help="write the UPDATE statements here, and the rollback to <file>.rollback")
    ap.add_argument("--apply", action="store_true", help="apply to --db")
    ap.add_argument("--ids", help="only these case ids (comma-separated)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()

    import p38_batch_enrich as p38
    con = sqlite3.connect(args.db, timeout=600)
    ids = args.ids.split(",") if args.ids else [r[0] for r in con.execute("SELECT case_id FROM cases ORDER BY case_id")]
    work = []
    for cid in ids:
        work.append((cid, con.execute("SELECT para_idx, text FROM paragraphs WHERE case_id = ? ORDER BY para_idx",
                                      (cid,)).fetchall()))
    changes, errors = [], {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for k, (cid, rows, err) in enumerate(pool.map(case_changes, work, chunksize=20), 1):
            if err:
                errors[err] = errors.get(err, 0) + 1
            changes += [(cid, idx, old, new) for idx, old, new in rows]
            if k % 2000 == 0:
                print(f"  {k:,}/{len(work):,} cases, {len(changes):,} rows to fix", file=sys.stderr, flush=True)
    cases = len({c for c, *_ in changes})
    print(f"{len(work):,} cases read; {len(changes):,} rows in {cases:,} cases get their hyphens back; "
          f"not checked: {errors or 'none'}")

    forward = [f"UPDATE paragraphs SET text = {quote(new)}, text_hash = {quote(p38.hash_text(new))} "
               f"WHERE case_id = {quote(cid)} AND para_idx = {idx} AND text = {quote(old)};"
               for cid, idx, old, new in changes]
    backward = [f"UPDATE paragraphs SET text = {quote(old)}, text_hash = {quote(p38.hash_text(old))} "
                f"WHERE case_id = {quote(cid)} AND para_idx = {idx} AND text = {quote(new)};"
                for cid, idx, old, new in changes]
    if args.sql_out:
        Path(args.sql_out).write_text("\n".join(forward) + "\n")
        Path(args.sql_out + ".rollback").write_text("\n".join(backward) + "\n")
        print(f"wrote {args.sql_out} and {args.sql_out}.rollback")
    if args.apply:
        with con:
            for stmt in forward:
                con.execute(stmt)
        print("applied; checkpoint:", con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
    return 0


if __name__ == "__main__":
    sys.exit(main())
