#!/usr/bin/env bash
#
# dedupe_on_vm.sh — repair a forward SQL file that was loaded twice on the production database.
#
#   ./deploy/dedupe_on_vm.sh /path/to/file.sql            # report only; changes nothing
#   ./deploy/dedupe_on_vm.sh /path/to/file.sql --apply    # delete the second copy of each paragraph
#
# Loading the same file twice leaves every case in it with doubled paragraphs (the case row is
# ignored the second time, its paragraphs are not). scripts/dedupe_loaded_paragraphs.py compares each
# case with the file, deletes only the later copy of identical rows, verifies every case is back to
# the file's count (rolls back otherwise) and checkpoints the write-ahead log.
#
# Afterwards: ./deploy/rebuild_citations.sh --apply  (citations were built from the doubled rows).
# scripts/apply_sql_batched.py now skips cases that are already present, so this cannot recur.
set -euo pipefail

SQL="${1:?usage: dedupe_on_vm.sh FILE.sql [--apply]}"
MODE="${2:-}"
[ -f "${SQL}" ] || { echo "no such file: ${SQL}" >&2; exit 2; }

HOST="${VM_HOST:-amuvmuser@150.254.115.204}"
CONTAINER="${CONTAINER:-echr-api}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="$(basename "${SQL}")"
SSH=(ssh -o BatchMode=yes "${HOST}")

scp -q -o BatchMode=yes "${SQL}" "${ROOT}/scripts/dedupe_loaded_paragraphs.py" "${HOST}:/tmp/"
"${SSH[@]}" "docker cp /tmp/${NAME} ${CONTAINER}:/tmp/${NAME} && \
  docker cp /tmp/dedupe_loaded_paragraphs.py ${CONTAINER}:/tmp/dedupe_loaded_paragraphs.py && \
  rm -f /tmp/${NAME} /tmp/dedupe_loaded_paragraphs.py"
"${SSH[@]}" "docker exec ${CONTAINER} python3 /tmp/dedupe_loaded_paragraphs.py --db /data/echr_search.db --sql /tmp/${NAME} ${MODE}"
"${SSH[@]}" "docker exec ${CONTAINER} rm -f /tmp/${NAME}"
[ "${MODE}" = "--apply" ] && echo "Next: ./deploy/rebuild_citations.sh --apply" || echo "(report only; add --apply to change the database)"
