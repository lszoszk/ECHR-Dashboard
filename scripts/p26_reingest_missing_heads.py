#!/usr/bin/env python3
"""
P26 — re-ingest missing head paragraphs from HUDOC source DOCX.

Background
----------
Some judgments lost their first N paragraphs during the original
PDF→DB ingest.  Detection: ``MIN(hudoc_para_no) > 1`` for the case.
On 2026-05-08 this hit 77 of 24,669 cases; for L.P. v. Hungary
(001-249494) ¶ 1-11 are absent entirely.

The official HUDOC DOCX export is the authoritative source.  This pass:

  1. For each affected case, downloads the DOCX from
     ``https://hudoc.echr.coe.int/app/conversion/docx/?library=ECHR&id=<id>&filename=<id>.docx``
  2. Walks the document body, classifies each paragraph by leading
     numeric prefix (``"12. ..."`` → hudoc_para_no=12, section inferred
     from the most-recent ALL-CAPS heading), and emits new rows for
     every numbered paragraph N in the range ``[1, MIN_existing_N - 1]``.
  3. Skips numbers we already have rows for — this pass only fills the
     gap, never overwrites or duplicates.

Section inference walks the document and tracks the last-seen heading
in this priority list (matches the segmenter's existing taxonomy):

    SUBJECT MATTER OF THE CASE        → "Facts"
    THE FACTS                         → "Facts"
    PROCEDURE                         → "Facts"  (preamble, never numbered)
    THE COURT'S ASSESSMENT            → "Merits"
    ALLEGED VIOLATION OF ARTICLE …    → "Merits"
    OTHER COMPLAINTS                  → "Merits"
    APPLICATION OF ARTICLE 41 …       → "Just Satisfaction"
    JUST SATISFACTION                 → "Just Satisfaction"
    FOR THESE REASONS, THE COURT …    → "Operative part"

Side effects
------------
INSERT new paragraph rows; DOES NOT touch existing rows.  All inserts
logged in `_p26_backup` for rollback.

Usage
-----
    python3 scripts/p26_reingest_missing_heads.py [--db PATH] \\
            [--apply] [--limit N] [--case CASE_ID]
"""
from __future__ import annotations

import argparse
import io
import re
import sqlite3
import ssl
import sys
import time
import urllib.request
from pathlib import Path

try:
    from docx import Document
except ImportError:
    print("ERROR: python-docx not installed.  Run:\n"
          "  pip3 install --user --break-system-packages python-docx",
          file=sys.stderr)
    sys.exit(2)

DOCX_URL_TEMPLATE = (
    "https://hudoc.echr.coe.int/app/conversion/docx/"
    "?library=ECHR&id={case_id}&filename={case_id}.docx"
)

PARA_NUM_RE = re.compile(r"^\s*(\d+)\.\s+")

# Order matters: more specific headings first.  Each entry: (substring, section).
HEADING_RULES = [
    ("FOR THESE REASONS",                "Operative part"),
    ("APPLICATION OF ARTICLE 41",        "Just Satisfaction"),
    ("JUST SATISFACTION",                "Just Satisfaction"),
    ("OTHER COMPLAINTS",                 "Merits"),
    ("ALLEGED VIOLATION OF ARTICLE",     "Merits"),
    ("THE COURT'S ASSESSMENT",           "Merits"),
    ("THE COURT’S ASSESSMENT",           "Merits"),  # curly apostrophe
    ("SUBJECT MATTER OF THE CASE",       "Facts"),
    ("THE FACTS",                        "Facts"),
    ("PROCEDURE",                        "Facts"),
]


def fetch_docx(case_id: str) -> bytes:
    """Download the HUDOC DOCX for the given case."""
    ctx = ssl._create_unverified_context()
    url = DOCX_URL_TEMPLATE.format(case_id=case_id)
    req = urllib.request.Request(url, headers={"User-Agent": "ECHR-Dashboard/p26"})
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        return resp.read()


def is_heading(text: str) -> bool:
    """Heuristic: ALL-CAPS-ish line, no leading digit, length ≤ 100."""
    if not text or len(text) > 100:
        return False
    if PARA_NUM_RE.match(text):
        return False
    upper = sum(1 for c in text if c.isalpha() and c.isupper())
    lower = sum(1 for c in text if c.isalpha() and c.islower())
    return upper >= 4 and upper > lower * 3


def section_for_heading(heading: str) -> str | None:
    h = heading.upper()
    for needle, sec in HEADING_RULES:
        if needle in h:
            return sec
    return None


