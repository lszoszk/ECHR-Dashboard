#!/usr/bin/env bash
#
# rebuild_stats.sh — regenerate docs/data/stats.json from the live corpus.
#
#   ./scripts/rebuild_stats.sh              # full rebuild, fresh HUDOC pull
#   ./scripts/rebuild_stats.sh --no-refetch # reuse the last HUDOC cache (faster)
#
# The Statistics page is a STATIC build. Nothing regenerates it when the
# database changes, so it must be re-run after every corpus update.
#
# WHY THE ORDER MATTERS — getting it wrong produces no error, just silent
# data loss. The database is authoritative for paragraphs and sections, but
# seven HUDOC metadata fields exist ONLY in the JSONL exports and drive whole
# page sections (hudoc_kpthesaurus -> the four Thesaurus charts, pcr_citations
# -> the citation network, chamber_composed_of -> judge counts, and the
# domestic_law / international_law / rules_of_court / separate_opinion KPI
# tiles). merge_ecthr_pcr OVERWRITES pcr_*, and the current public snapshot of
# ECTHR-PCR is thinner than the one merged in April: running the archive merge
# LAST silently dropped 782 cases and 18,847 citation edges when this was first
# assembled. So: live sources first, archive only to fill what they leave empty.
#
#   1. p67  export the corpus from the DB (streamed over SSH, nothing written
#           to the VM, whose disk sits at ~90%)
#   2.      hudoc_rescrape — live HUDOC metadata. NOTE: this script skips the
#           network entirely if its cache file exists, so a fresh path is used
#           unless --no-refetch is passed. Without that, a "refresh" silently
#           re-merges months-old data.
#   3.      merge_ecthr_pcr — live citation graph
#   4. p68  --fill-only — backfill ONLY what the live sources left empty
#   5.      build_pages_dashboard + build_citation_analytics
#
# Paragraph text is not shipped by p67 (build_pages_dashboard only tests it for
# emptiness), so the intermediate JSONL is ~250 MB rather than ~2 GB. That also
# makes it unusable for --export-data / --sample-output, which are pointed at
# throwaway paths below — do NOT repoint them at docs/data/.
set -euo pipefail

VM="${ECHR_VM:-amuvmuser@150.254.115.204}"
CONTAINER="${ECHR_CONTAINER:-echr-api}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
WORK="${ECHR_WORK:-/tmp/echr_stats_rebuild}"
STAMP="$(date +%Y%m%d)"
mkdir -p "$WORK"

ARCHIVE="$REPO/docs/data/echr_cases_enriched_final.jsonl"
CACHE="$WORK/hudoc_cache_$STAMP.json"
[ "${1:-}" = "--no-refetch" ] && CACHE="$WORK/hudoc_cache_latest.json"

if [ ! -f "$ARCHIVE" ]; then
    echo "ERROR: HUDOC metadata archive not found: $ARCHIVE" >&2
    echo "It is git-ignored (~1 GB) and is required for the thesaurus and" >&2
    echo "citation blocks. Without it those charts render empty." >&2
    exit 1
fi

echo "=== [1/5] exporting the corpus from the live DB ==="
ssh "$VM" "docker exec -i $CONTAINER python3 -" \
    < "$SCRIPT_DIR/p67_export_db_cases.py" > "$WORK/a.jsonl"
wc -l < "$WORK/a.jsonl" | xargs printf "    %s cases exported\n"

echo "=== [2/5] live HUDOC metadata (thesaurus, scl) ==="
python3 "$SCRIPT_DIR/hudoc_rescrape.py" \
    --input "$WORK/a.jsonl" --output "$WORK/b.jsonl" --cache "$CACHE" \
    | tail -14

echo "=== [3/5] live citation graph (ECTHR-PCR) ==="
python3 "$SCRIPT_DIR/merge_ecthr_pcr.py" \
    --input "$WORK/b.jsonl" --output "$WORK/c.jsonl" | tail -8

echo "=== [4/5] backfilling gaps from the archive (never overwriting) ==="
python3 "$SCRIPT_DIR/p68_merge_hudoc_metadata.py" \
    --meta "$ARCHIVE" --fill-only \
    < "$WORK/c.jsonl" > "$WORK/echr_cases_enriched_$STAMP.jsonl"

echo "=== [5/5] rebuilding stats.json ==="
python3 "$SCRIPT_DIR/build_pages_dashboard.py" \
    --input "$WORK/echr_cases_enriched_$STAMP.jsonl" \
    --output "$REPO/docs/data/stats.json" \
    --export-data "$WORK/discard_cases.jsonl" \
    --sample-output "$WORK/discard_sample.jsonl" | head -2
python3 "$SCRIPT_DIR/build_citation_analytics.py" \
    --input "$WORK/echr_cases_enriched_$STAMP.jsonl" \
    --stats "$REPO/docs/data/stats.json" | grep -E "Nodes|landmark" || true

echo
echo "Done. Commit docs/data/stats.json to publish it."
