#!/usr/bin/env python3
"""
Rebuild citations.json — the citation graph behind the Semantic Search page's
constellation (served by api/rag_mod.py from /data/rag/citations.json) — from the
case_citations table that scripts/p29_extract_citations.py writes, so the two
pages show the same numbers.

Shape (one node per case that has at least one edge):

    {"<case_id>": {"title": ..., "case_no": ..., "judgment_date": "DD/MM/YYYY",
                   "cites": ["<case_id>", ...], "cited_by": ["<case_id>", ...]}}

Usage
-----
    python3 scripts/build_rag_citations_json.py --db data/echr_search.db \\
            --out /data/rag/citations.json

The file is written to a temporary name and renamed, so a reader never sees a
half-written graph.  rag_mod caches the graph in memory on first use; restart the
API to pick up a new file.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict


def build_graph(con: sqlite3.Connection) -> dict[str, dict]:
    cites: dict[str, set] = defaultdict(set)
    cited_by: dict[str, set] = defaultdict(set)
    for citing, cited in con.execute(
            "SELECT DISTINCT citing_case_id, cited_case_id FROM case_citations"):
        cites[citing].add(cited)
        cited_by[cited].add(citing)
    ids = set(cites) | set(cited_by)
    graph: dict[str, dict] = {}
    for case_id, title, case_no, judgment_date in con.execute(
            "SELECT case_id, title, case_no, judgment_date FROM cases"):
        if case_id not in ids:
            continue
        graph[case_id] = {
            "title": title or "",
            "case_no": case_no or "",
            "judgment_date": judgment_date or "",
            "cites": sorted(cites.get(case_id, ())),
            "cited_by": sorted(cited_by.get(case_id, ())),
        }
    return graph


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/echr_search.db")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        graph = build_graph(con)
    except sqlite3.OperationalError as exc:
        print(f"ERROR: {exc} (has p29_extract_citations.py been run?)", file=sys.stderr)
        return 1
    if not graph:
        print("ERROR: case_citations is empty; refusing to write an empty graph", file=sys.stderr)
        return 1
    tmp = f"{args.out}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(graph, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, args.out)
    edges = sum(len(v["cites"]) for v in graph.values())
    print(f"wrote {args.out}: {len(graph):,} cases, {edges:,} citation edges")
    return 0


if __name__ == "__main__":
    sys.exit(main())
