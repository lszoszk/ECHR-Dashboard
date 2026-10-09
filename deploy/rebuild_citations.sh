#!/usr/bin/env bash
#
# rebuild_citations.sh — rebuild case_citations on the production VM, and the
# citation graph the Semantic Search page reads. Run it from your workstation
# after every monthly corpus update (scripts/p60_monthly_update.py).
#
#   ./deploy/rebuild_citations.sh            # dry run: scan and report, change nothing
#   ./deploy/rebuild_citations.sh --apply    # keep a backup table, rebuild, checkpoint, rewrite the graph
#
# What --apply does, in order:
#   1. copies scripts/p29_extract_citations.py and scripts/build_rag_citations_json.py
#      into the echr-api container;
#   2. copies case_citations to case_citations_prev (one rolling backup);
#   3. runs p29_extract_citations.py --apply against /data/echr_search.db;
#   4. checkpoints the write-ahead log;
#   5. rewrites /data/rag/citations.json (the old file is kept as citations.json.bak-<stamp>).
#
# The API reads the new table immediately (its caches follow the database file's
# modification time). The Semantic Search graph is cached in memory, so it shows
# the new file only after the next container restart — do that at a quiet time and
# run deploy/demo_prewarm.sh afterwards.
#
# Roll back the table (on the VM, inside the container, with sqlite3 or python):
#   DROP TABLE case_citations;
#   ALTER TABLE case_citations_prev RENAME TO case_citations;
#   CREATE INDEX idx_cc_citing ON case_citations(citing_case_id);
#   CREATE INDEX idx_cc_cited  ON case_citations(cited_case_id);
#
# Only the echr-api container is touched; the VM is shared with another application.
set -euo pipefail

HOST="${VM_HOST:-amuvmuser@150.254.115.204}"
CONTAINER="${CONTAINER:-echr-api}"
STAMP="$(date -u +%Y%m%d-%H%M)"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

SSH=(ssh -o BatchMode=yes "${HOST}")

echo "== copying scripts into ${CONTAINER} =="
for f in p29_extract_citations.py build_rag_citations_json.py; do
  scp -q -o BatchMode=yes "${ROOT}/scripts/${f}" "${HOST}:/tmp/${f}"
  "${SSH[@]}" "docker cp /tmp/${f} ${CONTAINER}:/tmp/${f} && rm -f /tmp/${f}"
done

if [ "${APPLY}" -eq 0 ]; then
  echo "== dry run (nothing is written) =="
  "${SSH[@]}" "docker exec ${CONTAINER} python3 /tmp/p29_extract_citations.py --db /data/echr_search.db"
  echo "Re-run with --apply to rebuild."
  exit 0
fi

echo "== backing up case_citations -> case_citations_prev =="
"${SSH[@]}" "docker exec ${CONTAINER} python3 -c \"
import sqlite3
c = sqlite3.connect('/data/echr_search.db', timeout=120)
c.execute('DROP TABLE IF EXISTS case_citations_prev')
c.execute('CREATE TABLE case_citations_prev AS SELECT * FROM case_citations')
c.commit()
print('backup rows:', c.execute('SELECT count(*) FROM case_citations_prev').fetchone()[0])
\""

echo "== rebuilding case_citations =="
"${SSH[@]}" "docker exec ${CONTAINER} python3 /tmp/p29_extract_citations.py --db /data/echr_search.db --apply"

echo "== checkpointing the write-ahead log =="
"${SSH[@]}" "docker exec ${CONTAINER} python3 -c \"
import sqlite3
c = sqlite3.connect('/data/echr_search.db', timeout=120)
print(c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone())
\""

echo "== rewriting the Semantic Search citation graph =="
"${SSH[@]}" "docker exec ${CONTAINER} sh -c 'cp /data/rag/citations.json /data/rag/citations.json.bak-${STAMP} && python3 /tmp/build_rag_citations_json.py --db /data/echr_search.db --out /data/rag/citations.json'"

echo "== spot check through the public API =="
API="${API:-https://150.254.115.204/echr-api}"
for pair in "001-57499 Handyside" "001-57496 Golder" "001-58920 Kudla"; do
  id="${pair%% *}"; name="${pair#* }"
  n="$(curl -s --max-time 60 "${API}/api/cases/${id}" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("cited_by_count"))' 2>/dev/null || echo '?')"
  echo "  ${name}: cited by ${n} cases"
done
echo "Done. Restart ${CONTAINER} at a quiet time to load the new Semantic Search graph, then run deploy/demo_prewarm.sh."
