#!/usr/bin/env bash
#
# sync_metadata_on_vm.sh — apply HUDOC's "Case details" metadata (fetched locally with
# scripts/p69_sync_hudoc_metadata.py fetch) to the production database.
#
#   ./deploy/sync_metadata_on_vm.sh /path/to/hudoc_metadata.json            # report only
#   ./deploy/sync_metadata_on_vm.sh /path/to/hudoc_metadata.json --apply    # write
#
# --apply replaces violation / non_violation with HUDOC's lists (our originals are kept, once, in
# outcome_backup_p69), stores every HUDOC field in hudoc_metadata and fills the strasbourg_caselaw,
# domestic_law, international_law and rules_of_court columns, which the API serves as soon as they
# exist. Rollback of the outcome columns: see the docstring of scripts/p69_sync_hudoc_metadata.py.
# Every write invalidates the API's cached facets: run deploy/demo_prewarm.sh afterwards.
set -euo pipefail

META="${1:?usage: sync_metadata_on_vm.sh META.json [--apply]}"
MODE="${2:-}"
[ -f "${META}" ] || { echo "no such file: ${META}" >&2; exit 2; }

HOST="${VM_HOST:-amuvmuser@150.254.115.204}"
CONTAINER="${CONTAINER:-echr-api}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH=(ssh -o BatchMode=yes "${HOST}")

scp -q -o BatchMode=yes "${META}" "${HOST}:/tmp/hudoc_metadata.json"
scp -q -o BatchMode=yes "${ROOT}/scripts/p69_sync_hudoc_metadata.py" "${HOST}:/tmp/p69_sync_hudoc_metadata.py"
"${SSH[@]}" "docker cp /tmp/hudoc_metadata.json ${CONTAINER}:/tmp/hudoc_metadata.json && \
  docker cp /tmp/p69_sync_hudoc_metadata.py ${CONTAINER}:/tmp/p69_sync_hudoc_metadata.py && \
  rm -f /tmp/hudoc_metadata.json /tmp/p69_sync_hudoc_metadata.py"
"${SSH[@]}" "docker exec ${CONTAINER} python3 /tmp/p69_sync_hudoc_metadata.py apply --db /data/echr_search.db --meta /tmp/hudoc_metadata.json ${MODE}"
"${SSH[@]}" "docker exec ${CONTAINER} rm -f /tmp/hudoc_metadata.json"
[ "${MODE}" = "--apply" ] && echo "Next: ./deploy/demo_prewarm.sh" || echo "(report only; add --apply to change the database)"
