#!/usr/bin/env python3
"""
Give unnumbered rows the paragraph number HUDOC shows for them.

Between two numbered paragraphs a and b (b - a between 2 and 6) the missing numbers usually are not lost
text: the paragraph is stored, but without its number, because the number sat behind a hidden HUDOC marker
("ITMarkFactsComplaintsStart 6. The applicant ..."), the row was taken for a heading or a quotation, or
Word's automatic numbering was not in the text. 78% of such gaps are gaps in HUDOC's own page as well;
those are left alone.

For each missing number g, among the unnumbered rows between a and b:
  1. a row whose text (after removing the marker) starts "g." gets the number;
  2. otherwise the text of paragraph g on HUDOC's page (local cache of the HTML view) is matched to a row,
     and the row gets the number, with "g." put in front of its text as HUDOC shows it.
A second kind: "half-numbered" rows (7,118 in 675 judgments) carry hudoc_para_no but no numbering_block and
no "n." in their text, so the case view shows them unnumbered among numbered neighbours. Where HUDOC's
page confirms that paragraph n is this text, the row gets numbering_block "main_judgment" (or
"separate_opinion" inside an opinion) and "n." in front of its text.

The row becomes a numbered paragraph of the main judgment (hudoc_para_no, display_para_no, numbering_block
"main_judgment", row_role "paragraph"); the marker is removed from the text and text_hash recomputed.
The SQL changes a row by (case_id, para_idx) only while it is still unnumbered with the old text; the
rollback restores it.

    python3 scripts/p73_fill_paragraph_numbers.py --db echr.db --html-dir ~/Desktop/HUDOC-Html --sql-out p73.sql
"""
from __future__ import annotations

import argparse
import html as htmlmod
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MARKER = re.compile(r"^\s*ITMark\w+\s*")
NBSP2 = "  "


def squash(s: str) -> str:
    return re.sub(r"[\W_]+", "", s or "").lower()


def strip_number(text: str) -> str:
    return re.sub(r"^\s*\d+\s*\.\s*", "", MARKER.sub("", text or ""))


def html_paragraphs(path: Path) -> dict[int, str]:
    """Paragraph number -> its text (without the number), from HUDOC's HTML view."""
    raw = path.read_text(encoding="utf8", errors="ignore")
    out: dict[int, str] = {}
    for block in re.findall(r"<p\b[^>]*>(.*?)</p>", raw, flags=re.S | re.I):
        text = htmlmod.unescape(re.sub(r"<[^>]+>", "", block))
        text = MARKER.sub("", text.replace(" ", " ")).strip()
        m = re.match(r"^(\d{1,4})\.\s+(.*)", text, flags=re.S)
        if m:
            out.setdefault(int(m.group(1)), m.group(2))
    return out


def plan_case(rows: list[dict], page: dict[int, str] | None) -> list[tuple[dict, int, str, str]]:
    """[(row, number, method, new text)] for the unnumbered rows that are missing paragraphs."""
    numbered = [(i, r["hudoc_para_no"]) for i, r in enumerate(rows)
                if r["hudoc_para_no"] is not None and r["numbering_block"] == "main_judgment"
                and r["section"] != "Separate Opinion"]
    out, used = [], set()
    for (i, a), (j, b) in zip(numbered, numbered[1:]):
        if not 2 <= b - a <= 6:
            continue
        between = [k for k in range(i + 1, j) if rows[k]["hudoc_para_no"] is None and k not in used]
        for g in range(a + 1, b):
            want = squash(page[g])[:60] if page and g in page else None

            def is_g(k):
                # "g." at the start; where HUDOC's page is available the text must also be paragraph g's,
                # so that a numbered item of a quoted report cannot take the judgment's number
                if not re.match(rf"^\s*{g}\s*\.\s", MARKER.sub("", rows[k]["text"] or "")):
                    return False
                if want:
                    return squash(strip_number(rows[k]["text"])).startswith(want[:40])
                return page is None and rows[k]["row_role"] != "quote"
            k = next((k for k in between if k not in used and is_g(k)), None)
            if k is not None:
                used.add(k)
                out.append((rows[k], g, "number in the text", MARKER.sub("", rows[k]["text"]).lstrip()))
                continue
            if not want or len(want) < 30:
                continue
            k = next((k for k in between if k not in used and squash(strip_number(rows[k]["text"])).startswith(want)), None)
            if k is not None:
                used.add(k)
                out.append((rows[k], g, "matched to HUDOC's page", f"{g}.{NBSP2}{strip_number(rows[k]['text']).lstrip()}"))
    return out


