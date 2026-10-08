#!/usr/bin/env python3
"""P68 — merge HUDOC metadata into the DB export, producing the generator's input.

Second half of the full Statistics regeneration (see `p67_export_db_cases.py`).

The database is authoritative for everything it stores — paragraphs, sections,
articles, outcomes — because it is the copy the cleaning passes healed. But
seven fields exist only in the enriched HUDOC export and drive whole sections
of the Statistics page:

    hudoc_kpthesaurus     the entire Thesaurus analytics block (4 charts)
    strasbourg_caselaw    precedent / citation analytics
    chamber_composed_of   judge counts
    separate_opinion      separate-opinion breakdowns
    domestic_law          \\
    international_law      >  "cases citing …" KPI tiles
    rules_of_court        /

This joins them onto the DB stream by `case_id` and reports coverage, so a
field that silently went missing shows up as a number rather than as an empty
chart.

Reads the DB export on stdin, writes the merged JSONL to stdout, coverage to
stderr.

ORDER MATTERS. The archive must never overwrite a live pull. `merge_ecthr_pcr.py`
overwrites `pcr_*`, and today's snapshot of the public ECTHR-PCR dataset is
thinner than the one merged in April — running it after this script silently
dropped 782 cases and 18,847 citation edges. So run the live sources first and
use `--fill-only` here to patch what they leave empty:

  # 1. corpus out of the DB
  ssh amuvmuser@… 'docker exec -i echr-api python3 -' < scripts/p67_export_db_cases.py > a.jsonl
  # 2. live HUDOC metadata (point --cache at a NEW file, or it never hits the network)
  python3 scripts/hudoc_rescrape.py --input a.jsonl --output b.jsonl --cache fresh_cache.json
  # 3. live citation graph
  python3 scripts/merge_ecthr_pcr.py --input b.jsonl --output c.jsonl
  # 4. backfill only what is still missing, from the archived export
  python3 scripts/p68_merge_hudoc_metadata.py --meta docs/data/echr_cases_enriched_final.jsonl \\
      --fill-only < c.jsonl > echr_cases_enriched_<date>.jsonl
  # 5. rebuild
  python3 scripts/build_pages_dashboard.py --input echr_cases_enriched_<date>.jsonl \\
      --output docs/data/stats.json --export-data /tmp/x --sample-output /tmp/y
  python3 scripts/build_citation_analytics.py --input echr_cases_enriched_<date>.jsonl \\
      --stats docs/data/stats.json

Without --fill-only this script overwrites, which is correct only when it is
the *sole* source of these fields (as in the first pass, straight after p67).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

# Only these come from the HUDOC export. Everything else is the DB's.
META_FIELDS = [
    "hudoc_kpthesaurus",
    "strasbourg_caselaw",
    "chamber_composed_of",
    "separate_opinion",
    "domestic_law",
    "international_law",
    "rules_of_court",
    # Consumed by scripts/build_citation_analytics.py, which merges the
    # `citation_network` block into stats.json in a second pass. Omitting these
    # does not error — it silently produces an empty citation_network and an
    # empty "Citation Landmarks" chart, which is how they were missed the
    # first time this ran.
    "pcr_citations",
    "pcr_cited_by",
    "pcr_citation_count",
    "pcr_cited_by_count",
    "pcr_matched",
    "resolved_citations",
    "resolved_citation_count",
    "resolution_rate",
    "external_sources",
]


def load_meta(path):
    meta = {}
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            n += 1
            c = json.loads(line)
            cid = c.get("case_id")
            if not cid:
                continue
            meta[cid] = {k: c[k] for k in META_FIELDS if k in c}
    print(f"[p68] metadata index: {len(meta):,} cases from {n:,} records",
          file=sys.stderr)
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--meta", required=True, help="enriched HUDOC JSONL export")
    ap.add_argument("--fill-only", action="store_true",
                    help="only set fields that are missing/empty on the input; "
                         "never overwrite a value already there")
    args = ap.parse_args()

    meta = load_meta(args.meta)

    matched = 0
    unmatched = 0
    filled = Counter()
    kept = Counter()
    total = 0
    out = sys.stdout

    for line in sys.stdin:
        if not line.strip():
            continue
        total += 1
        case = json.loads(line)
        m = meta.get(case.get("case_id"))
        if m:
            matched += 1
            for k, v in m.items():
                if args.fill_only and case.get(k) not in (None, "", [], {}, False):
                    kept[k] += 1          # live source already supplied it
                    continue
                case[k] = v
                if v not in (None, "", [], {}, False):
                    filled[k] += 1
        else:
            unmatched += 1
        out.write(json.dumps(case, ensure_ascii=False) + "\n")

    if args.fill_only:
        print("[p68] --fill-only: values kept from the live sources:",
              file=sys.stderr)
        for k in META_FIELDS:
            if kept[k]:
                print(f"[p68]     {k:26s} {kept[k]:>7,}", file=sys.stderr)

    print(f"[p68] {total:,} cases written", file=sys.stderr)
    print(f"[p68]   metadata matched  : {matched:,} "
          f"({100.0 * matched / max(1, total):.1f}%)", file=sys.stderr)
    print(f"[p68]   no metadata row   : {unmatched:,} "
          f"(newer than the HUDOC export — their thesaurus/citation "
          f"fields will be empty)", file=sys.stderr)
    print("[p68]   non-empty per field:", file=sys.stderr)
    for k in META_FIELDS:
        print(f"[p68]     {k:22s} {filled[k]:>7,}", file=sys.stderr)


if __name__ == "__main__":
    main()
