#!/usr/bin/env python3
"""
Build the English–French parallel corpus used as translation memory (TM) and test set.

Only Grand Chamber judgments and Key cases exist in both languages on HUDOC (Rules of Court 57/76,
HUDOC FAQ). For each such English judgment in the corpus, the French twin is found by ECLI, its DOCX
is parsed with the same parser as the corpus (p34.parse_docx), and paragraphs are aligned by the
paragraph number printed in the judgment (hudoc_para_no). Operative-part rows are aligned by order
when both sides have the same number of them.

About one judgment in ten (chosen by a hash of its id, so the choice is stable) is held out as the
test set and never used as translation memory.

    python3 scripts/mt/build_parallel.py --corpus-db DB --out mt/parallel.sqlite [--limit 400]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
  en_id TEXT PRIMARY KEY, fr_id TEXT, title TEXT, judgment_date TEXT, importance TEXT,
  grand_chamber INTEGER, split TEXT, en_numbered INTEGER, fr_numbered INTEGER, aligned INTEGER,
  status TEXT, built_at TEXT);
CREATE TABLE IF NOT EXISTS pairs (
  en_id TEXT, para_key TEXT, section TEXT, row_role TEXT, fr TEXT, en TEXT,
  PRIMARY KEY (en_id, para_key));
CREATE VIRTUAL TABLE IF NOT EXISTS pairs_fts USING fts5(fr, content='pairs', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS pairs_ai AFTER INSERT ON pairs BEGIN
  INSERT INTO pairs_fts(rowid, fr) VALUES (new.rowid, new.fr); END;
"""


def split_of(en_id: str) -> str:
    return "test" if int(hashlib.sha1(en_id.encode()).hexdigest(), 16) % 10 == 0 else "tm"


def align(en_rows: list[dict], fr_rows: list[dict]) -> list[tuple]:
    """[(para_key, section, row_role, fr, en)] aligned by printed paragraph number, then operative rows by order."""
    def numbered(rows):
        out = {}
        for r in rows:
            n, t = r.get("hudoc_para_no"), (r.get("text") or "").strip()
            if n is None or not t:
                continue
            out.setdefault(str(n), []).append(r)
        return {k: v[0] for k, v in out.items() if len(v) == 1}
    en_n, fr_n = numbered(en_rows), numbered(fr_rows)
    pairs = [(f"p{k}", en_n[k].get("section"), en_n[k].get("row_role"), fr_n[k]["text"], en_n[k]["text"])
             for k in en_n if k in fr_n]
    op = lambda rows: [r for r in rows if (r.get("section") or "").lower().startswith("operative")
                       and (r.get("text") or "").strip() and r.get("hudoc_para_no") is None]
    en_op, fr_op = op(en_rows), op(fr_rows)
    if en_op and len(en_op) == len(fr_op):
        pairs += [(f"op{i}", "Operative part", e.get("row_role"), f["text"], e["text"])
                  for i, (e, f) in enumerate(zip(en_op, fr_op))]
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--fetch-delay", type=float, default=0.4)
    args = ap.parse_args()

    os.environ["P34_FETCH_DELAY"] = str(args.fetch_delay)
    import p60_monthly_update as p60
    p34 = p60._load_module(p60.P34_PATH, "p34_rebuild_from_hudoc")

    src = sqlite3.connect(f"file:{args.corpus_db}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    cands = src.execute(
        "SELECT case_id, title, judgment_date, ecli, importance, originating_body FROM cases "
        "WHERE document_type LIKE 'Judgment%' AND ecli LIKE 'ECLI:%' AND title NOT LIKE '%translation%' "
        "AND (originating_body LIKE '%Grand Chamber%' OR importance IN ('1', 'Key cases')) "
        "ORDER BY (originating_body LIKE '%Grand Chamber%') DESC, judgment_date DESC").fetchall()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out = sqlite3.connect(args.out)
    out.executescript(SCHEMA)
    done = {r[0] for r in out.execute("SELECT en_id FROM docs")}
    todo = [c for c in cands if c["case_id"] not in done][:args.limit]
    print(f"candidates {len(cands):,}; already built {len(done):,}; this run {len(todo):,}", flush=True)
    stats = {"aligned_docs": 0, "pairs": 0, "no_twin": 0, "fetch_failed": 0}
    for i, c in enumerate(todo, 1):
        en_id = c["case_id"]
        status, fr_id, en_num, fr_num, n_pairs = "ok", None, 0, 0, 0
        try:
            d = p60.hudoc_get({"query": f'contentsitename:ECHR AND ecli:"{c["ecli"]}" AND languageisocode:"FRE"',
                               "select": "itemid,docname", "sort": "itemid Ascending", "start": "0", "length": "5"})
            fr = [x["columns"]["itemid"] for x in d.get("results", []) if x["columns"]["itemid"].startswith("001-")]
            if not fr:
                status = "no_twin"
            else:
                fr_id = fr[0]
                fr_rows, _ = p34.parse_docx(p34.fetch_docx(fr_id))
                en_rows = [dict(r) for r in src.execute(
                    "SELECT section, para_idx, hudoc_para_no, row_role, text FROM paragraphs "
                    "WHERE case_id = ? ORDER BY para_idx, rowid", (en_id,))]
                pairs = align(en_rows, fr_rows)
                en_num = sum(1 for r in en_rows if r.get("hudoc_para_no") is not None)
                fr_num = sum(1 for r in fr_rows if r.get("hudoc_para_no") is not None)
                n_pairs = len(pairs)
                out.executemany("INSERT OR IGNORE INTO pairs (en_id, para_key, section, row_role, fr, en) "
                                "VALUES (?,?,?,?,?,?)", [(en_id, *p) for p in pairs])
        except Exception as exc:                                              # noqa: BLE001
            status = "fetch_failed: " + str(exc)[:80]
        stats["aligned_docs"] += bool(n_pairs)
        stats["pairs"] += n_pairs
        stats["no_twin"] += status == "no_twin"
        stats["fetch_failed"] += status.startswith("fetch_failed")
        out.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (en_id, fr_id, c["title"], c["judgment_date"], c["importance"],
                     int("Grand Chamber" in (c["originating_body"] or "")), split_of(en_id),
                     en_num, fr_num, n_pairs, status, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
        out.commit()
        if i % 25 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)}  {json.dumps(stats)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
