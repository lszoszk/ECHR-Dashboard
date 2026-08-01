#!/usr/bin/env python3
"""P66 — refresh the section figures in docs/data/stats.json from the live DB.

The Statistics page ("Paragraph Distribution" chart, `sectionsChart`) renders
`rankings.sections` from the STATIC docs/data/stats.json, which was generated on
2026-04-16 from a JSONL export. After P63/P64 that block still advertised the
retired labels — `Facts (Proceedings)` 433,699, `facts` 247,480,
`Facts (Background)` 19,099 — so the public chart described a corpus that no
longer exists.

This refreshes ONLY the figures that are (a) invalidated by the Phase 2 split
and (b) computable exactly from the database:

    rankings.sections           paragraph counts per section label
    summary.total_cases
    summary.total_paragraphs
    summary.{avg,median,p90,min,max}_paragraphs_per_case

Everything else in stats.json — yearly series, cross-tabs, thesaurus and
citation analytics — is still the April snapshot and needs a full pipeline
regeneration (`build_pages_dashboard.py`, which reads a JSONL export rather
than the DB). This script deliberately does NOT touch those, and records what
it refreshed in `stats.json` under `partial_refresh` so the staleness is
visible rather than implied.

Two-step, because the DB lives on the VM and the JSON lives in the repo:

  # 1. on the VM — emit the fragment
  ssh amuvmuser@… 'docker exec -i echr-api python3 -' --emit < p66_refresh_stats_sections.py > frag.json

  # 2. locally — patch the file
  python3 scripts/p66_refresh_stats_sections.py --patch docs/data/stats.json < frag.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

DB = os.environ.get("ECHR_DB_PATH", "/data/echr_search.db")

# Sections that are document furniture rather than judgment prose. The April
# file included them, so they are kept for comparability, but flagged.
FURNITURE = {"Header", "Appendix", "Summary"}


def emit():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = conn.cursor()

    sections = [[s, n] for s, n in cur.execute(
        "SELECT section, COUNT(*) c FROM paragraphs "
        "WHERE section IS NOT NULL AND section <> '' GROUP BY 1 ORDER BY c DESC")]

    cur.execute("SELECT COUNT(*) FROM paragraphs")
    total_paragraphs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM cases")
    total_cases = cur.fetchone()[0]

    per_case = [n for (n,) in cur.execute(
        "SELECT COUNT(*) FROM paragraphs GROUP BY case_id")]
    per_case.sort()

    def q(frac):
        return per_case[min(len(per_case) - 1, int(frac * len(per_case)))]

    frag = {
        "rankings.sections": sections,
        "summary": {
            "total_cases": total_cases,
            "total_paragraphs": total_paragraphs,
            "avg_paragraphs_per_case": round(total_paragraphs / max(1, len(per_case)), 1),
            "median_paragraphs_per_case": q(0.50),
            "p90_paragraphs_per_case": q(0.90),
            "min_paragraphs_per_case": per_case[0] if per_case else 0,
            "max_paragraphs_per_case": per_case[-1] if per_case else 0,
        },
        "furniture_sections": sorted(FURNITURE),
    }
    json.dump(frag, sys.stdout, indent=1)
    print()


def patch(path):
    frag = json.load(sys.stdin)
    with open(path) as f:
        stats = json.load(f)

    before_sections = stats.get("rankings", {}).get("sections", [])
    before_summary = {k: stats.get("summary", {}).get(k) for k in frag["summary"]}

    stats.setdefault("rankings", {})["sections"] = frag["rankings.sections"]
    stats.setdefault("summary", {}).update(frag["summary"])
    stats["partial_refresh"] = {
        "refreshed": ["rankings.sections", *("summary." + k for k in frag["summary"])],
        "source": "live production DB (P66)",
        "note": ("Only the section figures and corpus totals were refreshed. "
                 "Yearly series, cross-tabs, thesaurus and citation analytics "
                 "remain from the generated_at snapshot and require a full "
                 "build_pages_dashboard.py regeneration."),
    }

    # Match the generator's formatting (2-space indent). Writing compact JSON
    # here would collapse a 17k-line file to one line and turn every future
    # diff of this file into an unreviewable rewrite.
    with open(path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("patched %s" % path)
    print("\n--- summary ---")
    for k, v in frag["summary"].items():
        print("  %-32s %14s -> %s" % (k, before_summary.get(k), v))
    print("\n--- rankings.sections ---")
    print("  before (%d labels):" % len(before_sections))
    for s, n in before_sections[:6]:
        print("      %-28s %10s" % (s, format(n, ",")))
    print("  after (%d labels):" % len(frag["rankings.sections"]))
    for s, n in frag["rankings.sections"]:
        tag = "  (furniture)" if s in FURNITURE else ""
        print("      %-28s %10s%s" % (s, format(n, ","), tag))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--emit", action="store_true", help="print the fragment (run on the VM)")
    ap.add_argument("--patch", metavar="STATS_JSON", help="patch this file from stdin")
    args = ap.parse_args()
    if args.emit:
        emit()
    elif args.patch:
        patch(args.patch)
    else:
        ap.error("one of --emit / --patch is required")


if __name__ == "__main__":
    main()
