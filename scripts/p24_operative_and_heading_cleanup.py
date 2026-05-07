#!/usr/bin/env python3
"""
P24 — Operative-part precision + ALL-CAPS heading promotion.

Three correlated bugs surface in committee judgments:

(a) Sign-off block tagged as Op. ¶ 77.  L.P. v. Hungary's row "§§ 2 and 3
    of the Rules of Court. Sophie Piquet  María Elósegui  Acting Deputy
    Registrar  President" carries `numbering_block='operative_dispositif'`
    and `hudoc_para_no=77` because the segmenter saw "Rule 77 §§ 2 and 3"
    inside the closing block and tokenised "77." as a paragraph start.
    Demote: section → Header, numbering_block → NULL, hudoc_para_no →
    NULL.

(b) Dispositif clauses (Decides / Declares / Holds / Dismisses / Notes)
    that lack `numbering_block='operative_dispositif'` because they were
    inserted by an early ingest before P12 ran.  Promote.

(c) Pop C structural headings ("OTHER COMPLAINTS", "APPLICATION OF
    ARTICLE 41 OF THE CONVENTION", "JUST SATISFACTION", "MERITS",
    "SUBJECT MATTER OF THE CASE") that ride along inside a paragraph
    text instead of being broken out.  Promote to a standalone Header
    row.  (This pass detects the simpler case where the heading IS the
    full text of a row but section is wrong; mid-paragraph heading
    extraction is left for a future text-mutating pass.)

Usage
-----
    python3 scripts/p24_operative_and_heading_cleanup.py [--db PATH] [--apply]

Idempotent.  Backups: `_p24_backup_a`, `_p24_backup_b`, `_p24_backup_c`.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

# (a) signing block — must include a registrar/president title so we don't
# false-positive on dispositive clauses that mention Rule 77.
SIGNING_BLOCK_RE = re.compile(
    r"(Acting\s+)?(Deputy\s+)?(Section\s+)?Registrar.*?President", re.IGNORECASE | re.DOTALL,
)

# (b) dispositif clause leaders.  We require them to start the row.
DISPOSITIF_LEADER_RE = re.compile(
    r"^\s*(Decides|Declares|Dismisses|Holds|Notes|Joins|Strikes)\b",
    re.IGNORECASE,
)

# (c) Pop C heading texts.  Conservative whitelist — these are unambiguous
# section titles.  Anything else is left alone for a future pass.
POP_C_HEADINGS = {
    "OTHER COMPLAINTS",
    "APPLICATION OF ARTICLE 41 OF THE CONVENTION",
    "JUST SATISFACTION",
    "MERITS",
    "SUBJECT MATTER OF THE CASE",
    "FACTS",
    "THE FACTS",
    "RELEVANT LEGAL FRAMEWORK",
    "ALLEGED VIOLATION OF ARTICLE 8 OF THE CONVENTION",
    "ALLEGED VIOLATION OF ARTICLE 6 OF THE CONVENTION",
    "ALLEGED VIOLATION OF ARTICLE 3 OF THE CONVENTION",
    "ALLEGED VIOLATION OF ARTICLE 5 OF THE CONVENTION",
    "ALLEGED VIOLATION OF ARTICLE 10 OF THE CONVENTION",
    "ALLEGED VIOLATION OF ARTICLE 11 OF THE CONVENTION",
    "ALLEGED VIOLATION OF ARTICLE 14 OF THE CONVENTION",
    "ALLEGED VIOLATION OF ARTICLE 1 OF PROTOCOL NO. 1",
    "FOR THESE REASONS, THE COURT, UNANIMOUSLY,",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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

    cols = {r[1] for r in cur.execute("PRAGMA table_info(paragraphs)").fetchall()}
    has_hudoc = "hudoc_para_no" in cols
    has_block = "numbering_block" in cols

    # ---------- (a) signing block demotion -----------------------------
    print("(a) signing-block demotion — rows with Registrar+President text")
    if not (has_hudoc and has_block):
        print("    SKIPPED — needs hudoc_para_no + numbering_block columns.")
        candidates_a: list[dict] = []
    else:
        cur.execute(
            "SELECT rowid, case_id, section, numbering_block, hudoc_para_no, text "
            "FROM paragraphs "
            "WHERE numbering_block = 'operative_dispositif' "
            "  AND text LIKE '%Registrar%President%'"
        )
        candidates_a = [dict(r) for r in cur.fetchall()
                        if SIGNING_BLOCK_RE.search(r["text"] or "")]
        print(f"    matches: {len(candidates_a):,}")

    # ---------- (b) dispositif leader promotion ------------------------
    print("(b) Decides/Declares/Holds rows missing operative_dispositif tag")
    if not has_block:
        print("    SKIPPED — needs numbering_block column.")
        candidates_b: list[dict] = []
    else:
        cur.execute(
            "SELECT rowid, case_id, section, numbering_block, text "
            "FROM paragraphs "
            "WHERE section IN ('Operative Part', 'Operative part') "
            "  AND (numbering_block IS NULL OR numbering_block != 'operative_dispositif')"
        )
        candidates_b = [dict(r) for r in cur.fetchall()
                        if DISPOSITIF_LEADER_RE.match(r["text"] or "")]
        print(f"    matches: {len(candidates_b):,}")

    # ---------- (c) heading promotion ---------------------------------
    print("(c) Pop C headings stuck in non-Header sections")
    cur.execute(
        "SELECT rowid, case_id, section, text "
        "FROM paragraphs "
        "WHERE length(text) <= 80 AND section != 'Header'"
    )
    candidates_c: list[dict] = []
    for r in cur.fetchall():
        if (r["text"] or "").strip().rstrip(".") in {h.rstrip(".") for h in POP_C_HEADINGS}:
            candidates_c.append(dict(r))
    print(f"    matches: {len(candidates_c):,}")

    if not args.apply:
        if candidates_c[:3]:
            print("\n    sample heading rows:")
            for r in candidates_c[:5]:
                print(f"      {r['case_id']} [{r['section']}] {r['text']!r}")
        print("\n(dry run — pass --apply to commit)")
        return 0

    # ---------- apply --------------------------------------------------
    print("\napplying…")
    try:
        cur.execute("BEGIN")
        # backups
        cur.execute("DROP TABLE IF EXISTS _p24_backup_a")
        cur.execute("DROP TABLE IF EXISTS _p24_backup_b")
        cur.execute("DROP TABLE IF EXISTS _p24_backup_c")
        cur.execute(
            "CREATE TABLE _p24_backup_a ("
            "rowid INTEGER PRIMARY KEY, case_id TEXT, "
            "old_section TEXT, old_numbering_block TEXT, old_hudoc_para_no INTEGER)"
        )
        cur.execute(
            "CREATE TABLE _p24_backup_b ("
            "rowid INTEGER PRIMARY KEY, case_id TEXT, "
            "old_numbering_block TEXT)"
        )
        cur.execute(
            "CREATE TABLE _p24_backup_c ("
            "rowid INTEGER PRIMARY KEY, case_id TEXT, "
            "old_section TEXT)"
        )
        for r in candidates_a:
            cur.execute(
                "INSERT INTO _p24_backup_a VALUES (?,?,?,?,?)",
                (r["rowid"], r["case_id"], r["section"],
                 r["numbering_block"], r["hudoc_para_no"]),
            )
            cur.execute(
                "UPDATE paragraphs SET section='Header', "
                "numbering_block=NULL, hudoc_para_no=NULL "
                "WHERE rowid=?", (r["rowid"],),
            )
        for r in candidates_b:
            cur.execute(
                "INSERT INTO _p24_backup_b VALUES (?,?,?)",
                (r["rowid"], r["case_id"], r["numbering_block"]),
            )
            cur.execute(
                "UPDATE paragraphs SET numbering_block='operative_dispositif' "
                "WHERE rowid=?", (r["rowid"],),
            )
        for r in candidates_c:
            cur.execute(
                "INSERT INTO _p24_backup_c VALUES (?,?,?)",
                (r["rowid"], r["case_id"], r["section"]),
            )
            cur.execute(
                "UPDATE paragraphs SET section='Header' WHERE rowid=?",
                (r["rowid"],),
            )
        con.commit()
    except Exception as exc:
        con.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"done.  Updated rows: a={len(candidates_a)}  "
          f"b={len(candidates_b)}  c={len(candidates_c)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
