#!/usr/bin/env python3
"""
P66 — ingest the admissibility decisions that the corpus cites.

Judgments cite decisions as ``Brusco v. Italy (dec.), no. 69789/01, 6 September
2001``.  Those decisions are separate HUDOC documents, and until they are in the
corpus the reference cannot become a link (scripts/p29_extract_citations.py drops
it rather than crediting a later judgment that shares the application number).

The script
  1. scans the corpus text for ``(dec.)`` references and collects, per application
     number, how many judgments cite it and the dates written next to it;
  2. asks HUDOC (English, DECISIONS collection) for those application numbers,
     keeping the decision whose date matches a cited date (or every decision of
     the number when no date matches);
  3. optionally adds the decisions HUDOC rates importance 1 or 2 (``--also-key``);
  4. fetches and parses each DOCX with the same helpers as p60_monthly_update.py
     and writes forward SQL plus a rollback script.

Commission decisions (``DECCOMMISSION``) are skipped: they are not Court documents.

Usage
-----
    python3 scripts/p66_ingest_decisions.py --db data/echr_search.db --discover-only
    python3 scripts/p66_ingest_decisions.py --db data/echr_search.db --also-key \\
            --out /tmp/p66_decisions.sql

Apply the SQL to the database the same way as the p60 output, then re-run
scripts/p29_extract_citations.py so the ``(dec.)`` references turn into links.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p60_monthly_update as p60  # noqa: E402

# HUDOC `doctypebranch` -> `originating_body` label used elsewhere in the corpus.
DECISION_BODY = {
    "DECGRANDCHAMBER": "Court (Grand Chamber)",
    "ADMISSIBILITY": "Court (Chamber)",
    "ADMISSIBILITYCOM": "Court (Committee)",
}

BASE_QUERY = ('contentsitename:ECHR AND languageisocode:"ENG" '
              'AND documentcollectionid2:"DECISIONS"')
BATCH = 25

_MONTHS = ("January|February|March|April|May|June|July|August|September|"
           "October|November|December")
_DATE = rf"(\d{{1,2}} (?:{_MONTHS}) \d{{4}})"
# "(dec.), no. 1234/05, 9 December 2004"  and the Polish style "(no. 1234/05 (dec.), …)".
DEC_BEFORE_RE = re.compile(
    r"\(dec\.\)(?:\s*\[GC\])?,?\s*(?:\(?nos?\.?\)?\s*)?(\d{3,6}/\d{2,4})(?:[^()]{0,40}?" + _DATE + ")?")
DEC_AFTER_RE = re.compile(r"(\d{3,6}/\d{2,4})\s*\(dec\.\)(?:[^()]{0,40}?" + _DATE + ")?")


def to_ddmmyyyy(text: str) -> str:
    return datetime.strptime(text, "%d %B %Y").strftime("%d/%m/%Y")


def cited_decisions(con: sqlite3.Connection) -> dict[str, dict]:
    """{appno: {"cited_by": n judgments, "dates": {dd/mm/yyyy: n}}}"""
    citing: dict[str, set] = defaultdict(set)
    dates: dict[str, Counter] = defaultdict(Counter)
    for case_id, text in con.execute(
            "SELECT case_id, text FROM paragraphs WHERE text LIKE '%(dec.)%'"):
        text = (text or "").replace("\xa0", " ")
        for rx in (DEC_BEFORE_RE, DEC_AFTER_RE):
            for m in rx.finditer(text):
                appno = m.group(1)
                citing[appno].add(case_id)
                if m.group(2):
                    try:
                        dates[appno][to_ddmmyyyy(m.group(2))] += 1
                    except ValueError:
                        pass
    return {a: {"cited_by": len(v), "dates": dict(dates[a])} for a, v in citing.items()}


def corpus_decisions(con: sqlite3.Connection) -> tuple[set[str], set[str]]:
    """(case_ids already in the corpus, application numbers that already have a Decision)"""
    ids, have = set(), set()
    for cid, case_no, dtype in con.execute("SELECT case_id, case_no, document_type FROM cases"):
        ids.add(cid)
        if (dtype or "").startswith("Decision"):
            have.update(p.strip() for p in re.split(r"[;,]\s*", case_no or "") if p.strip())
    return ids, have


def hudoc_query(query: str) -> list[dict]:
    rows, start, page = [], 0, 500
    while True:
        data = p60.hudoc_get({"query": query, "select": p60.META_SELECT,
                              "sort": "itemid Ascending", "start": str(start),
                              "length": str(page)})
        batch = data.get("results", [])
        rows += [r.get("columns", {}) for r in batch]
        start += page
        if not batch or start >= data.get("resultcount", 0):
            return rows


def discover_cited(cited: dict[str, dict], skip_ids: set[str]) -> tuple[dict[str, dict], list[str]]:
    """Return ({itemid: columns}, [application numbers HUDOC has no English decision for])."""
    appnos = sorted(cited)
    by_appno: dict[str, list[dict]] = defaultdict(list)
    for i in range(0, len(appnos), BATCH):
        part = appnos[i:i + BATCH]
        q = BASE_QUERY + " AND (" + " OR ".join(f'appno:"{a}"' for a in part) + ")"
        for cols in hudoc_query(q):
            for a in (cols.get("appno") or "").split(";"):
                if a.strip() in cited:
                    by_appno[a.strip()].append(cols)
        if (i // BATCH) % 20 == 0:
            print(f"  discovery {min(i + BATCH, len(appnos)):,}/{len(appnos):,}", flush=True)
        p60.time.sleep(0.3)
    chosen: dict[str, dict] = {}
    missing: list[str] = []
    for appno in appnos:
        docs = {d["itemid"]: d for d in by_appno.get(appno, []) if d["itemid"].startswith("001-")}
        if not docs:
            missing.append(appno)
            continue
        wanted = set(cited[appno]["dates"])
        matching = [d for d in docs.values() if p60._hudoc_date(d) in wanted] if wanted else []
        for d in (matching or list(docs.values())):
            if d["itemid"] not in skip_ids:
                chosen[d["itemid"]] = d
    return chosen, missing


def discover_key(skip_ids: set[str]) -> dict[str, dict]:
    q = BASE_QUERY + " AND (importance:1 OR importance:2)"
    return {d["itemid"]: d for d in hudoc_query(q)
            if d["itemid"].startswith("001-") and d["itemid"] not in skip_ids}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="corpus database (read-only use)")
    ap.add_argument("--out", default="/tmp/p66_decisions.sql")
    ap.add_argument("--rollback-out", default="")
    ap.add_argument("--report-out", default="", help="JSON report of what was found and not found")
    ap.add_argument("--also-key", action="store_true",
                    help="also ingest decisions HUDOC rates importance 1 or 2")
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--fetch-delay", type=float, default=0.5)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    existing_ids, have_dec = corpus_decisions(con)
    cited = cited_decisions(con)
    print(f"decisions cited in the corpus text: {len(cited):,}")
    cited = {a: v for a, v in cited.items() if a not in have_dec}
    print(f"  not yet in the corpus:            {len(cited):,}")

    chosen, missing = discover_cited(cited, existing_ids)
    print(f"HUDOC English decisions found:      {len(chosen):,}  (no English decision for {len(missing):,} numbers)")
    if args.also_key:
        key = discover_key(existing_ids)
        print(f"importance 1-2 decisions:           {len(key):,}  ({len(set(key) - set(chosen)):,} new)")
        chosen.update(key)

    skipped = Counter()
    todo = []
    for iid, cols in chosen.items():
        branch = (cols.get("doctypebranch") or "").upper()
        if branch not in DECISION_BODY:
            skipped[branch] += 1
            continue
        todo.append(cols)
    print(f"to ingest: {len(todo):,}   skipped by branch: {dict(skipped)}")
    print("branches:", dict(Counter((c.get('doctypebranch') or '').upper() for c in todo)))
    if args.report_out:
        Path(args.report_out).write_text(json.dumps(
            {"cited": len(cited), "found": len(chosen), "to_ingest": len(todo),
             "no_english_decision": missing, "skipped_branches": dict(skipped)}, indent=1))
    if args.discover_only:
        return 0
    if args.limit:
        todo = todo[:args.limit]

    import os
    os.environ["P34_FETCH_DELAY"] = str(args.fetch_delay)
    p34 = p60._load_module(p60.P34_PATH, "p34_rebuild_from_hudoc")
    build_db = p60._load_module(p60.BUILD_DB_PATH, "build_db")
    kpthes = json.loads(p60.KPTHESAURUS_PATH.read_text())

    def fetch_one(cols):
        cid = cols["itemid"]
        try:
            rows, _lang = p34.parse_docx(p34.fetch_docx(cid))
            return cid, cols, (rows or None), (None if rows else "no parsable paragraphs")
        except Exception as exc:                                   # noqa: BLE001
            return cid, cols, None, str(exc)[:140]

    forward, ok_ids, failures, n_paras = [], [], [], 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        for i, (cid, cols, rows, err) in enumerate(ex.map(fetch_one, todo), 1):
            if err:
                failures.append((cid, err))
            else:
                meta = p60.map_metadata(cols, kpthes, build_db)
                meta["document_type"] = "Decision"
                meta["originating_body"] = DECISION_BODY[(cols.get("doctypebranch") or "").upper()]
                forward += p60.emit_case(meta, rows, build_db, p34)
                ok_ids.append(cid)
                n_paras += sum(1 for r in rows if r.get("text"))
            if i % 50 == 0 or i == len(todo):
                print(f"  fetched {i:,}/{len(todo):,}  ok={len(ok_ids):,} failed={len(failures):,}", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("BEGIN;\n" + "\n".join(forward) + "\nCOMMIT;\n"
                   "INSERT INTO paragraphs_fts(paragraphs_fts) VALUES('optimize');\n")
    rb = Path(args.rollback_out or (str(out) + ".rollback"))
    rb.write_text("BEGIN;\n" + "\n".join(p60.emit_rollback(ok_ids, p34)) + "\nCOMMIT;\n")
    print()
    print("=" * 60)
    print(f"decisions built: {len(ok_ids):,}   paragraphs: {n_paras:,}   failures: {len(failures):,}")
    for cid, err in failures[:10]:
        print(f"  ! {cid}: {err}")
    print(f"forward SQL  -> {out}  ({out.stat().st_size:,} bytes)")
    print(f"rollback SQL -> {rb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
