#!/usr/bin/env python3
"""Re-scrape HUDOC API to fill sparse metadata fields in the ECHR dataset.

Queries the HUDOC API in batches of 500, fetches structured metadata fields
that are richer than what our original scrape captured, and merges them into
the enriched JSONL.

Fields fetched:
  scl              → strasbourg_caselaw (if currently empty)
  violation        → violation (if currently empty)
  nonviolation     → non-violation (if currently empty)
  representedby    → represented_by (if currently empty)
  kpthesaurus      → hudoc_kpthesaurus (new field, always written)
  conclusion       → conclusion (if currently empty)
  applicability    → applicability (if currently empty)
  rulesofcourt     → rules_of_court (if currently empty)
  externalsources  → external_sources (new field, always written)

Original non-empty values are NEVER overwritten. HUDOC data is only used
to fill gaps.
"""

from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


HUDOC_URL = "https://hudoc.echr.coe.int/app/query/results"
BATCH_SIZE = 500
SELECT_FIELDS = (
    "itemid,docname,appno,scl,representedby,kpthesaurus,"
    "violation,nonviolation,conclusion,article,respondent,"
    "importance,rulesofcourt,applicability,externalsources"
)
# Include both judgments and other document types
QUERY_ALL = 'contentsitename:ECHR'
QUERY_JUDGMENTS = 'contentsitename:ECHR AND (documentcollectionid2:"JUDGMENTS")'


def create_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_batch(start: int, length: int, query: str, ctx) -> dict:
    """Fetch a batch of results from the HUDOC API."""
    params = urllib.parse.urlencode({
        "query": query,
        "select": SELECT_FIELDS,
        "sort": "itemid Ascending",
        "start": str(start),
        "length": str(length),
    })
    url = f"{HUDOC_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "ECHR-Dashboard/1.0"})
    resp = urllib.request.urlopen(req, timeout=60, context=ctx)
    return json.loads(resp.read())


def fetch_year(year: int, ctx) -> dict[str, dict]:
    """Fetch all judgments for a single year (avoids 10K result limit)."""
    base_query = (
        f'contentsitename:ECHR AND (documentcollectionid2:"JUDGMENTS")'
        f' AND (kpdate>="{year}-01-01T00:00:00.0Z"'
        f' AND kpdate<="{year}-12-31T00:00:00.0Z")'
    )
    index = {}
    start = 0
    while True:
        data = fetch_batch(start, BATCH_SIZE, base_query, ctx)
        for result in data.get("results", []):
            cols = result.get("columns", {})
            itemid = cols.get("itemid", "")
            if itemid:
                index[itemid] = cols
        if not data.get("results") or start + BATCH_SIZE >= data.get("resultcount", 0):
            break
        start += BATCH_SIZE
        time.sleep(0.2)
    return index


def fetch_all_metadata(query: str) -> dict[str, dict]:
    """Fetch all HUDOC judgment metadata year by year.

    HUDOC API limits results to 10K per query, so we query each year
    separately (max ~2K-3K judgments per year) to stay well under the limit.
    """
    ctx = create_ssl_context()

    # Also fetch non-judgment documents (decisions, etc.) that might
    # match our dataset — use a broader query for recent years
    index = {}
    # ECHR judgments span 1959 to present
    current_year = 2026
    years = list(range(1959, current_year + 1))

    print(f"  Fetching judgments year by year ({years[0]}–{years[-1]}) ...")
    for year in years:
        try:
            year_data = fetch_year(year, ctx)
        except Exception as e:
            print(f"\n  ERROR year {year}: {e}. Retrying in 5s...")
            time.sleep(5)
            try:
                year_data = fetch_year(year, ctx)
            except Exception as e2:
                print(f"\n  RETRY FAILED year {year}: {e2}. Skipping.")
                continue

        index.update(year_data)
        if year_data:
            print(f"  {year}: {len(year_data):>5,} judgments  (total: {len(index):,})")
        time.sleep(0.1)

    print(f"\n  Done: {len(index):,} records indexed by itemid")
    return index


def parse_semicolon_list(value: str) -> list[str]:
    """Split semicolon-separated HUDOC field into list."""
    if not value or not value.strip():
        return []
    return [x.strip() for x in value.split(";") if x.strip()]