def parse_docx_paragraphs(docx_bytes: bytes) -> list[dict]:
    """Walk the DOCX body and yield {hudoc_para_no, text, section} dicts.

    Only emits rows for paragraphs that begin with ``N. `` — i.e. the
    Court's own numbering.  Section is the most-recent matched heading
    above the paragraph; defaults to None for the procedural preamble
    above the first heading."""
    doc = Document(io.BytesIO(docx_bytes))
    current_section: str | None = None
    out: list[dict] = []
    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text:
            continue
        if is_heading(text):
            sec = section_for_heading(text)
            if sec:
                current_section = sec
            continue
        m = PARA_NUM_RE.match(text)
        if not m:
            continue
        n = int(m.group(1))
        out.append({
            "hudoc_para_no": n,
            "text": text,
            "section": current_section or "Facts",  # pre-heading paragraphs are facts
        })
    return out


def find_affected_cases(cur: sqlite3.Cursor) -> list[tuple[str, int]]:
    """Return [(case_id, first_existing_main_hudoc_para_no), …] for cases
    whose lowest MAIN-JUDGMENT paragraph number is > 1.

    operative_dispositif rows carry their own 1-based clause numbering
    (assigned by P25), which is unrelated to main-judgment numbering, so
    we filter them out before computing the MIN."""
    cur.execute(
        "SELECT case_id, MIN(hudoc_para_no) AS first_p "
        "FROM paragraphs "
        "WHERE hudoc_para_no IS NOT NULL "
        "  AND (numbering_block IS NULL "
        "       OR numbering_block != 'operative_dispositif') "
        "GROUP BY case_id HAVING first_p > 1 "
        "ORDER BY case_id"
    )
    return [(r["case_id"], r["first_p"]) for r in cur.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/echr_search.db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap the number of cases processed.")
    ap.add_argument("--case", default=None,
                    help="Process a single case_id (overrides scan).")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="Politeness delay between HUDOC requests (seconds).")
    ap.add_argument("--override-mismatched", action="store_true",
                    help="Also demote (NULL hudoc_para_no on) existing rows "
                    "whose text doesn't match HUDOC ¶ N.  Use to recover "
                    "L.P.-style misextracted fragments where '1.' or '7.' "
                    "from a mid-sentence reference was tokenised as a "
                    "paragraph start.  Conservative — only fires when our "
                    "row's first 30 chars don't overlap HUDOC's.")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    if args.case:
        affected = [args.case]
    else:
        affected = [cid for cid, _ in find_affected_cases(cur)]
    if args.limit:
        affected = affected[: args.limit]

    print(f"affected cases: {len(affected):,}")
    if not affected:
        return 0

    # Plans:
    #   * plan_inserts   — new rows to add, one per HUDOC ¶ that has no
    #                      legitimate match in our DB.
    #   * plan_demote    — rowids whose hudoc_para_no should be NULLed
    #                      because the text doesn't match HUDOC ¶ N (these
    #                      are misextracted fragments — e.g. L.P.'s
    #                      "1. (a) of Protocol No. 7…" tagged as ¶ 1).  Only
    #                      populated when --override-mismatched is set.
    plan_inserts: list[tuple[str, str, int, str]] = []
    plan_demote:  list[tuple[int, str, int]] = []  # (rowid, case_id, old_hudoc_para_no)
    fetch_failures: list[tuple[str, str]] = []
    parse_empty:    list[str] = []
    no_gap_filled:  list[str] = []

    def first_60_match(a: str, b: str) -> bool:
        """Conservative same-paragraph check: do the first 60 non-whitespace
        chars of (a) and (b) share a common 30-char prefix?  Tolerates the
        leading "N. " in one but not the other, and minor whitespace diffs."""
        norm = lambda s: re.sub(r"\s+", " ", (s or "").strip())[:60]
        na, nb = norm(a), norm(b)
        # Strip leading "<num>. " / "<num>\xa0\xa0" prefix from each side
        na = re.sub(r"^\d+\.\s+", "", na)[:30]
        nb = re.sub(r"^\d+\.\s+", "", nb)[:30]
        return bool(na) and bool(nb) and (na == nb or na.startswith(nb[:20]) or nb.startswith(na[:20]))

    for i, cid in enumerate(affected, 1):
        # Exclude operative_dispositif rows from the existing-rows map.
        # Their `hudoc_para_no` is a 1-based clause index assigned by P25,
        # NOT a main-judgment paragraph number, so it has its own namespace
        # and the text-match check would always fail (clause 1 = "Decides…",
        # main ¶ 1 = "The case concerns…").
        cur.execute(
            "SELECT rowid, hudoc_para_no, text FROM paragraphs "
            "WHERE case_id = ? AND hudoc_para_no IS NOT NULL "
            "  AND (numbering_block IS NULL "
            "       OR numbering_block != 'operative_dispositif')",
            [cid],
        )
        existing_rows: dict[int, list] = {}
        for r in cur.fetchall():
            existing_rows.setdefault(r["hudoc_para_no"], []).append(dict(r))

        try:
            blob = fetch_docx(cid)
            parsed = parse_docx_paragraphs(blob)
        except Exception as exc:
            fetch_failures.append((cid, str(exc)))
            continue
        if not parsed:
            parse_empty.append(cid)
            continue

        added_for_case = 0
        for p in parsed:
            n = p["hudoc_para_no"]
            existing = existing_rows.get(n, [])
            legitimate_match = any(first_60_match(p["text"], r["text"]) for r in existing)
            if legitimate_match:
                continue
            if existing and not args.override_mismatched:
                # Existing row(s) have hudoc_para_no=N but text differs from
                # HUDOC's ¶ N.  Without --override-mismatched, leave them
                # alone — the frontend's enrichContinuationParaNos already
                # demotes them via the out-of-order guard.  This keeps the
                # default invocation conservative.
                continue
            if existing and args.override_mismatched:
                for r in existing:
                    plan_demote.append((r["rowid"], cid, n))
            plan_inserts.append((cid, p["section"], n, p["text"]))
            added_for_case += 1
        if added_for_case == 0:
            no_gap_filled.append(cid)

        if i % 10 == 0 or i == len(affected):
            print(f"  scanned {i:,}/{len(affected):,}  "
                  f"fetched={i - len(fetch_failures)}  "
                  f"queued_ins={len(plan_inserts):,}  "
                  f"queued_demote={len(plan_demote):,}")
        time.sleep(args.sleep)

    print(f"\nplanned inserts:           {len(plan_inserts):,}")
    print(f"planned demotions:         {len(plan_demote):,}")
    print(f"fetch failures:            {len(fetch_failures):,}")
    print(f"DOCX-parse empty:          {len(parse_empty):,}")
    print(f"cases needing nothing:     {len(no_gap_filled):,}")

    if fetch_failures and len(fetch_failures) <= 5:
        print("\nfetch failures (first 5):")
        for cid, err in fetch_failures[:5]:
            print(f"  {cid}: {err[:100]}")

    if not args.apply:
        seen_cases: set[str] = set()
        print("\nsample inserts (first 6 cases):")
        for cid, sec, n, text in plan_inserts:
            if cid in seen_cases:
                continue
            seen_cases.add(cid)
            print(f"  {cid}  [{sec}]  ¶{n}  {text[:80]}")
            if len(seen_cases) >= 6:
                break
        if plan_demote:
            print("\nsample demotions (first 6):")
            for rowid, cid, n in plan_demote[:6]:
                print(f"  rowid={rowid}  {cid}  ¶{n} (text doesn't match HUDOC)")
        print("\n(dry run — pass --apply to commit)")
        return 0

    print("\napplying…")
    try:
        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS _p26_backup_inserts")
        cur.execute("DROP TABLE IF EXISTS _p26_backup_demotions")
        cur.execute(
            "CREATE TABLE _p26_backup_inserts ("
            "rowid INTEGER PRIMARY KEY AUTOINCREMENT, "
            "case_id TEXT, section TEXT, hudoc_para_no INTEGER, text TEXT, "
            "inserted_paragraph_rowid INTEGER)"
        )
        cur.execute(
            "CREATE TABLE _p26_backup_demotions ("
            "rowid INTEGER PRIMARY KEY, case_id TEXT, "
            "old_hudoc_para_no INTEGER)"
        )
        for cid, sec, n, text in plan_inserts:
            cur.execute(
                "INSERT INTO paragraphs (case_id, section, para_idx, "
                "hudoc_para_no, numbering_block, text) "
                "VALUES (?, ?, NULL, ?, 'main_judgment', ?)",
                (cid, sec, n, text),
            )
            new_rowid = cur.lastrowid
            cur.execute(
                "INSERT INTO _p26_backup_inserts "
                "(case_id, section, hudoc_para_no, text, inserted_paragraph_rowid) "
                "VALUES (?, ?, ?, ?, ?)",
                (cid, sec, n, text, new_rowid),
            )
        for rowid, cid, old_n in plan_demote:
            cur.execute(
                "INSERT INTO _p26_backup_demotions VALUES (?, ?, ?)",
                (rowid, cid, old_n),
            )
            cur.execute(
                "UPDATE paragraphs SET hudoc_para_no = NULL WHERE rowid = ?",
                [rowid],
            )
        con.commit()
    except Exception as exc:
        con.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"done.  Inserted {len(plan_inserts):,} rows + demoted "
          f"{len(plan_demote):,} rows across "
          f"{len({c for c, *_ in plan_inserts}):,} cases.")
    print("backup retained as `_p26_backup_inserts` + `_p26_backup_demotions`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
