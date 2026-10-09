#!/usr/bin/env python3
"""
Smoke test: every public endpoint, with and without filters, must answer 200.

It exists because a helper that handled an empty filter list but not None made
/api/facets?q=... return 500 while every test that only searched passed.

    ECHR_DB_PATH=/path/to/echr_search.db python3 scripts/smoke_api.py

Needs a real database (a copy is fine); the API is called in-process.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
os.environ.setdefault("ECHR_DB_PATH", "data/echr_search.db")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)

CASES = [
    ("/health", {}),
    ("/api/stats", {}),
    ("/api/facets", {}),
    ("/api/facets", {"q": "torture"}),
    ("/api/facets", {"q": "torture", "doc_types": "decision"}),
    ("/api/facets", {"q": "torture", "doc_types": "chamber,committee", "articles": "3"}),
    ("/api/analytics", {}),
    ("/api/analytics", {"q": "torture"}),
    ("/api/analytics", {"q": "torture", "doc_types": "decision"}),
    ("/api/browse", {}),
    ("/api/browse", {"doc_types": "grand_chamber"}),
    ("/api/browse", {"doc_types": "decision", "page_size": 5}),
    ("/api/search", {"q": "pressing social need"}),
    ("/api/search", {"q": "torture", "doc_types": "judgment"}),
    ("/api/search", {"q": "torture", "doc_types": "decision"}),
    ("/api/search", {"q": "torture", "doc_types": "chamber,grand_chamber,committee,decision"}),
    ("/api/search", {"q": "torture", "doc_types": "nonsense"}),
    ("/api/search", {"q": "case:30210/96"}),
    ("/api/search", {"q": "torture", "group": "paragraph", "page_size": 5}),
    ("/api/suggest", {"q": "Kudla v. Poland"}),
    ("/api/cases/001-58920", {}),
    ("/api/cases/001-58920/cited_by", {}),
    ("/api/cases/001-58920/cites", {}),
]


def main_() -> int:
    failures = 0
    for path, params in CASES:
        r = client.get(path, params=params)
        ok = r.status_code == 200
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {r.status_code}  {path} {params}")
        if not ok:
            print("      ", r.text[:200])
    print(f"\n{len(CASES) - failures}/{len(CASES)} endpoints answered 200")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main_())