def half_numbered(rows: list[dict], page: dict[int, str] | None) -> list[tuple[dict, int, str, str]]:
    """[(row, number, method, new text)] for rows with a number but no block and no "n." in the text."""
    out = []
    if not page:
        return out
    for r in rows:
        n = r["hudoc_para_no"]
        if n is None or r["numbering_block"] is not None or n not in page:
            continue
        if re.match(rf"^\s*{n}\s*\.", MARKER.sub("", r["text"] or "")):
            continue
        want = squash(page[n])[:40]
        if len(want) < 20 or not squash(strip_number(r["text"])).startswith(want):
            continue
        out.append((r, n, "half-numbered", f"{n}.{NBSP2}{strip_number(r['text']).lstrip()}"))
    return out


def quote(s) -> str:
    return "NULL" if s is None else "'" + str(s).replace("'", "''") + "'"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--html-dir", default=str(Path.home() / "Desktop/HUDOC-Html"))
    ap.add_argument("--sql-out")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--examples", type=int, default=0)
    args = ap.parse_args()
    import p38_batch_enrich as p38
    con = sqlite3.connect(args.db, timeout=600)
    con.row_factory = sqlite3.Row
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in con.execute("SELECT case_id, para_idx, section, row_role, hudoc_para_no, numbering_block, text "
                         "FROM paragraphs ORDER BY case_id, para_idx"):
        by_case[r["case_id"]].append(dict(r))
    # Repeat until nothing changes: a row numbered in one pass can open a gap window for the next.
    first: dict[tuple[str, int], dict] = {}
    final: dict[tuple[str, int], tuple] = {}
    for _ in range(5):
        found = 0
        for cid, rows in by_case.items():
            page_path = Path(args.html_dir) / f"{cid}.html"
            page = html_paragraphs(page_path) if page_path.exists() else None
            for row, g, method, new_text in plan_case(rows, page) + half_numbered(rows, page):
                key = (cid, row["para_idx"])
                first.setdefault(key, dict(row))
                final[key] = (g, method if key not in final else final[key][1], new_text)
                row["hudoc_para_no"], row["text"] = g, new_text
                row["numbering_block"] = "separate_opinion" if row["section"] == "Separate Opinion" else "main_judgment"
                found += 1
        if not found:
            break
    changes, methods = [], Counter()
    for (cid, idx), (g, method, new_text) in final.items():
        changes.append((cid, first[(cid, idx)], g, method, new_text))
        methods[method] += 1
    print(f"{len(by_case):,} documents; {len(changes):,} rows get their paragraph number in "
          f"{len({c[0] for c in changes}):,} documents: {dict(methods)}")
    for cid, row, g, method, new in changes[:: max(1, len(changes) // max(1, args.examples))][: args.examples]:
        print(f"  {cid} § {g} ({method}, was {row['row_role']}): {row['text'][:70]!r} -> {new[:70]!r}")
    forward, backward = [], []
    for cid, row, g, method, new in changes:
        old = row["text"]
        if method == "half-numbered":
            block = "separate_opinion" if row["section"] == "Separate Opinion" else "main_judgment"
            forward.append(
                f"UPDATE paragraphs SET numbering_block = '{block}', text = {quote(new)}, text_hash = {quote(p38.hash_text(new))} "
                f"WHERE case_id = {quote(cid)} AND para_idx = {row['para_idx']} AND hudoc_para_no = {g} "
                f"AND numbering_block IS NULL AND text = {quote(old)};")
            backward.append(
                f"UPDATE paragraphs SET numbering_block = NULL, text = {quote(old)}, text_hash = {quote(p38.hash_text(old))} "
                f"WHERE case_id = {quote(cid)} AND para_idx = {row['para_idx']} AND hudoc_para_no = {g} AND text = {quote(new)};")
            continue
        forward.append(
            f"UPDATE paragraphs SET hudoc_para_no = {g}, display_para_no = {g}, numbering_block = 'main_judgment', "
            f"row_role = 'paragraph', text = {quote(new)}, text_hash = {quote(p38.hash_text(new))} "
            f"WHERE case_id = {quote(cid)} AND para_idx = {row['para_idx']} AND hudoc_para_no IS NULL AND text = {quote(old)};")
        backward.append(
            f"UPDATE paragraphs SET hudoc_para_no = NULL, display_para_no = NULL, numbering_block = {quote(row['numbering_block'])}, "
            f"row_role = {quote(row['row_role'])}, text = {quote(old)}, text_hash = {quote(p38.hash_text(old))} "
            f"WHERE case_id = {quote(cid)} AND para_idx = {row['para_idx']} AND hudoc_para_no = {g} AND text = {quote(new)};")
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
