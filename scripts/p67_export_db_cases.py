#!/usr/bin/env python3
"""P67 — stream the live corpus out of the DB as JSONL, one case per line.

Half of the full Statistics regeneration. `build_pages_dashboard.py` consumes a
JSONL export, but no existing export matches the database any more:

  docs/data/echr_cases_enriched_final.jsonl   2026-04-16, pre-Phase-2 sections
  /data/echr_cases.jsonl (VM)                 2026-05-11, pre-P5x heal passes
                                              (Operative part 834,521 vs 183,451)

So the paragraphs must come from the DB. The seven HUDOC metadata fields the DB
does NOT carry (chamber_composed_of, domestic_law, international_law,
rules_of_court, separate_opinion, strasbourg_caselaw, hudoc_kpthesaurus) are
merged back in by `p68_merge_hudoc_metadata.py` on the other side of the pipe.

Where the two sources disagree the DB wins, because it is the healed one — P61
in particular rewrote `article_no`, which in the April export still carries the
comma-mashed compound strings.

TEXT IS DELIBERATELY NOT SHIPPED. build_pages_dashboard.py touches paragraph
text exactly once (line 436: `if not text: continue`) and never reads its
content, so this emits "x" for a non-blank row and "" for a blank one. That is
byte-for-byte equivalent for every statistic while turning a ~2 GB transfer
into ~150 MB. It also means the output is NOT suitable for --export-data or
--sample-output; point those at scratch paths.

Streams to stdout, so nothing is written to the VM's disk (which sits at 90%).
Progress goes to stderr.

Usage:
  ssh amuvmuser@… 'docker exec -i echr-api python3 -' < p67_export_db_cases.py \
      | python3 scripts/p68_merge_hudoc_metadata.py --meta <april.jsonl> > current.jsonl
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

DB = os.environ.get("ECHR_DB_PATH", "/data/echr_search.db")


def split_multi(value):
    """Normalise a multi-valued DB column to a list of strings.

    These columns are not uniform: `violation` / `non_violation` / `keywords`
    hold a JSON-encoded list ('["6-1"]'), while others hold a ;- or
    ,-separated string. Splitting a JSON payload on ';' yields the literal
    ['["6-1"]'], which silently poisons every outcome and article statistic —
    so try JSON first and only then fall back to splitting.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    s = str(value).strip()
    if not s:
        return []
    if s[0] in "[{":
        try:
            parsed = json.loads(s)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
        if isinstance(parsed, dict):
            return [str(v).strip() for v in parsed.values() if str(v).strip()]
    parts = [p.strip() for p in s.replace(",", ";").split(";")]
    return [p for p in parts if p]


def main():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Articles live in their own table (post-P61).
    articles: dict[str, list[str]] = {}
    for r in cur.execute("SELECT case_id, article FROM case_articles"):
        if r["article"]:
            articles.setdefault(r["case_id"], []).append(str(r["article"]).strip())

    cases = {}
    order = []
    for r in cur.execute(
        """SELECT case_id, case_no, title, hudoc_url, ecli, judgment_date,
                  respondent_state, importance, conclusion, violation,
                  non_violation, keywords, originating_body, document_type
           FROM cases ORDER BY case_id"""
    ):
        cid = r["case_id"]
        order.append(cid)
        cases[cid] = {
            "case_id": cid,
            "case_no": r["case_no"],
            "title": r["title"],
            "hudoc_url": r["hudoc_url"],
            "ecli": r["ecli"],
            "judgment_date": r["judgment_date"],
            "respondent_state": r["respondent_state"],
            "importance": r["importance"],
            "conclusion": r["conclusion"],
            "violation": split_multi(r["violation"]),
            "non-violation": split_multi(r["non_violation"]),
            "keywords": split_multi(r["keywords"]),
            "originating_body": r["originating_body"],
            "document_type": r["document_type"],
            "article_no": ";".join(articles.get(cid, [])),
            "paragraphs": [],
        }

    print(f"[p67] {len(cases):,} cases, streaming paragraphs…", file=sys.stderr)

    # Index-ordered scan over (case_id, para_idx) — idx_paragraphs_case_para.
    # Cases come out in the same order as `order`, so each is emitted and freed
    # as soon as its last paragraph is seen; peak memory stays flat.
    emitted = 0
    n_paras = 0
    current = None
    out = sys.stdout
    for r in cur.execute(
        "SELECT case_id, section, row_role, text FROM paragraphs "
        "ORDER BY case_id, para_idx"
    ):
        cid = r["case_id"]
        if cid != current:
            if current is not None and current in cases:
                out.write(json.dumps(cases.pop(current), ensure_ascii=False) + "\n")
                emitted += 1
                if emitted % 2000 == 0:
                    print(f"[p67]   {emitted:,} cases emitted", file=sys.stderr)
            current = cid
        c = cases.get(cid)
        if c is None:
            continue                       # paragraph for a case not in `cases`
        c["paragraphs"].append({
            "section": r["section"],
            "row_role": r["row_role"],
            # presence-only placeholder — see the module docstring
            "text": "x" if (r["text"] or "").strip() else "",
        })
        n_paras += 1

    if current is not None and current in cases:
        out.write(json.dumps(cases.pop(current), ensure_ascii=False) + "\n")
        emitted += 1

    # Cases with no paragraph rows at all still belong in the corpus.
    for cid in order:
        if cid in cases:
            out.write(json.dumps(cases.pop(cid), ensure_ascii=False) + "\n")
            emitted += 1

    print(f"[p67] done: {emitted:,} cases, {n_paras:,} paragraph rows",
          file=sys.stderr)


if __name__ == "__main__":
    main()
