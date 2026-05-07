#!/usr/bin/env python3
"""
P31 — demote over-tagged operative_dispositif rows.

Background
----------
The original ingest mistakenly set ``numbering_block='operative_dispositif'``
on many rows that aren't dispositif clauses — typically Merits paragraphs
that happened to live in the Operative Part section because of upstream
mis-segmentation.  P25 (anchor-merge) folded follower rows INTO their
preceding anchor when an anchor verb was present, but never *demoted*
rows that had the tag without justification.

BAYRAMALIYEV v. TÜRKİYE (001-249495) is the canonical example: 29 rows
tagged ``operative_dispositif`` including text fragments like
``§§``, ``ALLEGED VIOLATION OF ARTICLE 5 § 4 OF THE CONVENTION``, and
``The applicant also alleged that…`` — none of which are dispositif
content.

This pass walks every row currently tagged as operative_dispositif and
demotes (clears the tag, also clears hudoc_para_no since P25 used those
slots for clause indices) the ones that:

  * do NOT begin with a leader verb (Decides / Declares / Dismisses /
    Holds / Notes / Joins / Strikes), AND
  * are NOT a continuation of an anchor row immediately preceding them.
    (Continuations within a clause are legitimate — e.g. the EUR amounts
    that P25 already merged into the anchor row should themselves be
    gone, but if any survived we keep them.)

A row is treated as a "continuation" when the most-recent ANCHOR row in
the same case+section appears within the previous 3 rows (by para_idx /
rowid).  Anything beyond that gap is almost certainly mis-tagged.

Usage
-----
    python3 scripts/p31_demote_overtagged_dispositif.py [--db PATH] [--apply]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

OPERATIVE_SECTIONS = ("Operative Part", "Operative part")
LEADER_VERBS = ("Decides", "Declares", "Dismisses", "Holds", "Notes", "Joins", "Strikes")
# Two anchor forms in the wild:
#   "Decides to strike the application…"           — modern style (post-2015 ish)
#   "1. Declares the application admissible;"      — older numbered style
# The bare-number prefix is OPTIONAL; either form qualifies as a dispositif anchor.
ANCHOR_RE = re.compile(
    rf"^\s*(?:\d+\s*\.\s*)?(?:{'|'.join(LEADER_VERBS)})\b"
)

# Cases where the row is clearly NOT dispositif content.
DEFINITELY_NOT_DISPOSITIF_RE = re.compile(
    r"^\s*(?:§§?\s*$"          # bare "§" / "§§"
    r"|ALLEGED VIOLATION"      # heading text
    r"|FOR THESE REASONS"      # super-heading bleed
    r"|APPLICATION OF ARTICLE\s+41"
    r"|JUST SATISFACTION"
    r"|OTHER COMPLAINTS"
    r"|THE COURT'S ASSESSMENT"
    r")",
    re.IGNORECASE,
)


def is_anchor(text: str) -> bool:
    return bool(text) and bool(ANCHOR_RE.match(text.lstrip()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/echr_search.db")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    placeholders = ",".join("?" for _ in OPERATIVE_SECTIONS)
    cur.execute(
        f"SELECT rowid, case_id, section, para_idx, hudoc_para_no, "
        f"       numbering_block, text "
        f"FROM paragraphs "
        f"WHERE numbering_block = 'operative_dispositif' "
        f"  AND section IN ({placeholders}) "
        f"ORDER BY case_id, para_idx, rowid",
        OPERATIVE_SECTIONS,
    )
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in cur.fetchall():
        by_case[r["case_id"]].append(dict(r))

    print(f"cases with operative_dispositif rows: {len(by_case):,}")

    plan_demote = []   # (rowid, case_id, old_hudoc, old_text)
    n_kept = 0

    for cid, rows in by_case.items():
        # Walk in document order; track last-anchor index.
        last_anchor_idx = -10
        for i, r in enumerate(rows):
            text = (r["text"] or "").strip()
            if is_anchor(text):
                last_anchor_idx = i
                n_kept += 1
                continue
            # Non-anchor: keep if it's an immediate-tail continuation,
            # demote otherwise.
            if (i - last_anchor_idx) <= 1 and not DEFINITELY_NOT_DISPOSITIF_RE.match(text):
                n_kept += 1
                continue
            plan_demote.append((r["rowid"], cid, r["hudoc_para_no"], text[:80]))

    print(f"  rows kept (anchors + immediate followers):  {n_kept:,}")
    print(f"  rows queued for demotion:                   {len(plan_demote):,}")

    # Sample for sanity
    sample_cases: dict = {}
    for rowid, cid, _, snippet in plan_demote:
        sample_cases.setdefault(cid, []).append(snippet)
    print(f"  affected cases: {len(sample_cases):,}")
    print()
    print("sample demotion rows (first 8 cases):")
    for i, (cid, snippets) in enumerate(list(sample_cases.items())[:8]):
        print(f"  {cid}  ({len(snippets)} demotions)")
        for s in snippets[:2]:
            print(f"     - {s!r}")

    if not args.apply:
        print("\n(dry run — pass --apply to commit)")
        return 0

    print("\napplying…")
    try:
        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS _p31_backup")
        cur.execute(
            "CREATE TABLE _p31_backup ("
            "rowid INTEGER PRIMARY KEY, case_id TEXT, "
            "old_hudoc_para_no INTEGER, old_text_excerpt TEXT)"
        )
        cur.executemany(
            "INSERT INTO _p31_backup VALUES (?, ?, ?, ?)",
            plan_demote,
        )
        # Demote: clear numbering_block + hudoc_para_no.  Keep section as-is
        # (these are still in Operative Part by location, just not real
        # dispositif clauses).
        cur.executemany(
            "UPDATE paragraphs "
            "SET numbering_block = NULL, hudoc_para_no = NULL "
            "WHERE rowid = ?",
            [(rowid,) for rowid, _, _, _ in plan_demote],
        )
        con.commit()
    except Exception as exc:
        con.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"done.  Demoted {len(plan_demote):,} rows across {len(sample_cases):,} cases.")
    print("backup retained as `_p31_backup`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
