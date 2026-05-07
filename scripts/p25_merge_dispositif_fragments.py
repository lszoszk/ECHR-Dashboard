#!/usr/bin/env python3
"""
P25 — merge over-segmented operative-part dispositif fragments.

Background
----------
HUDOC presents the operative part as a small, fixed list of numbered
clauses, e.g. for L.P. v. Hungary:

    1.  Decides to strike the applicant's complaint under Article 13 of the
        Convention out of its list of cases;
    2.  Declares the complaint concerning Article 8 admissible and the
        remainder of the application inadmissible;
    3.  Holds that there has been a violation of Article 8 of the Convention;
    4.  Holds
        (a)  that the respondent State is to pay …
        (b)  that from the expiry of the above-mentioned three months …
    5.  Dismisses the remainder of the applicant's claim for just satisfaction.

The PDF→DB segmenter splits each multi-line clause on every newline /
bullet break, so L.P.'s 5-clause dispositif lands as 8 rows in the DB,
all with `hudoc_para_no=NULL`.  The dashboard renders them as eight
"Op. ¶ —" rows — visually noisy and missing the canonical clause numbers.

This pass walks each case's operative-part rows in order, identifies the
"anchor" rows (those that START with one of the dispositif leader verbs:
Decides / Declares / Dismisses / Holds / Notes / Joins / Strikes), and
appends every following non-anchor row's text to the most recent anchor
until the next anchor (or the end of the section).  The anchor row's
hudoc_para_no is set to the clause's 1-based position; the merged
followers are deleted.

Detection rule for "anchor"
---------------------------
Match `^\s*(Decides|Declares|Dismisses|Holds|Notes|Joins|Strikes)\b` on
the row's stripped text, after trimming any stray "(a)" / "(b)" sub-bullet
markers.  Conservative — we only merge when there's an unambiguous leader
verb, otherwise the row stays put.

Side effects
------------
* anchor row's text grows;
* anchor row's hudoc_para_no = clause_index_within_case (1, 2, 3, …);
* anchor row's numbering_block = 'operative_dispositif' (already true for
  most, ensured for the rest);
* follower rows DELETEd;
* every change snapshotted into `_p25_backup`.

Usage
-----
    python3 scripts/p25_merge_dispositif_fragments.py [--db PATH] [--apply]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

OPERATIVE_SECTIONS = ("Operative Part", "Operative part")

# Anchor verbs from real HUDOC dispositif clauses.  Order doesn't matter.
LEADER_VERBS = ("Decides", "Declares", "Dismisses", "Holds", "Notes", "Joins", "Strikes")
ANCHOR_RE = re.compile(
    rf"^\s*(?:{'|'.join(LEADER_VERBS)})\b",
)


def is_anchor(text: str) -> bool:
    return bool(text) and bool(ANCHOR_RE.match(text.lstrip()))


def merge_text(parts: list[str]) -> str:
    """Join text fragments back into a single dispositif clause.  Most
    fragments are pure mid-sentence continuations and need a single space;
    a few are punctuation tails (";", "."), which we attach without space."""
    out = ""
    for p in parts:
        s = (p or "").strip()
        if not s:
            continue
        if not out:
            out = s
        elif out[-1:] in {"-", "(", "[", "/", "—", "“"}:
            out = out + s
        elif s[:1] in {",", ".", ";", ":", ")", "]", "”"}:
            out = out + s
        else:
            out = out + " " + s
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--db", default="data/echr_search.db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit-cases", type=int, default=0,
                    help="Only process the first N cases (debug).")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cols = {r[1] for r in cur.execute("PRAGMA table_info(paragraphs)").fetchall()}
    if "hudoc_para_no" not in cols or "numbering_block" not in cols:
        print("ERROR: target DB has no hudoc_para_no / numbering_block columns.", file=sys.stderr)
        return 2

    # Pull every operative-part row, ordered so the natural document flow is
    # preserved within each case.  para_idx is filled (P23 ran), but rowid
    # is the canonical sequence in case para_idx was tied for some rows.
    placeholders = ",".join("?" for _ in OPERATIVE_SECTIONS)
    cur.execute(
        f"SELECT rowid, case_id, section, para_idx, hudoc_para_no, "
        f"       numbering_block, text "
        f"FROM paragraphs "
        f"WHERE section IN ({placeholders}) "
        f"ORDER BY case_id, para_idx, rowid",
        OPERATIVE_SECTIONS,
    )
    rows = cur.fetchall()

    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_case[r["case_id"]].append(dict(r))

    case_ids = list(by_case.keys())
    if args.limit_cases:
        case_ids = case_ids[: args.limit_cases]

    print(f"operative-part cases: {len(case_ids):,}")

    plan_anchor_updates = []   # [(rowid, new_text, clause_idx, case_id), …]
    plan_drop_rowids: list[int] = []
    backup_anchor: list[tuple] = []   # (rowid, old_text, old_hudoc_para_no, old_numbering_block)
    backup_drop:   list[tuple] = []   # (rowid, case_id, section, para_idx, hudoc_para_no, numbering_block, text, anchor_rowid)

    cases_with_clauses = 0
    cases_with_no_anchor = 0
    total_clauses = 0

    for case_id in case_ids:
        case_rows = by_case[case_id]
        # Walk rows.  A clause = anchor + zero-or-more follower rows up to the
        # next anchor.  Rows that come BEFORE the first anchor have no anchor
        # to attach to — leave them alone (they're typically section headers
        # like "FOR THESE REASONS, THE COURT, UNANIMOUSLY," or stray content).
        anchor_idx_in_case = 0
        current_anchor: dict | None = None
        followers: list[dict] = []
        clauses: list[tuple[dict, list[dict]]] = []
        for r in case_rows:
            if is_anchor(r["text"]):
                if current_anchor is not None:
                    clauses.append((current_anchor, followers))
                current_anchor = r
                followers = []
            else:
                if current_anchor is not None:
                    followers.append(r)
                # else: pre-anchor row (heading or stray) — leave untouched
        if current_anchor is not None:
            clauses.append((current_anchor, followers))

        if not clauses:
            cases_with_no_anchor += 1
            continue

        # Now lay out the merge plan for this case.
        for clause_idx, (anchor, fols) in enumerate(clauses, start=1):
            if not fols and anchor["hudoc_para_no"] == clause_idx \
                    and (anchor["numbering_block"] == "operative_dispositif"):
                # Nothing to do for this clause.
                continue
            new_text = merge_text([anchor["text"]] + [f["text"] for f in fols])
            plan_anchor_updates.append(
                (anchor["rowid"], new_text, clause_idx, case_id)
            )
            backup_anchor.append((
                anchor["rowid"], anchor["text"],
                anchor["hudoc_para_no"], anchor["numbering_block"],
            ))
            for f in fols:
                plan_drop_rowids.append(f["rowid"])
                backup_drop.append((
                    f["rowid"], f["case_id"], f["section"],
                    f["para_idx"], f["hudoc_para_no"],
                    f["numbering_block"], f["text"], anchor["rowid"],
                ))
            total_clauses += 1
        cases_with_clauses += 1

    print(f"  cases with at least one anchor:    {cases_with_clauses:,}")
    print(f"  cases with no anchor (untouched):  {cases_with_no_anchor:,}")
    print(f"  clauses to write/renumber:         {total_clauses:,}")
    print(f"  follower rows to delete:           {len(plan_drop_rowids):,}")
    print(f"  anchor rows to update:             {len(plan_anchor_updates):,}")

    if not args.apply:
        # Show one sample case for sanity.
        if plan_anchor_updates:
            sample_case = plan_anchor_updates[0][3]
            print(f"\nsample case `{sample_case}` AFTER merge:")
            for u in [u for u in plan_anchor_updates if u[3] == sample_case]:
                snippet = u[1][:100] + ("…" if len(u[1]) > 100 else "")
                print(f"   Op. {u[2]}  {snippet}")
        print("\n(dry run — pass --apply to commit)")
        return 0

    print("\napplying…")
    try:
        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS _p25_backup_anchors")
        cur.execute("DROP TABLE IF EXISTS _p25_backup_drops")
        cur.execute(
            "CREATE TABLE _p25_backup_anchors ("
            "rowid INTEGER PRIMARY KEY, old_text TEXT, "
            "old_hudoc_para_no INTEGER, old_numbering_block TEXT)"
        )
        cur.execute(
            "CREATE TABLE _p25_backup_drops ("
            "rowid INTEGER PRIMARY KEY, case_id TEXT, section TEXT, "
            "para_idx INTEGER, hudoc_para_no INTEGER, "
            "numbering_block TEXT, text TEXT, anchor_rowid INTEGER)"
        )
        cur.executemany(
            "INSERT INTO _p25_backup_anchors VALUES (?,?,?,?)",
            backup_anchor,
        )
        cur.executemany(
            "INSERT INTO _p25_backup_drops VALUES (?,?,?,?,?,?,?,?)",
            backup_drop,
        )
        # Anchor updates
        cur.executemany(
            "UPDATE paragraphs "
            "SET text = ?, hudoc_para_no = ?, "
            "    numbering_block = 'operative_dispositif' "
            "WHERE rowid = ?",
            [(text, idx, rowid) for (rowid, text, idx, _case) in plan_anchor_updates],
        )
        # Follower deletes — chunk to dodge SQLite parameter limits.
        chunk = 500
        for i in range(0, len(plan_drop_rowids), chunk):
            batch = plan_drop_rowids[i:i+chunk]
            ph = ",".join("?" for _ in batch)
            cur.execute(f"DELETE FROM paragraphs WHERE rowid IN ({ph})", batch)
        con.commit()
    except Exception as exc:
        con.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"done.  {len(plan_anchor_updates):,} clauses rewritten, "
          f"{len(plan_drop_rowids):,} follower rows deleted.")
    print("backup retained as `_p25_backup_anchors` + `_p25_backup_drops`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
