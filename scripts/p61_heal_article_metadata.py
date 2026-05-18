#!/usr/bin/env python3
"""P61 — heal contaminated article metadata.

~6,238 cases carry a legacy `case_articles` row that is a comma-mashed
compound string — e.g.

    "34, 366 § 1, 358, 362, 366, 6, 13, 35 § 3, 6 § 1, 35"

— mixing real Convention articles (6, 6-1, 34, 35, 41) with non-ECHR
numbers (domestic-law article numbers, paragraph references: 358, 366,
617 …).  Two faults combined: the original scrape captured article-like
numbers from the wrong place, and build_db.py's _normalize_articles only
splits on ';' and '+' (never ','), so the whole blob became one row.

Effect: the /api/facets article rail surfaces ~1,000 artefact "articles",
and a contaminated case is not reliably found by its real article filter.

This pass re-fetches HUDOC's clean `article` metadata field (machine
format: "6;6-1;P1-1") for the affected cases and rebuilds their
case_articles rows — properly split and normalised via the same
_normalize_articles helper build_db uses for clean cases.

Runs LOCALLY (HUDOC query API only — no DOCX).  Emits transactional SQL
applied to the VM database; also emits a rollback SQL.

Input: a JSONL of `{"case_id": ..., "article": ...}` — the contaminated
case_articles rows, dumped from the VM (JSONL, not TSV, because the
contaminated values contain embedded newlines):

    SELECT case_id, article FROM case_articles WHERE article LIKE '%,%'

Usage
-----
    python3 scripts/p61_heal_article_metadata.py \\
        --contaminated /tmp/p61_contaminated.jsonl --out /tmp/p61_articles.sql
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
BUILD_DB_PATH = REPO / "backend" / "build_db.py"

HUDOC_QUERY_URL = "https://hudoc.echr.coe.int/app/query/results"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_SSL = ssl._create_unverified_context()
BATCH = 50


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sql_str(s) -> str:
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def hudoc_articles(itemids: list[str]) -> dict[str, str]:
    """Return {itemid: raw article string} from HUDOC for the given ids."""
    out: dict[str, str] = {}
    for i in range(0, len(itemids), BATCH):
        chunk = itemids[i:i + BATCH]
        q = ("contentsitename:ECHR AND ("
             + " OR ".join(f'itemid:"{x}"' for x in chunk) + ")")
        url = HUDOC_QUERY_URL + "?" + urllib.parse.urlencode({
            "query": q, "select": "itemid,article",
            "sort": "itemid Ascending", "start": "0",
            "length": str(len(chunk)),
        })
        data = {"results": []}
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": UA,
                    "Referer": "https://hudoc.echr.coe.int/"})
                with urllib.request.urlopen(req, context=_SSL,
                                            timeout=60) as r:
                    data = json.loads(r.read().decode())
                break
            except Exception as exc:                   # noqa: BLE001
                if attempt == 3:
                    print(f"  ! batch at {i} failed: {exc}", file=sys.stderr)
                else:
                    time.sleep(2 * (attempt + 1))
        for res in data.get("results", []):
            c = res.get("columns", {})
            out[c.get("itemid", "")] = c.get("article", "") or ""
        print(f"  HUDOC fetched {min(i + BATCH, len(itemids))}/{len(itemids)}")
        time.sleep(0.4)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contaminated", required=True,
                    help="JSONL: {\"case_id\": ..., \"article\": ...} per line")
    ap.add_argument("--out", default="/tmp/p61_articles.sql")
    ap.add_argument("--rollback-out",
                    help="rollback SQL path (default: <out>.rollback)")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap cases processed (debug)")
    ap.add_argument("--apply-to",
                    help="also executescript the forward SQL into this DB "
                         "(local testing / direct apply)")
    args = ap.parse_args()

    path = Path(args.contaminated)
    if not path.exists():
        print(f"ERROR: --contaminated not found: {path}", file=sys.stderr)
        return 2

    build_db = _load_module(BUILD_DB_PATH, "build_db")

    # case_id -> list of current (contaminated) article values
    old: dict[str, list[str]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        old.setdefault(rec["case_id"], []).append(rec.get("article") or "")
    ids = sorted(old)
    if args.limit:
        ids = ids[:args.limit]
    print(f"contaminated cases: {len(ids):,}")

    fetched = hudoc_articles(ids)
    print(f"HUDOC returned article metadata for {len(fetched):,} cases")

    forward: list[str] = []
    rollback: list[str] = []
    healed = healed_empty = missing = 0
    examples: list[tuple] = []
    for cid in ids:
        if cid not in fetched:
            missing += 1
            continue
        clean = build_db._normalize_articles(fetched[cid])
        forward.append(f"DELETE FROM case_articles WHERE case_id={sql_str(cid)};")
        for art in clean:
            forward.append("INSERT INTO case_articles (case_id, article) "
                            f"VALUES ({sql_str(cid)}, {sql_str(art)});")
        rollback.append(f"DELETE FROM case_articles WHERE case_id={sql_str(cid)};")
        for art in old[cid]:
            rollback.append("INSERT INTO case_articles (case_id, article) "
                             f"VALUES ({sql_str(cid)}, {sql_str(art)});")
        if clean:
            healed += 1
            if len(examples) < 6:
                examples.append((cid, old[cid][0][:54], clean))
        else:
            healed_empty += 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("BEGIN;\n" + "\n".join(forward) + "\nCOMMIT;\n")
    rb_path = Path(args.rollback_out or (str(out_path) + ".rollback"))
    rb_path.write_text("BEGIN;\n" + "\n".join(rollback) + "\nCOMMIT;\n")

    print()
    print("=" * 60)
    print(f"healed (>=1 clean article): {healed:,}")
    print(f"healed to empty (HUDOC lists no article): {healed_empty:,}")
    print(f"missing from HUDOC (left untouched): {missing:,}")
    print(f"forward SQL  -> {out_path}  ({out_path.stat().st_size:,} bytes)")
    print(f"rollback SQL -> {rb_path}")
    print("\nexamples (contaminated -> clean):")
    for cid, before, after in examples:
        print(f"  {cid}: {before!r}")
        print(f"       -> {after}")

    if args.apply_to:
        db = Path(args.apply_to)
        print(f"\napplying forward SQL to {db} ...")
        con = sqlite3.connect(db)
        try:
            con.executescript(out_path.read_text())
            con.commit()
            n = con.execute("SELECT COUNT(*) FROM case_articles").fetchone()[0]
            print(f"  done — case_articles now holds {n:,} rows")
        finally:
            con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
