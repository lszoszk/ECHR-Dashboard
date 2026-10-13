#!/usr/bin/env python3
"""p75 — build echr_fr.db: the French originals of the judgments HUDOC publishes only in French.

The API searches this file when a request carries lang=fr. It has the main database's tables (cases,
paragraphs, paragraphs_fts, case_articles, and empty citation tables), so the same search code runs on
it unchanged; only the full-text index differs: no English stemmer, accents ignored (unicode61
remove_diacritics 2), so `requerant` finds `requérant` and a word ending is matched with `*`.

Input: the reconciliation worker's parsed judgments (<codex-dir>/parsed/*.json, read-only). A judgment's
case_id is the one the main database uses for its machine translation, where there is one, so a client
can move between the two. Metadata is mapped exactly as the monthly update maps it (p60.map_metadata),
so Articles, States, formations and importance use the same values as the English search; the title,
the conclusion and the HUDOC link are the French ones.

    python3 scripts/p75_build_french_db.py --codex-dir output/hudoc-reconciliation/missing-judgments \\
        --out /path/echr_fr.db [--limit N] [--audit-out audit.json]

The output is a new file (an existing one is replaced only with --force). Deploy = copy it next to the
main database; rollback = remove it.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SCHEMA = """
CREATE TABLE cases (
    case_id TEXT PRIMARY KEY, case_no TEXT, title TEXT, hudoc_url TEXT, judgment_date TEXT, ecli TEXT,
    respondent_state TEXT, importance TEXT, conclusion TEXT, violation TEXT, non_violation TEXT,
    violation_inferred TEXT, non_violation_inferred TEXT, keywords TEXT, originating_body TEXT,
    document_type TEXT, strasbourg_caselaw TEXT, domestic_law TEXT, international_law TEXT,
    rules_of_court TEXT, separate_opinion TEXT, text_origin TEXT, source_case_id TEXT,
    source_language TEXT, title_en TEXT);
CREATE TABLE paragraphs (
    rowid INTEGER PRIMARY KEY, case_id TEXT NOT NULL, section TEXT, para_idx INTEGER, title TEXT,
    keywords_text TEXT, text TEXT, hudoc_para_no INTEGER, numbering_block TEXT, row_role TEXT,
    logical_para_idx INTEGER, display_para_no INTEGER);
