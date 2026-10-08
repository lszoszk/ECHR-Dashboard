#!/usr/bin/env python3
"""Build cases_meta.json — the RAG's per-case metadata sidecar.

Keyed by case_id, consumed by rag_mod (result cards), ann_build_eval / serve
(the +0.05 importance authority boost) and the benchmark experiments.

Like row_section.tsv, no script in the repo produced this file — it was made
ad hoc, which is how it came to sit at May's case list while the corpus moved
on. Both are now generated, so a corpus update can refresh them.

Shape (verbatim from the deployed file):
  {"001-57516": {"title": …, "case_no": …, "date": "14/11/1960", "state": …,
                 "importance": "1", "conclusion": …, "violation": [],
                 "body": "Court (Chamber)", "hudoc": "https://…"}}

`violation` is stored in the database as a JSON-encoded string; it is decoded
here so downstream code gets a real list. `date` keeps the database's DD/MM/YYYY
form — the RAG displays it verbatim and does not sort on it.

Usage (inside the echr-api container, where /data is mounted):
    python3 build_cases_meta.py > /data/rag/cases_meta.json.new
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

DB = os.environ.get("ECHR_DB_PATH", "/data/echr_search.db")


def as_list(value):
    """violation / non_violation are JSON-encoded lists in the DB."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    s = str(value).strip()
    if not s:
        return []
    if s[0] == "[":
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except (ValueError, TypeError):
            pass
    return [p.strip() for p in s.replace(",", ";").split(";") if p.strip()]


def main():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out = {}
    for r in conn.execute(
        """SELECT case_id, title, case_no, judgment_date, respondent_state,
                  importance, conclusion, violation, originating_body, hudoc_url
           FROM cases"""
    ):
        out[r["case_id"]] = {
            "title": r["title"] or "",
            "case_no": r["case_no"] or "",
            "date": r["judgment_date"] or "",
            "state": r["respondent_state"] or "",
            "importance": str(r["importance"] or ""),
            "conclusion": r["conclusion"] or "",
            "violation": as_list(r["violation"]),
            "body": r["originating_body"] or "",
            "hudoc": r["hudoc_url"] or "",
        }
    json.dump(out, sys.stdout, ensure_ascii=False)
    print(f"[done] {len(out):,} cases", file=sys.stderr)


if __name__ == "__main__":
    main()
