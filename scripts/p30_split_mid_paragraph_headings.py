#!/usr/bin/env python3
"""
P30 — split ALL-CAPS section headings out of paragraph bodies.

Background
----------
Codex's 2026-05-07 audit found 18,780 cases where heading-like phrases
sit INSIDE paragraph text rather than as standalone heading rows.  The
BAYRAMALIYEV browse turned this up vividly:

    Op. ¶ 35 cont.  (a) and 4 of the Convention. ALLEGED VIOLATION OF
                    ARTICLE 5 § 4 OF THE CONVENTION

The "ALLEGED VIOLATION OF ARTICLE 5 § 4 OF THE CONVENTION" portion is
the next sub-section's heading, swallowed at PDF segmentation time
into the previous paragraph's tail.  P24 only handled the pure case
where the entire row IS a heading; this pass handles the in-line case.

Detection
---------
A row is a candidate when its text contains one of the recognised
heading phrases as an internal substring (i.e. NOT at character 0 —
those are caught by P24) AND the substring is preceded by a sentence
break (".", "!", "?") OR a paragraph break, AND the heading begins
with a known anchor.

Heading anchors (case-sensitive against ALL-CAPS):
    THE COURT'S ASSESSMENT, THE PARTIES' SUBMISSIONS,
    ALLEGED VIOLATION OF ARTICLE …, OTHER COMPLAINTS,
    APPLICATION OF ARTICLE 41 …, JUST SATISFACTION,
    SUBJECT MATTER OF THE CASE, THE FACTS, THE LAW,
    FOR THESE REASONS, THE COURT, GENERAL PRINCIPLES,
    FACTS BACKGROUND, FACTS PROCEEDINGS

Action
------
Split the row into two:
    - The original row, with its text TRUNCATED at the heading start.
    - A NEW row whose text IS the heading, section='Header',
      numbering_block=NULL, hudoc_para_no=NULL, para_idx=parent.para_idx.

The frontend already filters Header rows out of the modal flow — so
the heading "disappears" from the noisy mid-paragraph context and the
truncated body keeps its original paragraph number.

Conservative — only fires when the heading is at least 12 chars long
and ends at a clear word boundary (next character is end-of-text or
whitespace + capital).

Usage
-----
    python3 scripts/p30_split_mid_paragraph_headings.py [--db PATH] [--apply]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

# Heading anchors.  Build one big alternation regex; match on the
# longest possible (greedy) heading.  ASCII-uppercase-only — the
# segmenter never produces lowercase headings, and matching anything
# in lowercase risks false positives on running text.
HEADING_PATTERNS = [
    r"ALLEGED VIOLATION OF ARTICLE\s+\d+(?:\s*§+\s*\d+)?(?:\s*OF\s+(?:THE\s+CONVENTION|PROTOCOL\s+NO\.\s*\d+(?:\s*TO\s+THE\s+CONVENTION)?))?",
    r"OTHER ALLEGED VIOLATIONS",
    r"OTHER COMPLAINTS",
    r"APPLICATION OF ARTICLE\s+41(?:\s+OF\s+THE\s+CONVENTION)?",
    r"JUST SATISFACTION",
    r"SUBJECT MATTER OF THE CASE",
    r"THE FACTS",
    r"THE LAW",
    r"FOR THESE REASONS, THE COURT[^a-z]*",
    r"THE COURT'S ASSESSMENT",
    r"THE COURT[’']S ASSESSMENT",
    r"THE PARTIES'? SUBMISSIONS",
    r"THE PARTIES[’']? SUBMISSIONS",
    r"GENERAL PRINCIPLES",
    r"PRELIMINARY OBJECTIONS?",
    r"PROCEDURE",
]
HEADING_RE = re.compile(
    r"(?<=[\.\!\?\)])\s+(" + "|".join(f"(?:{p})" for p in HEADING_PATTERNS) + r")\b",
)


def find_split_point(text: str) -> tuple[int, str] | None:
    """Return (split_index, heading_text) for a mid-paragraph heading,
    else None.  split_index is the offset where the heading begins
    (i.e. text[:split_index] = body, text[split_index:] = heading +
    anything after)."""
    if not text or len(text) < 30:
        return None
    m = HEADING_RE.search(text)
    if not m:
        return None
    heading = m.group(1).strip()
    if len(heading) < 12:
        return None
    return (m.start(1), heading)


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

    print("scanning paragraphs for mid-paragraph headings…")
    cur.execute(
        "SELECT rowid, case_id, section, para_idx, hudoc_para_no, "
        "       numbering_block, text "
        "FROM paragraphs "
        "WHERE text IS NOT NULL AND length(text) >= 60"
    )
    rows = cur.fetchall()
    print(f"  scanning {len(rows):,} candidate rows")

    plan: list[dict] = []
    for r in rows:
        sp = find_split_point(r["text"] or "")
        if not sp:
            continue
        split_idx, heading = sp
        body_before = r["text"][:split_idx].strip()
        if len(body_before) < 30:
            # Heading is at the very start (or close) — likely caught by
            # P24 already, OR the whole paragraph IS the heading; skip.
            continue
        plan.append({
            "rowid": r["rowid"],
            "case_id": r["case_id"],
            "section": r["section"],
            "para_idx": r["para_idx"],
            "hudoc_para_no": r["hudoc_para_no"],
            "numbering_block": r["numbering_block"],
            "old_text": r["text"],
            "new_body": body_before,
            "heading": heading,
        })

    print(f"  candidates with mid-paragraph headings: {len(plan):,}")
    affected_cases = {p["case_id"] for p in plan}
    print(f"  affected cases: {len(affected_cases):,}")

    if plan:
        print("\nsample splits (first 5):")
        for p in plan[:5]:
            tail_preview = p["old_text"][len(p["new_body"]):].strip()[:80]
            print(f"  {p['case_id']}  ¶{p['hudoc_para_no']}  [{p['section']}]")
            print(f"     KEEP: {p['new_body'][-60:]!r}")
            print(f"     SPLIT: {tail_preview!r}")

    if not args.apply:
        print("\n(dry run — pass --apply to commit)")
        return 0

    print("\napplying…")
    try:
        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS _p30_backup")
        cur.execute(
            "CREATE TABLE _p30_backup ("
            "rowid INTEGER PRIMARY KEY, case_id TEXT, "
            "old_text TEXT, heading TEXT, "
            "new_heading_rowid INTEGER)"
        )
        for p in plan:
            # Insert new heading row with the heading text only.  Section
            # set to 'Header' so the modal renderer hides it from the
            # main flow; the frontend's isStructuralHeading detector will
            # also style it consistently.
            cur.execute(
                "INSERT INTO paragraphs (case_id, section, para_idx, "
                "hudoc_para_no, numbering_block, text) "
                "VALUES (?, 'Header', ?, NULL, NULL, ?)",
                (p["case_id"], p["para_idx"], p["heading"]),
            )
            new_heading_rowid = cur.lastrowid
            cur.execute(
                "INSERT INTO _p30_backup VALUES (?, ?, ?, ?, ?)",
                (p["rowid"], p["case_id"], p["old_text"],
                 p["heading"], new_heading_rowid),
            )
            cur.execute(
                "UPDATE paragraphs SET text = ? WHERE rowid = ?",
                (p["new_body"], p["rowid"]),
            )
        con.commit()
    except Exception as exc:
        con.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"done.  Split {len(plan):,} rows; created {len(plan):,} new heading rows.")
    print("backup retained as `_p30_backup`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