CREATE VIRTUAL TABLE paragraphs_fts USING fts5(
    title, keywords_text, text, content='paragraphs', content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2');
CREATE TABLE case_articles (case_id TEXT NOT NULL, article TEXT NOT NULL);
CREATE TABLE case_citations (citing_case_id TEXT NOT NULL, cited_case_id TEXT NOT NULL,
    citing_paragraph_rowid INTEGER, raw_text TEXT, extraction_method TEXT);
CREATE TABLE french_only_citations (citing_case_id TEXT NOT NULL, cited_case_id TEXT NOT NULL,
    extraction_method TEXT);
CREATE TABLE french_only_cases (case_id TEXT PRIMARY KEY, source_id TEXT, title TEXT, case_no TEXT,
    judgment_date TEXT, respondent_state TEXT, hudoc_url TEXT);
"""
INDEXES = """
CREATE INDEX idx_paragraphs_case_id ON paragraphs(case_id);
CREATE INDEX idx_paragraphs_case_para ON paragraphs(case_id, para_idx);
-- covering indexes the search reads instead of whole rows (api/main.py, _par_hint)
CREATE INDEX idx_par_meta ON paragraphs(rowid, case_id, section, row_role);
CREATE INDEX idx_par_case_section ON paragraphs(case_id, section);
CREATE INDEX idx_case_articles_article ON case_articles(article);
CREATE INDEX idx_case_articles_case ON case_articles(case_id);
CREATE INDEX idx_cases_respondent_state ON cases(respondent_state);
CREATE INDEX idx_cases_judgment_date ON cases(judgment_date);
CREATE INDEX idx_cc_citing ON case_citations(citing_case_id);
CREATE INDEX idx_cc_cited ON case_citations(cited_case_id);
CREATE INDEX idx_foc_cited ON french_only_citations(cited_case_id);
"""
_LEAD_NO = re.compile(r"^\s*(\d{1,4})\s*\.\s")


def audit(data: dict, stats: Counter) -> None:
    """Deterministic checks of one parsed judgment: printed § numbers that disagree with the text,
    numbers that go backwards, judgments without numbered paragraphs."""
    nums = []
    for r in data["paragraphs"]:
        no = r.get("hudoc_para_no")
        m = _LEAD_NO.match(r.get("text") or "")
        if no is not None:
            nums.append((r.get("numbering_block"), no))
            stats["numbered rows"] += 1
            if m and int(m.group(1)) != no:
                stats["number differs from the text"] += 1
        elif m and r.get("row_role") == "paragraph" and r.get("section") not in ("Operative part",):
            stats["numbered in the text, not in the row"] += 1
    if not nums:
        stats["judgments without numbered paragraphs"] += 1
    back = sum(1 for (b1, a), (b2, b) in zip(nums, nums[1:]) if b1 == b2 and b < a)
    stats["numbers going backwards"] += back
    if data.get("needs_manual_review"):
        stats["flagged for manual review by the worker"] += 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--codex-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0, help="first N judgments only (testing)")
    ap.add_argument("--force", action="store_true", help="replace an existing output file")
    ap.add_argument("--audit-out", help="write the per-check counts as JSON")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        if not args.force:
            print(f"{out} exists; use --force to replace it", file=sys.stderr)
            return 2
        out.unlink()

    import p60_monthly_update as p60
    build_db = p60._load_module(p60.BUILD_DB_PATH, "build_db")
    kpthes = json.loads(p60.KPTHESAURUS_PATH.read_text())

    files = sorted((Path(args.codex_dir) / "parsed").glob("*.json"))
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)
    stats: Counter = Counter()
    done = 0
    for f in files:
        data = json.loads(f.read_text())
        if (data.get("source_language") or "").upper() != "FRE":
            continue
        om, sm = data["official_metadata"], data.get("source_metadata") or {}
        meta = p60.map_metadata(om, kpthes, build_db)
        cid, src = data["case_id"], data.get("source_case_id") or data["case_id"]
        title_fr = (sm.get("docname") or "").strip() or meta["title"]
        conclusion_fr = (sm.get("conclusion") or "").strip() or meta["conclusion"]
        j = build_db._json_field
        con.execute(
            "INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, meta["case_no"], title_fr, f"https://hudoc.echr.coe.int/fre?i={src}", meta["judgment_date"],
             meta["ecli"], meta["respondent_state"], meta["importance"], j(conclusion_fr), j(meta["violation"]),
             j(meta["non_violation"]), j(meta["violation_inferred"] or []), j(meta["non_violation_inferred"] or []),
             j(meta["keywords"]), j(meta["originating_body"]), meta["document_type"],
             j(meta["strasbourg_caselaw"]), None, None, meta["rules_of_court"], None,
             "original", src, "FRE", p60.TRANSLATION_NOTE.sub("", meta["title"])))
        first = True
        for r in data["paragraphs"]:
            text = (r.get("text") or "").strip()
            if not text:
                continue
            con.execute(
                "INSERT INTO paragraphs (case_id, section, para_idx, title, keywords_text, text, hudoc_para_no, "
                "numbering_block, row_role, logical_para_idx, display_para_no) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (cid, r.get("section"), r.get("para_idx"), title_fr if first else "", "", text,
                 r.get("hudoc_para_no"), r.get("numbering_block"), r.get("row_role"),
                 r.get("logical_para_idx"), r.get("display_para_no")))
            first = False
            stats["rows"] += 1
            stats["characters"] += len(text)
        for art in build_db._normalize_articles(meta["article_no"]):
            con.execute("INSERT INTO case_articles VALUES (?,?)", (cid, art))
        audit(data, stats)
        done += 1
        if args.limit and done >= args.limit:
            break
    stats["judgments"] = done
    con.commit()
    con.execute("INSERT INTO paragraphs_fts(paragraphs_fts) VALUES ('rebuild')")
    con.executescript(INDEXES)
    con.execute("ANALYZE")
    con.commit()
    con.execute("VACUUM")
    con.execute("PRAGMA journal_mode = WAL")    # as the main database: the API opens both read-only in WAL
    con.close()
    report = dict(stats)
    report["size_mb"] = round(out.stat().st_size / 1e6)
    print(json.dumps(report, indent=1))
    if args.audit_out:
        Path(args.audit_out).write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
