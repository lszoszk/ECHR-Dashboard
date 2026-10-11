#!/usr/bin/env python3
"""p76 — citation links of the French originals (echr_fr.db), so that lang=fr shows Cites / Cited by.

The French database (scripts/p75_build_french_db.py) is searched with the same code as the main one,
which counts citations in its case_citations table. This script fills that table from the main
database, in three directions:

  * a French original cites a judgment of the corpus: the rows p70 derived from HUDOC's metadata
    (french_only_citations in the main database), copied as they are;
  * a judgment of the corpus cites a French original:
      - for a judgment that has been machine-translated, the links the main database already holds
        for its translation (case_citations, and french_only_citations from other French-only
        judgments), so the counts equal the English ones;
      - otherwise, the application numbers that belong to no judgment of the corpus but to a French
        original: in the judgment's text (an English paragraph naming the number, unless it is a
        "(dec.)" reference), or, where the text lacks it, in HUDOC's extracted numbers
        (hudoc_metadata.extractedappno, mostly footnotes);
  * a French original cites another: the same numbers in the French texts (a "(déc.)" reference
    is a decision, not the judgment).
A judgment never cites itself or a later judgment. Where several French originals share a number
(merits and just satisfaction), p29's rules pick one.

    python3 p76_french_citations.py --main /data/echr_search.db --fr /data/echr_fr.db          # report
    python3 p76_french_citations.py --main /data/echr_search.db --fr /data/echr_fr.db --apply  # write

--apply replaces the French database's case_citations in one transaction. Needs
p29_extract_citations.py next to it.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

_spec = importlib.util.spec_from_file_location("p29", Path(__file__).with_name("p29_extract_citations.py"))
p29 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p29)

FR_DEC_RE = re.compile(r"\(d[ée]c\.\)")


def fr_decision_reference(text: str, start: int, end: int) -> bool:
    """A "(déc.)" next to the number: a decision, not the judgment under the same number."""
    return bool(FR_DEC_RE.search(text[max(0, start - 70):end + 12]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--main", required=True)
    ap.add_argument("--fr", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--samples", type=int, default=0, help="print N random links per method, for checking")
    args = ap.parse_args()

    main_con = sqlite3.connect(f"file:{args.main}?mode=ro", uri=True)
    main_con.row_factory = sqlite3.Row
    fr_con = sqlite3.connect(args.fr if args.apply else f"file:{args.fr}?mode=ro", uri=not args.apply)
    fr_con.row_factory = sqlite3.Row

    idx = p29.build_indexes(main_con.cursor())             # the corpus, as p29 sees it
    fr_idx = p29.build_indexes(fr_con.cursor())            # the French originals
    translated = {cid for cid in fr_idx.docs if cid in idx.docs}
    # Numbers that only French originals hold (a number the corpus holds resolves there, as in p29).
    fr_only = {a: docs for a, docs in fr_idx.by_appno.items() if a not in idx.by_appno}
    stats: Counter = Counter()
    links: dict[tuple[str, str], tuple[str, str]] = {}    # (citing, cited) -> (method, excerpt)

    def add(citing: str, cited: str, method: str, raw: str) -> None:
        if citing != cited and (citing, cited) not in links:
            links[(citing, cited)] = (method, raw[:300])
            stats[method] += 1

    # 1. French original -> corpus (HUDOC metadata, p70)
    for r in main_con.execute("SELECT citing_case_id, cited_case_id FROM french_only_citations"):
        if r["citing_case_id"] in fr_idx.docs:
            add(r["citing_case_id"], r["cited_case_id"], "hudoc_metadata", "HUDOC metadata (p70)")

    # 2a. corpus or French-only -> a translated French original: the main database's links
    if translated:
        ph = ",".join("?" * len(translated))
        for r in main_con.execute(f"SELECT DISTINCT citing_case_id, cited_case_id, extraction_method FROM case_citations "
                                  f"WHERE cited_case_id IN ({ph})", sorted(translated)):
            add(r["citing_case_id"], r["cited_case_id"], "corpus_" + (r["extraction_method"] or ""), "main case_citations")
        for r in main_con.execute(f"SELECT citing_case_id, cited_case_id FROM french_only_citations "
                                  f"WHERE cited_case_id IN ({ph})", sorted(translated)):
            add(r["citing_case_id"], r["cited_case_id"], "hudoc_metadata", "HUDOC metadata (p70)")

    def resolve(appno: str, citing_doc, text: str, start: int, end: int):
        cands = [d for d in fr_only.get(appno, []) if d.case_id not in translated]
        if not cands:
            return None
        doc, _ = p29.pick_for_appno(cands, text, start, end, False)
        if doc is None or (citing_doc.date and doc.date and doc.date > citing_doc.date):
            stats["later or none"] += 1
            return None
        return doc

    # 2b. corpus text -> untranslated French original (paragraphs naming a French-only number)
    seen_in_text: set[tuple[str, str]] = set()
    for appno in sorted(fr_only):
        n, y = appno.split("/")
        try:
            rows = main_con.execute("SELECT p.case_id, p.text FROM paragraphs_fts f JOIN paragraphs p ON p.rowid = f.rowid "
                                    "WHERE paragraphs_fts MATCH ?", (f'text : "{n} {y}"',)).fetchall()
        except sqlite3.OperationalError:
            continue
        for r in rows:
            citing = idx.docs.get(r["case_id"])
            if citing is None or r["case_id"] in idx.excluded or r["case_id"] in idx.not_citing:
                continue
            text = p29.plain(r["text"] or "")
            for a, s, e in p29.extract_appnos(text):
                if a != appno or a in citing.appnos:
                    continue
                seen_in_text.add((r["case_id"], a))
                if p29.is_decision_reference(text, s, e):
                    stats["(dec.) reference"] += 1
                    continue
                doc = resolve(a, citing, text, s, e)
                if doc:
                    add(r["case_id"], doc.case_id, "corpus_text_appno", text[max(0, s - 120):e + 60])

    # 2c. HUDOC's extracted numbers of corpus judgments (footnotes), where the text lacks the number
    for r in main_con.execute("SELECT case_id, extractedappno FROM hudoc_metadata"):
        citing = idx.docs.get(r["case_id"])
        if citing is None or r["case_id"] in idx.excluded or r["case_id"] in idx.not_citing:
            continue
        for a in (x.strip() for x in (r["extractedappno"] or "").split(";")):
            if a in fr_only and a not in citing.appnos and (r["case_id"], a) not in seen_in_text:
                cands = [d for d in fr_only[a] if d.case_id not in translated]
                doc = p29.pick_extracted(cands, citing) if cands else None
                if doc and not (citing.date and doc.date and doc.date > citing.date):
                    add(r["case_id"], doc.case_id, "fr_hudoc_extracted", f"HUDOC extracted application no. {a}")

    # 3. French original -> French original (numbers in the French texts)
    for r in fr_con.execute("SELECT case_id, text FROM paragraphs WHERE instr(text, '/') > 0"):
        citing = fr_idx.docs.get(r["case_id"])
        if citing is None:
            continue
        text = r["text"] or ""
        for a, s, e in p29.extract_appnos(text):
            if a not in fr_only or a in citing.appnos:
                continue
            if fr_decision_reference(text, s, e):
                stats["(déc.) reference"] += 1
                continue
            doc = resolve(a, citing, text, s, e)
            if doc:
                add(r["case_id"], doc.case_id, "fr_text_appno", text[max(0, s - 120):e + 60])

    cited_by = Counter(cited for _, cited in links)
    cites = Counter(citing for citing, _ in links if citing in fr_idx.docs)
    print(dict(stats))
    print(f"links {len(links):,}; French originals cited by at least one judgment {len(cited_by.keys() & fr_idx.docs.keys()):,}"
          f" of {len(fr_idx.docs):,}; citing something {len(cites):,}")
    for cid, n in [x for x in cited_by.most_common() if x[0] in fr_idx.docs][:6]:
        t = fr_con.execute("SELECT title FROM cases WHERE case_id = ?", (cid,)).fetchone()[0]
        print(f"  cited by {n:>4}: {t} ({cid}){' [translated]' if cid in translated else ''}")
    if args.samples:
        import random
        random.seed(7)
        for method in ("corpus_text_appno", "fr_text_appno", "fr_hudoc_extracted"):
            rows = [(k, v) for k, v in links.items() if v[0] == method]
            for (c, d), (m, raw) in random.sample(rows, min(args.samples, len(rows))):
                ct = (idx.docs.get(c) or fr_idx.docs.get(c))
                print(f"--- {m}: {c} ({ct.date_str if ct else ''}) -> {d} {fr_idx.docs[d].date_str} {sorted(fr_idx.docs[d].appnos)}\n    {raw!r}")
    if not args.apply:
        print("dry run: nothing written (use --apply)")
        return 0
    with fr_con:
        fr_con.execute("DELETE FROM case_citations")
        fr_con.executemany("INSERT INTO case_citations (citing_case_id, cited_case_id, citing_paragraph_rowid, raw_text, "
                           "extraction_method) VALUES (?,?,NULL,?,?)",
                           [(c, d, raw, m) for (c, d), (m, raw) in sorted(links.items())])
    fr_con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print(f"wrote {len(links):,} rows to {args.fr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
