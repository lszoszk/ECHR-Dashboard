#!/usr/bin/env python3
"""
Correct two section-labelling errors that the Search filters expose.

1. Stray "Operative part" rows inside the reasoning. 21% of judgments have rows labelled "Operative part"
   before "FOR THESE REASONS": headings such as "I. JOINDER OF THE APPLICATIONS", "..." rows inside
   quotations, award lists of the just-satisfaction section, and plain paragraphs. With the Operative
   filter they show up as dispositif; without it they disappear from the reasoning. A stray heading takes
   the section of the next correctly labelled row (it introduces what follows); any other stray row takes
   the section of the previous one.

2. Separate opinions outside "Separate Opinion". In older judgments the opinions that follow the
   dispositif were labelled "Operative part", "Appendix" (hidden by default) or "Just Satisfaction". From
   an opinion heading after the dispositif ("DISSENTING OPINION OF JUDGE ...", "DECLARATION OF JUDGE ...")
   to the end of the document, or to an appendix, rows become "Separate Opinion".

The start of the dispositif is the first row labelled "Operative part" that begins "FOR THESE REASONS" or
"PAR CES MOTIFS" and is not a quotation; a judgment without one is left alone. Only the section changes.
The SQL updates rows by (case_id, para_idx) while the section is still the old one; the rollback restores it.

    python3 scripts/p72_fix_sections.py --db echr.db --sql-out p72.sql --examples 20     # report + SQL
    python3 scripts/p72_fix_sections.py --db echr.db --apply                             # local copy
"""
from __future__ import annotations

import argparse
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

START = re.compile(r"^\s*(FOR THESE REASONS|PAR CES MOTIFS)", re.I)
OPINION = re.compile(
    r"^\s*(?:(?:JOINT|COLLECTIVE|INDIVIDUAL|SEPARATE|PARTLY|PARTIALLY|PARTLY CONCURRING,)\s+)*"
    r"(?:(?:CONCURRING|DISSENTING|SEPARATE|CONCURRING AND PARTLY DISSENTING|PARTLY DISSENTING|PARTLY CONCURRING)\s+)?"
    r"(?:OPINION|DECLARATION)S?\s+OF\s+(?:JUDGES?|MR\.?|MRS\.?|MS\.?|SIR|PRESIDENT|THE PRESIDENT)\b", re.I)
STOP = re.compile(r"^\s*(APPENDIX|ANNEX|LIST OF (THE )?APPLICANTS)\b", re.I)
STRAY = "Operative part"
OP_SECTION = "Separate Opinion"


def stray_operative(rows: list[dict]) -> list[tuple[int, str, str]]:
    """[(row position, old section, new section)] for stray dispositif labels before the dispositif."""
    start = next((i for i, r in enumerate(rows) if r["section"] == STRAY and r["row_role"] != "quote"
                  and START.match(r["text"])), None)
    if start is None:
        return []
    out = []
    for i in range(start):
        r = rows[i]
        if r["section"] != STRAY:
            continue
        nxt = next((rows[j]["section"] for j in range(i + 1, start) if rows[j]["section"] != STRAY), None)
        prv = next((rows[j]["section"] for j in range(i - 1, -1, -1) if rows[j]["section"] != STRAY), None)
        new = (nxt or prv) if (r["row_role"] or "").startswith("heading") else (prv or nxt)
        if new and new != STRAY and new != "Header":
            out.append((i, STRAY, new))
    return out


def opinions_outside(rows: list[dict]) -> list[tuple[int, str, str]]:
    """[(row position, old section, "Separate Opinion")] for opinion text after the dispositif."""
    start = next((i for i, r in enumerate(rows) if r["section"] == STRAY and START.match(r["text"])), None)
    if start is None:
        return []
    first = next((i for i in range(start + 1, len(rows))
                  if len(rows[i]["text"]) < 300 and OPINION.match(rows[i]["text"])
                  and not rows[i]["text"].rstrip().endswith((";", ",")) and rows[i]["row_role"] != "table_cell"), None)
    if first is None:
        return []
    out = []
    for i in range(first, len(rows)):
        r = rows[i]
        if STOP.match(r["text"]) or r["row_role"] == "table_cell":
            break
        if r["section"] != OP_SECTION:
            out.append((i, r["section"], OP_SECTION))
    return out


def quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--sql-out")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--examples", type=int, default=0, help="print N random changes of each kind")
    args = ap.parse_args()
    con = sqlite3.connect(args.db, timeout=600)
    con.row_factory = sqlite3.Row
    by_case: dict[str, list[dict]] = {}
    for r in con.execute("SELECT case_id, para_idx, section, row_role, text FROM paragraphs ORDER BY case_id, para_idx"):
        by_case.setdefault(r["case_id"], []).append({"para_idx": r["para_idx"], "section": r["section"] or "",
                                                     "row_role": r["row_role"] or "", "text": r["text"] or ""})
    # Repeat until nothing changes: a stray row next to another stray row only resolves on the next pass.
    first_old: dict[tuple[str, int], str] = {}
    final: dict[tuple[str, int], str] = {}
    kinds, moved = Counter(), Counter()
    examples: dict[str, list] = {"stray": [], "opinion": []}
    for _ in range(5):
        changed = 0
        for cid, rows in by_case.items():
            done = set()
            for kind, found in (("opinion", opinions_outside(rows)), ("stray", stray_operative(rows))):
                for i, old, new in found:
                    if i in done:
                        continue
                    done.add(i)
                    key = (cid, rows[i]["para_idx"])
                    first_old.setdefault(key, old)
                    if key not in final:
                        kinds[kind] += 1
                        examples[kind].append((cid, rows[i]["row_role"], old, new, rows[i]["text"][:100]))
                    final[key] = new
                    rows[i]["section"] = new
                    changed += 1
        if not changed:
            break
    changes = [(cid, idx, first_old[(cid, idx)], new) for (cid, idx), new in final.items() if first_old[(cid, idx)] != new]
    moved.update((old, new) for _, _, old, new in changes)
    cases = Counter(c for c, *_ in changes)
    print(f"{len(by_case):,} documents; {len(changes):,} rows relabelled in {len(cases):,} documents: {dict(kinds)}")
    print("old -> new:", moved.most_common(10))
    random.seed(1)
    for kind, ex in examples.items():
        for e in random.sample(ex, min(args.examples, len(ex))):
            print(f"  [{kind}] {e[0]} {e[1]:<12} {e[2]} -> {e[3]} | {e[4]!r}")
    forward = [f"UPDATE paragraphs SET section = {quote(new)} WHERE case_id = {quote(cid)} AND para_idx = {idx} "
               f"AND section = {quote(old)};" for cid, idx, old, new in changes]
    backward = [f"UPDATE paragraphs SET section = {quote(old)} WHERE case_id = {quote(cid)} AND para_idx = {idx} "
                f"AND section = {quote(new)};" for cid, idx, old, new in changes]
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