def is_empty(value) -> bool:
    """Check if a field value is effectively empty."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def merge(input_path: Path, output_path: Path, hudoc_index: dict[str, dict]):
    """Merge HUDOC metadata into the enriched JSONL."""
    total = 0
    matched = 0
    fills = {
        "violation": 0,
        "non-violation": 0,
        "represented_by": 0,
        "strasbourg_caselaw": 0,
        "conclusion": 0,
        "applicability": 0,
        "rules_of_court": 0,
        "kpthesaurus": 0,
        "external_sources": 0,
    }

    with input_path.open("r", encoding="utf-8") as fin, \
         output_path.open("w", encoding="utf-8") as fout:

        for line in fin:
            line = line.strip()
            if not line:
                continue
            total += 1
            case = json.loads(line)
            case_id = str(case.get("case_id") or "").strip()

            # Match by case_id (= HUDOC itemid)
            hudoc = hudoc_index.get(case_id)
            if hudoc:
                matched += 1

                # violation
                if is_empty(case.get("violation")):
                    v = parse_semicolon_list(hudoc.get("violation", ""))
                    if v:
                        case["violation"] = v
                        fills["violation"] += 1

                # non-violation
                if is_empty(case.get("non-violation")):
                    nv = parse_semicolon_list(hudoc.get("nonviolation", ""))
                    if nv:
                        case["non-violation"] = nv
                        fills["non-violation"] += 1

                # represented_by
                if is_empty(case.get("represented_by")):
                    rep = str(hudoc.get("representedby") or "").strip()
                    if rep:
                        case["represented_by"] = rep
                        fills["represented_by"] += 1

                # strasbourg_caselaw
                if is_empty(case.get("strasbourg_caselaw")):
                    scl = parse_semicolon_list(hudoc.get("scl", ""))
                    if scl:
                        case["strasbourg_caselaw"] = scl
                        fills["strasbourg_caselaw"] += 1

                # conclusion
                if is_empty(case.get("conclusion")):
                    conc = str(hudoc.get("conclusion") or "").strip()
                    if conc:
                        case["conclusion"] = conc
                        fills["conclusion"] += 1

                # applicability
                if is_empty(case.get("applicability")):
                    app = parse_semicolon_list(hudoc.get("applicability", ""))
                    if app:
                        case["applicability"] = app
                        fills["applicability"] += 1

                # rules_of_court
                if is_empty(case.get("rules_of_court")):
                    roc = str(hudoc.get("rulesofcourt") or "").strip()
                    if roc:
                        case["rules_of_court"] = roc
                        fills["rules_of_court"] += 1

                # Always write new fields
                kpt = str(hudoc.get("kpthesaurus") or "").strip()
                if kpt:
                    case["hudoc_kpthesaurus"] = kpt
                    fills["kpthesaurus"] += 1

                ext = str(hudoc.get("externalsources") or "").strip()
                if ext:
                    case["external_sources"] = ext
                    fills["external_sources"] += 1

            fout.write(json.dumps(case, ensure_ascii=False) + "\n")

    print()
    print("=" * 65)
    print(f"  Total records:          {total:>10,}")
    print(f"  Matched to HUDOC:       {matched:>10,}  ({matched/total*100:.1f}%)")
    print(f"  ---")
    print(f"  Fields filled from HUDOC:")
    for field, count in fills.items():
        print(f"    {field:<25s} {count:>8,}")
    print("=" * 65)
    print(f"\n  Output: {output_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default="docs/data/echr_cases_enriched.jsonl",
                        help="Input JSONL (will NOT be modified)")
    parser.add_argument("--output", default="docs/data/echr_cases_enriched.jsonl",
                        help="Output JSONL (can be same as input to update in-place)")
    parser.add_argument("--query", default=QUERY_ALL,
                        help="HUDOC query filter")
    parser.add_argument("--cache", default="docs/data/hudoc_metadata_cache.json",
                        help="Path to cache HUDOC responses (skip re-download)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    def resolve(p):
        pp = Path(p).expanduser()
        return pp if pp.is_absolute() else (repo_root / pp).resolve()

    input_path = resolve(args.input)
    output_path = resolve(args.output)
    cache_path = resolve(args.cache)

    if not input_path.exists():
        print(f"ERROR: Input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load or fetch HUDOC metadata
    if cache_path.exists():
        print(f"Loading cached HUDOC metadata from {cache_path} ...")
        hudoc_index = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"  Loaded {len(hudoc_index):,} records from cache")
    else:
        print("Fetching metadata from HUDOC API ...")
        hudoc_index = fetch_all_metadata(args.query)
        # Cache for reuse
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(hudoc_index, ensure_ascii=False), encoding="utf-8")
        print(f"  Cached to {cache_path}")

    merge(input_path, output_path, hudoc_index)


if __name__ == "__main__":
    main()
