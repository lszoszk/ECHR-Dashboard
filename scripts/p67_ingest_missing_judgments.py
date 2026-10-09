#!/usr/bin/env python3
"""
P67 — find the English judgments that HUDOC has and the corpus lacks, and build SQL for them.

p60_monthly_update.py only looks forward from the newest judgment in the corpus, so it never
sees older gaps. An audit on 2026-10-09 found 9,333 real English judgments in HUDOC (Chamber,
Committee, Grand Chamber; not press releases, translations or extracts) that the corpus did not
hold: importance 1: 15, 2: 151, 3: 1,883, 4: 7,284.

The script
  1. lists every English judgment in HUDOC, half a year at a time (one HUDOC query is capped at
     10,000 results), reusing p60_monthly_update.discover();
  2. drops what the corpus already has (``--existing``: a TSV whose first column is case_id);
  3. splits the rest into tranches by HUDOC importance, so the important ones can be loaded first:
     ``imp1-2``, ``imp3``, ``imp4`` (``--tranches`` chooses which to build);
  4. fetches and parses each DOCX with the p60 helpers and writes, per tranche, forward SQL and a
     rollback script: ``<prefix>_<tranche>.sql`` and ``<prefix>_<tranche>.sql.rollback``.

RESULT OF THE 2026-10-09 RUN: the premise that these documents can be fetched turned out to be
mostly false. Of the 166 importance 1-2 documents only 10 downloaded; of 320 sampled importance 3-4
documents none did (HTTP 500 from the DOCX service, 204 from the HTML and PDF services). HUDOC's own page
for such a record says the judgment is available in French only: the English-flagged record has no
English text. So most of the 9,333 are French-original judgments, not gaps in this corpus. The script is
still useful for ``--discover-only`` audits and for the occasional record whose DOCX appears later.

Documents HUDOC has not rendered yet (HTTP 500) are listed and simply left out; run again later.

Usage
-----
    python3 scripts/p67_ingest_missing_judgments.py --existing ids.tsv --discover-only
    python3 scripts/p67_ingest_missing_judgments.py --existing ids.tsv --out-prefix /tmp/p67 --tranches imp1-2,imp3

Load the SQL with scripts/apply_sql_batched.py (or deploy/load_sql_on_vm.sh), then re-run
scripts/p29_extract_citations.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p60_monthly_update as p60  # noqa: E402

TRANCHES = {
    "imp1-2": {"1", "2"},
    "imp3": {"3"},
    "imp4": {"4", "", "None"},
}
SKIP_TITLE = re.compile(r"translation|extracts?\b", re.IGNORECASE)


def list_hudoc_judgments(first_year: int, last_year: int) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for year in range(first_year, last_year + 1):
        for lo, hi in (("01-01", "06-30"), ("07-01", "12-31")):
            for cols in p60.discover(f"{year}-{lo}", f"{year}-{hi}"):
                found.setdefault(cols["itemid"], cols)
        if year % 5 == 0:
            print(f"  listed up to {year}: {len(found):,} judgments", flush=True)
    return found


def tranche_of(cols: dict) -> str:
    imp = str(cols.get("importance") or "").strip()
    for name, values in TRANCHES.items():
        if imp in values:
            return name
    return "imp4"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--existing", required=True, help="TSV with case_id in the first column")
    ap.add_argument("--out-prefix", default="/tmp/p67")
    ap.add_argument("--tranches", default="imp1-2,imp3,imp4")
    ap.add_argument("--first-year", type=int, default=1958)
    ap.add_argument("--last-year", type=int, default=2026)
    ap.add_argument("--ids-file", help="JSON list of HUDOC item ids to process as one tranche 'ids' "
                    "(skips the year-by-year listing; metadata is fetched by id)")
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="debug: cap documents per tranche")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--fetch-delay", type=float, default=0.4)
    args = ap.parse_args()

    existing = {line.split("\t")[0].strip() for line in Path(args.existing).read_text().splitlines() if line.strip()}
    print(f"corpus documents: {len(existing):,}")
    by_tranche: dict[str, list[dict]] = {t: [] for t in TRANCHES}
    if args.ids_file:
        wanted = [i for i in json.loads(Path(args.ids_file).read_text()) if i not in existing]
        rows: dict[str, dict] = {}
        for k in range(0, len(wanted), 25):
            chunk = wanted[k:k + 25]
            q = ('contentsitename:ECHR AND languageisocode:"ENG" AND documentcollectionid2:"JUDGMENTS" AND ('
                 + " OR ".join(f'itemid:"{i}"' for i in chunk) + ")")
            for cols in p60.hudoc_get({"query": q, "select": p60.META_SELECT, "sort": "itemid Ascending",
                                       "start": "0", "length": "100"}).get("results", []):
                rows[cols["columns"]["itemid"]] = cols["columns"]
            p60.time.sleep(0.3)
        by_tranche = {"ids": [rows[i] for i in wanted if i in rows]}
        print(f"requested {len(wanted):,} ids; metadata found for {len(by_tranche['ids']):,}")
        args.tranches = "ids"
    else:
        listed = list_hudoc_judgments(args.first_year, args.last_year)
        missing = [c for iid, c in listed.items()
                   if iid not in existing and not SKIP_TITLE.search(c.get("docname") or "")
                   and not (c.get("docname") or "").startswith("AFFAIRE")]
        print(f"HUDOC English judgments: {len(listed):,}; missing from the corpus: {len(missing):,}")
        for c in missing:
            by_tranche[tranche_of(c)].append(c)
    for t, rows in by_tranche.items():
        print(f"  {t:7s} {len(rows):6,}")
    Path(f"{args.out_prefix}_missing.json").write_text(
        json.dumps({t: [c["itemid"] for c in rows] for t, rows in by_tranche.items()}))
    if args.discover_only:
        return 0

    os.environ["P34_FETCH_DELAY"] = str(args.fetch_delay)
    p34 = p60._load_module(p60.P34_PATH, "p34_rebuild_from_hudoc")
    build_db = p60._load_module(p60.BUILD_DB_PATH, "build_db")
    kpthes = json.loads(p60.KPTHESAURUS_PATH.read_text())

    def fetch_one(cols):
        cid = cols["itemid"]
        try:
            rows, _lang = p34.parse_docx(p34.fetch_docx(cid))
            return cid, cols, (rows or None), (None if rows else "no parsable paragraphs")
        except Exception as exc:                                    # noqa: BLE001
            return cid, cols, None, str(exc)[:140]

    for name in [t.strip() for t in args.tranches.split(",") if t.strip()]:
        todo = by_tranche[name][:args.limit] if args.limit else by_tranche[name]
        print(f"\n== tranche {name}: {len(todo):,} documents", flush=True)
        forward, ok_ids, failures, n_paras = [], [], [], 0
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            for i, (cid, cols, rows, err) in enumerate(ex.map(fetch_one, todo), 1):
                if err:
                    failures.append((cid, err))
                else:
                    meta = p60.map_metadata(cols, kpthes, build_db)
                    forward += p60.emit_case(meta, rows, build_db, p34)
                    ok_ids.append(cid)
                    n_paras += sum(1 for r in rows if r.get("text"))
                if i % 100 == 0 or i == len(todo):
                    print(f"  {name}: {i:,}/{len(todo):,}  ok={len(ok_ids):,} failed={len(failures):,}", flush=True)
        out = Path(f"{args.out_prefix}_{name}.sql")
        out.write_text("BEGIN;\n" + "\n".join(forward) + "\nCOMMIT;\n"
                       "INSERT INTO paragraphs_fts(paragraphs_fts) VALUES('optimize');\n")
        Path(str(out) + ".rollback").write_text(
            "BEGIN;\n" + "\n".join(p60.emit_rollback(ok_ids, p34)) + "\nCOMMIT;\n")
        kinds = Counter("not rendered yet (HTTP 500)" if "500" in e else e[:40] for _, e in failures)
        print(f"  {name}: built {len(ok_ids):,} judgments, {n_paras:,} paragraphs; "
              f"failures {len(failures):,} {dict(kinds)}")
        print(f"  -> {out}  ({out.stat().st_size:,} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
