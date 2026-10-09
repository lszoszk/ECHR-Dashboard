#!/usr/bin/env bash
#
# load_sql_on_vm.sh — apply a forward SQL file (the output of p60_monthly_update.py or
# p66_ingest_decisions.py) to the production database in small transactions, and keep
# the rollback file on the VM.
#
#   ./deploy/load_sql_on_vm.sh /path/to/p66_decisions.sql
#
# The rollback file must sit next to the forward file as <name>.sql.rollback; it is copied
# to /home/amuvmuser/echr/ with the forward file. To undo a load, run that file inside the
# container:
#   docker exec echr-api python3 -c "import sqlite3; sqlite3.connect('/data/echr_search.db',
#     timeout=600).executescript(open('/tmp/<name>.sql.rollback').read())"
#
# Uses scripts/apply_sql_batched.py (a few hundred documents per transaction, the write-ahead
# log is checkpointed as it goes) because a single transaction over ~400,000 paragraphs would
# grow the log by gigabytes on a disk shared with another application. It refuses to start with
# less than 3 GB free. Expect tens of minutes; the API is slower while it runs.
#
# Afterwards: ./deploy/rebuild_citations.sh --apply, then restart echr-api and run
# ./deploy/demo_prewarm.sh (every write invalidates the API's cached facets).
set -euo pipefail

SQL="${1:?usage: load_sql_on_vm.sh FORWARD.sql}"
RB="${SQL}.rollback"
[ -f "${SQL}" ] || { echo "no such file: ${SQL}" >&2; exit 2; }
[ -f "${RB}" ] || { echo "rollback file missing: ${RB}" >&2; exit 2; }

HOST="${VM_HOST:-amuvmuser@150.254.115.204}"
CONTAINER="${CONTAINER:-echr-api}"
REMOTE_DIR="${REMOTE_DIR:-/home/amuvmuser/echr}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="$(basename "${SQL}")"
SSH=(ssh -o BatchMode=yes "${HOST}")

echo "== free space on the VM"
"${SSH[@]}" "df -h ${REMOTE_DIR}/data | tail -1"

echo "== copying ${NAME}, its rollback and the loader to ${HOST}"
scp -q -o BatchMode=yes "${SQL}" "${RB}" "${ROOT}/scripts/apply_sql_batched.py" "${HOST}:${REMOTE_DIR}/"
"${SSH[@]}" "cd ${REMOTE_DIR} && docker cp ${NAME} ${CONTAINER}:/tmp/${NAME} && \
  docker cp ${NAME}.rollback ${CONTAINER}:/tmp/${NAME}.rollback && \
  docker cp apply_sql_batched.py ${CONTAINER}:/tmp/apply_sql_batched.py && rm -f ${NAME}"

echo "== applying in batches"
"${SSH[@]}" "docker exec ${CONTAINER} python3 /tmp/apply_sql_batched.py --db /data/echr_search.db --sql /tmp/${NAME} --min-free-gb 3"
"${SSH[@]}" "docker exec ${CONTAINER} rm -f /tmp/${NAME}"

echo "Done. The rollback file is ${REMOTE_DIR}/${NAME}.rollback (and /tmp/${NAME}.rollback in the container)."
echo "Next: ./deploy/rebuild_citations.sh --apply"
