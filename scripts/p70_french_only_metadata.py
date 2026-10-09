#!/usr/bin/env python3
"""
Put HUDOC's citation metadata for the French-only judgments into the hudoc_metadata table.

The 9,283 judgments that HUDOC flags English but publishes only in French (downloaded by the
reconciliation worker) are not rows in `cases`, so p69 never fetched them. Their English-flag
catalogue record carries the curated "Strasbourg case-law" list (scl) for about half of them and no
extractedappno; the French record carries extractedappno for all of them and more scl lists.

For each of them this script writes one hudoc_metadata row keyed by the catalogue item id (the id the
judgment will have in `cases` once translated). Fields come from the catalogue record, scl is the
union of both records' lists and extractedappno comes from the French record. p29_extract_citations
reads the rows when the judgment is loaded; until then they are inert (p29 skips ids that are not in
`cases`). Rows for ids that are in `cases` are never touched.

    python3 scripts/p70_french_only_metadata.py --db echr.db --meta metadata_with_french.json \\
            --jobs output/hudoc-reconciliation/missing-judgments/downloads.sqlite            # dry run
    ... --apply                                                                              # write

Rollback:  DELETE FROM hudoc_metadata WHERE case_id NOT IN (SELECT case_id FROM cases);
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p29_extract_citations as p29  # noqa: E402

COLUMNS = ["violation", "nonviolation", "article", "conclusion", "scl", "extractedappno", "separateopinion",
           "externalsources", "issue", "rulesofcourt", "representedby", "importance", "kpthesaurus",
           "judgementdate", "kpdate", "ecli"]


def items(value) -> list[str]:
    return [x.strip() for x in str(value or "").split(";") if x.strip()]


def union(*lists: str) -> str:
    seen: dict[str, None] = {}
    for value in lists:
        for item in items(value):
            seen.setdefault(item)
    return ";".join(seen)


def merge(catalogue: dict, french: dict | None) -> dict:
    """One hudoc_metadata row from the English-flag catalogue record and the French record."""
    french = french or {}
    row = {c: catalogue.get(c) for c in COLUMNS}
    row["scl"] = union(catalogue.get("scl"), french.get("scl"))
    row["extractedappno"] = union(catalogue.get("extractedappno"), french.get("extractedappno"))
    for c in ("separateopinion", "externalsources", "issue", "rulesofcourt"):
        row[c] = row[c] or french.get(c) or ""
    return row


def citing_doc(case_id: str, catalogue: dict) -> p29.Doc:
    title = catalogue.get("docname") or ""
    left, _, right = p29.fold(title.replace("CASE OF ", "")).partition(" v. ")
    day = (catalogue.get("judgementdate") or "").split(" ")[0]
    return p29.Doc(
        case_id=case_id, date_str=day, date=p29.parse_date(day), is_decision=False, rank=0,
        appnos=frozenset(a for a in items(catalogue.get("appno")) if p29.APPNO_RE.fullmatch(a)),
        is_gc=False, applicant=frozenset(p29.tokens(left)),
        lead=frozenset(p29.tokens(re.split(r",| and ", left)[0])), respondent=frozenset(p29.tokens(right)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--meta", required=True, help="p69 fetch output that includes the French source records")
    ap.add_argument("--jobs", required=True, help="reconciliation downloads.sqlite (opened read-only)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", help="write the resolved links and counts here (JSON)")
    args = ap.parse_args()

    meta = json.loads(Path(args.meta).read_text())
    jobs = sqlite3.connect(f"file:{args.jobs}?mode=ro", uri=True).execute(
        "SELECT case_id, source_case_id, metadata FROM jobs WHERE source_language = 'FRE'").fetchall()
    con = sqlite3.connect(args.db, timeout=600)
    con.row_factory = sqlite3.Row
    in_cases = {r[0] for r in con.execute("SELECT case_id FROM cases")}

    rows, docs, stats = {}, {}, Counter()
    for case_id, source_id, md in jobs:
        if case_id in in_cases:
            stats["already_in_cases"] += 1
            continue
        catalogue = json.loads(md)
        french = meta.get(source_id)
        stats["french_record_missing"] += french is None
        rows[case_id] = merge(catalogue, french)
        docs[case_id] = citing_doc(case_id, catalogue)
    stats["rows"] = len(rows)
    stats["with_scl"] = sum(bool(r["scl"]) for r in rows.values())
    stats["with_extractedappno"] = sum(bool(r["extractedappno"]) for r in rows.values())

    # Which corpus judgments would these judgments cite? Same rules as p29 uses for corpus judgments.
    idx = p29.build_indexes(con.cursor())
    idx = idx._replace(docs={**idx.docs, **docs})
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    mem.execute("CREATE TABLE hudoc_metadata (case_id TEXT, scl TEXT, extractedappno TEXT)")
    mem.executemany("INSERT INTO hudoc_metadata VALUES (?,?,?)",
                    [(k, v["scl"], v["extractedappno"]) for k, v in rows.items()])
    link_stats: Counter = Counter()
    links = p29.hudoc_additions(mem.cursor(), idx, [], {}, link_stats)
    cited_by = Counter(cited for _, cited, *_ in links)
    stats["links"] = len(links)
    stats["citing_judgments_with_links"] = len({c for c, *_ in links})
    stats["corpus_judgments_gaining_citations"] = len(cited_by)
    print(json.dumps({"rows": dict(stats), "resolution": dict(link_stats)}, indent=1))
    top = cited_by.most_common(5)
    for case_id, n in top:
        d = con.execute("SELECT title FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        have = con.execute("SELECT count(DISTINCT citing_case_id) FROM case_citations WHERE cited_case_id = ?",
                           (case_id,)).fetchone()[0]
        print(f"  +{n:>3} French-only citing judgments on {d['title']}  (now cited by {have})")
    if args.report:
        Path(args.report).write_text(json.dumps(
            {"stats": dict(stats), "resolution": dict(link_stats),
             "links": [[c, k, m] for c, k, _, _, m in links]}, ensure_ascii=False))

    if not args.apply:
        print("dry run: nothing written (use --apply)")
        return 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.execute("PRAGMA busy_timeout = 600000")
    cols = ["case_id", "fetched_at"] + COLUMNS
    with con:
        con.executemany(
            f"INSERT OR REPLACE INTO hudoc_metadata ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [(k, now, *[v[c] for c in COLUMNS]) for k, v in rows.items()])
    total = con.execute("SELECT count(*) FROM hudoc_metadata").fetchone()[0]
    print(f"wrote {len(rows):,} rows; hudoc_metadata now has {total:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
