#!/usr/bin/env python3
"""
Merge the export of scripts/export_search_citations.py into the Statistics citation snapshot
(docs/data/judgment-citations.json) as its "with_search_graph" view, the one the Statistics page
shows first, so that "Most cited judgments" gives the same counts as Search's Cited by.

    python3 scripts/merge_search_citations.py search_citations.json [docs/data/judgment-citations.json]

Run it after scripts/refresh_statistics.py, which rewrites the snapshot without this view.
"""
import json
import sys
from pathlib import Path

src = json.loads(Path(sys.argv[1]).read_text())
target = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/data/judgment-citations.json")
snap = json.loads(target.read_text())
snap["with_search_graph"] = {
    "scope": src["source"],
    "ranking": src["ranking"],
    "citing_by_target": src["citing_by_target"],
    "citing_judgments": src["citing_judgments"],
    "coverage": {**snap.get("coverage", {}), **src["coverage"]},
}
target.write_text(json.dumps(snap, ensure_ascii=True, indent=2) + "\n")
top = src["ranking"][0]
print(f"merged into {target}: {len(src['ranking'])} judgments; top {top['title']} {top['cited_by_count']}")
