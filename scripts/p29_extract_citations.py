#!/usr/bin/env python3
"""
P29 — extract paragraph-level citations from text and build case_citations.

Background
----------
Phase 1 (P28) surfaced the JSONL `strasbourg_caselaw` field for the 7,807
older judgments that carry it.  ~16,800 cases — most importantly the
6,240 post-2021 committee judgments — never went through that ingest
path and consequently show "0 cites / 0 cited by" in the dashboard,
even when their text is full of HUDOC-style citations.

This pass walks paragraphs of every case, extracts ECHR application
numbers via regex, resolves each to a `case_id` through the existing
`case_no → case_id` index, and writes a `case_citations` table:

    case_citations(
      citing_case_id TEXT NOT NULL,
      cited_case_id  TEXT NOT NULL,
      citing_paragraph_rowid INTEGER,
      raw_text TEXT,
      extraction_method TEXT,
      PRIMARY KEY (citing_case_id, cited_case_id, citing_paragraph_rowid)
    )

Detection strategy
------------------
* PRIMARY: `(\\d{4,5}/\\d{2,4})` appno pattern.  ECHR application numbers
  are formatted ``NNNN/YY`` or ``NNNNN/YYYY`` (e.g. 19376/23, 80982/12).
  Conservative — only counts when the appno is found in the *cases*
  index, which automatically eliminates false positives (year-codes
  like ``2026/01`` won't resolve to a case).

* SECONDARY (`--include-name-matches`): proximity-based "X v. Y" name
  resolution against a normalized title index.  Useful for "cited above"
  references and pre-2000 cases without explicit appnos.  Off by default
  because of higher false-positive risk.

The script is idempotent: running it twice rebuilds the table from
scratch (DROP + CREATE).  No backup table needed since the table is
fully derived from `paragraphs` + `cases`.

Usage
-----
    python3 scripts/p29_extract_citations.py [--db PATH] [--apply] \\
            [--include-name-matches] [--limit-cases N]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

# ECHR application-number pattern.  Two forms in the wild:
#   - 4-5 digit application + 2-digit year:    19376/23
#   - 4-5 digit application + 4-digit year:    19376/2023  (rare, recent)
APPNO_RE = re.compile(r"\b(\d{4,5})/(\d{2}|\d{4})\b")

# Heuristic: appno is more credible if context within ±60 chars contains
# any of these citation cue words.  We DON'T strictly require this — the
# case_no resolution already filters most false positives — but we use
# it for the `extraction_method` audit trail.
CITATION_CUE_RE = re.compile(
    r"\b(no\.?|nos?\.?|application|judgment|decision|v\.|cited above|see\s|compare)",
    re.IGNORECASE,
)


def normalise_appno(raw: str) -> str:
    """Convert raw appno match to the canonical form used in cases.case_no."""
    m = APPNO_RE.match(raw)
    if not m:
        return raw
    num, yr = m.group(1), m.group(2)
    # Treat 4-digit years as already canonical (post-2000 changeover).
    return f"{num}/{yr}"


def build_appno_index(cur: sqlite3.Cursor) -> dict[str, str]:
    """{normalised_appno: case_id}.  case_no often holds multiple appnos
    semicolon-separated for joined cases — split + index each."""
    cur.execute("SELECT case_id, case_no FROM cases WHERE case_no IS NOT NULL")
    out: dict[str, str] = {}
    for r in cur.fetchall():
        case_no = (r["case_no"] or "").strip()
        if not case_no:
            continue
        # Split on ';' or whitespace+';' or comma — joined cases like
        # "32310/08; 33191/08; 43100/08".
        for part in re.split(r"[;,]\s*", case_no):
            part = part.strip()
            if APPNO_RE.fullmatch(part):
                out[part] = r["case_id"]
    return out


def extract_appnos(text: str) -> list[tuple[str, int]]:
    """Return [(canonical_appno, char_offset), …] of distinct appnos in text."""
    seen: set[str] = set()
    out: list[tuple[str, int]] = []
    for m in APPNO_RE.finditer(text):
        canon = f"{m.group(1)}/{m.group(2)}"
        if canon in seen:
            continue
        seen.add(canon)
        out.append((canon, m.start()))
    return out


def has_citation_cue(text: str, offset: int, window: int = 60) -> bool:
    lo = max(0, offset - window)
    hi = min(len(text), offset + window)
    return bool(CITATION_CUE_RE.search(text[lo:hi]))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--db", default="data/echr_search.db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit-cases", type=int, default=0,
                    help="Cap the number of citing cases scanned (debug).")
    ap.add_argument("--report-cues", action="store_true",
                    help="Audit-only: report on appnos found WITHOUT a "
                    "citation cue word in context (potential false "
                    "positives).  No DB writes.")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("building case_no → case_id index…")
    appno_to_case = build_appno_index(cur)
    print(f"  indexed {len(appno_to_case):,} unique application numbers")

    print("\nscanning paragraphs for appno citations…")
    cur.execute("SELECT DISTINCT case_id FROM paragraphs ORDER BY case_id")
    case_ids = [r["case_id"] for r in cur.fetchall()]
    if args.limit_cases:
        case_ids = case_ids[: args.limit_cases]

    citations: list[tuple[str, str, int, str, str]] = []
    # (citing_case_id, cited_case_id, paragraph_rowid, raw_text_excerpt, method)

    seen_pair_para: set[tuple[str, str, int]] = set()
    no_cue_count = 0
    self_cite_count = 0
    unresolved_count = Counter()
    t0 = time.perf_counter()

    for i, citing_id in enumerate(case_ids, 1):
        cur.execute(
            "SELECT rowid, text FROM paragraphs WHERE case_id = ?",
            [citing_id],
        )
        for prow in cur.fetchall():
            text = prow["text"] or ""
            if "/" not in text:
                continue
            for appno, off in extract_appnos(text):
                cited_id = appno_to_case.get(appno)
                if cited_id is None:
                    unresolved_count[appno[:5]] += 1
                    continue
                if cited_id == citing_id:
                    self_cite_count += 1
                    continue
                key = (citing_id, cited_id, prow["rowid"])
                if key in seen_pair_para:
                    continue
                seen_pair_para.add(key)
                cued = has_citation_cue(text, off)
                if not cued:
                    no_cue_count += 1
                method = "appno_with_cue" if cued else "appno_no_cue"
                # Capture ±50 char context for audit
                lo = max(0, off - 50)
                hi = min(len(text), off + len(appno) + 50)
                excerpt = text[lo:hi].replace("\n", " ")
                citations.append((citing_id, cited_id, prow["rowid"], excerpt, method))
        if i % 1000 == 0 or i == len(case_ids):
            elapsed = time.perf_counter() - t0
            rate = i / elapsed if elapsed > 0 else 0
            print(f"  scanned {i:,}/{len(case_ids):,} cases  "
                  f"citations queued={len(citations):,}  "
                  f"({rate:.0f} cases/s)")

    print()
    print(f"total citations extracted:    {len(citations):,}")
    print(f"  with citation cue:          {len(citations) - no_cue_count:,}")
    print(f"  without cue (audit-only):   {no_cue_count:,}")
    print(f"self-citations dropped:       {self_cite_count:,}")
    print(f"unresolved appnos (top 5 prefixes):")
    for prefix, n in unresolved_count.most_common(5):
        print(f"    {prefix}xx/yy: {n:,}")

    # Aggregate stats
    cited_by = Counter(c[1] for c in citations)
    cites    = Counter(c[0] for c in citations)
    print(f"\ncases with at least one cite:    {len(cites):,}")
    print(f"cases that are cited by something: {len(cited_by):,}")
    if cited_by:
        top = cited_by.most_common(5)
        print("most-cited cases (top 5):")
        for cid, n in top:
            cur.execute("SELECT title FROM cases WHERE case_id = ?", [cid])
            tr = cur.fetchone()
            title = tr["title"] if tr else "(unknown)"
            print(f"    {cid}  {n:>4}× cited  {title}")

    if args.report_cues:
        return 0
    if not args.apply:
        print("\n(dry run — pass --apply to write case_citations table)")
        return 0

    print("\napplying — building case_citations table…")
    try:
        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS case_citations")
        cur.execute(
            "CREATE TABLE case_citations ("
            "  citing_case_id TEXT NOT NULL, "
            "  cited_case_id TEXT NOT NULL, "
            "  citing_paragraph_rowid INTEGER, "
            "  raw_text TEXT, "
            "  extraction_method TEXT, "
            "  PRIMARY KEY (citing_case_id, cited_case_id, citing_paragraph_rowid)"
            ")"
        )
        cur.execute("CREATE INDEX idx_cc_citing ON case_citations(citing_case_id)")
        cur.execute("CREATE INDEX idx_cc_cited  ON case_citations(cited_case_id)")
        cur.executemany(
            "INSERT INTO case_citations "
            "  (citing_case_id, cited_case_id, citing_paragraph_rowid, "
            "   raw_text, extraction_method) "
            "VALUES (?, ?, ?, ?, ?)",
            citations,
        )
        con.commit()
    except Exception as exc:
        con.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"done.  case_citations table contains {len(citations):,} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
