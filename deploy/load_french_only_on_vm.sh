#!/usr/bin/env bash
#
# load_french_only_on_vm.sh — create the two small tables behind "cited by" counts of judgments that
# HUDOC publishes only in French (scripts/p70_french_only_metadata.py --sql-out) in the production
# database. About 8,400 rows and 59,000 links, a few MB; one transaction.
#
#   ./deploy/load_french_only_on_vm.sh ~/Desktop/HURIDOCS/echr-local-demo/sql/p70_french_only_citations.sql
#
# Order: run this BEFORE deploying the API change (./deploy/deploy_api_main.sh) and before merging the
# frontend. The old API ignores the tables; the new API reads them. Re-running replaces the content.
# Rollback (also copied next to the forward file): drops both tables.
set -euo pipefail

SQL="${1:?usage: load_french_only_on_vm.sh FORWARD.sql}"
RB="${SQL}.rollback"
[ -f "${SQL}" ] || { echo "no such file: ${SQL}" >&2; exit 2; }
[ -f "${RB}" ] || { echo "rollback file missing: ${RB}" >&2; exit 2; }

HOST="${VM_HOST:-amuvmuser@150.254.115.204}"
CONTAINER="${CONTAINER:-echr-api}"
REMOTE_DIR="${REMOTE_DIR:-/home/amuvmuser/echr}"
NAME="$(basename "${SQL}")"
SSH=(ssh -o BatchMode=yes "${HOST}")

echo "== copying ${NAME} and its rollback to ${HOST}"
scp -q -o BatchMode=yes "${SQL}" "${RB}" "${HOST}:${REMOTE_DIR}/"
"${SSH[@]}" "cd ${REMOTE_DIR} && docker cp ${NAME} ${CONTAINER}:/tmp/${NAME} && \
  docker cp ${NAME}.rollback ${CONTAINER}:/tmp/${NAME}.rollback"

echo "== applying (one transaction)"
"${SSH[@]}" "docker exec ${CONTAINER} python3 -c \"
import sqlite3
con = sqlite3.connect('/data/echr_search.db', timeout=600)
con.executescript(open('/tmp/${NAME}').read())
print('french_only_cases', con.execute('SELECT count(*) FROM french_only_cases').fetchone()[0],
      '| french_only_citations', con.execute('SELECT count(*) FROM french_only_citations').fetchone()[0],
      '| cases', con.execute('SELECT count(*) FROM cases').fetchone()[0])
\""
"${SSH[@]}" "docker exec ${CONTAINER} rm -f /tmp/${NAME}"

echo "Done. To undo: docker exec ${CONTAINER} python3 -c \"import sqlite3; sqlite3.connect('/data/echr_search.db', timeout=600).executescript(open('/tmp/${NAME}.rollback').read())\""
echo "Next: ./deploy/deploy_api_main.sh (new API), then merge the frontend pull request."
