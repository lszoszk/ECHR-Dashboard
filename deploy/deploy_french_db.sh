#!/usr/bin/env bash
#
# deploy_french_db.sh — put echr_fr.db (the French originals, scripts/p75_build_french_db.py) next to
# the production database, where the API finds it (ECHR_FR_DB_PATH, default /data/echr_fr.db).
#
#   ./deploy/deploy_french_db.sh /path/to/echr_fr.db
#
# The file is copied under a temporary name, its checksum compared with the local one, and only then
# renamed into place, so the API never sees a half-copied file. It needs the API code that knows the
# file (lang=fr): run deploy/deploy_api_main.sh afterwards if that is not deployed yet, then
# deploy/demo_prewarm.sh. Without that code the file is simply ignored.
#
# Rollback: remove the file (and its -wal/-shm) on the VM; the API then answers lang=fr with 404 and
# the Search page hides the language switch:
#   ssh amuvmuser@150.254.115.204 'rm -f /home/amuvmuser/echr/data/echr_fr.db*'
#
# Only the ECHR data directory is touched; the VM is shared with another application.
set -euo pipefail

SRC="${1:?usage: deploy_french_db.sh /path/to/echr_fr.db}"
[ -f "${SRC}" ] || { echo "no such file: ${SRC}" >&2; exit 2; }
HOST="${VM_HOST:-amuvmuser@150.254.115.204}"
DATA="${REMOTE_DATA:-/home/amuvmuser/echr/data}"
SSH=(ssh -o BatchMode=yes "${HOST}")

SIZE_MB=$(( $(stat -f %z "${SRC}" 2>/dev/null || stat -c %s "${SRC}") / 1048576 ))
echo "== free space on the VM (file: ${SIZE_MB} MB)"
FREE_MB=$("${SSH[@]}" "df -m ${DATA} | tail -1 | awk '{print \$4}'")
echo "   ${FREE_MB} MB free"
[ "${FREE_MB}" -gt $(( SIZE_MB + 3000 )) ] || { echo "less than file + 3 GB free; stopping" >&2; exit 3; }

echo "== checkpointing the local file into one piece"
python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()" "${SRC}"
LOCAL_SUM=$(shasum -a 256 "${SRC}" | cut -d' ' -f1)

echo "== copying to ${HOST}:${DATA}/echr_fr.db.part"
scp -q -o BatchMode=yes "${SRC}" "${HOST}:${DATA}/echr_fr.db.part"
REMOTE_SUM=$("${SSH[@]}" "sha256sum ${DATA}/echr_fr.db.part | cut -d' ' -f1")
[ "${LOCAL_SUM}" = "${REMOTE_SUM}" ] || { echo "checksum mismatch; the .part file is left for inspection" >&2; exit 4; }

echo "== moving into place"
"${SSH[@]}" "rm -f ${DATA}/echr_fr.db-wal ${DATA}/echr_fr.db-shm && mv ${DATA}/echr_fr.db.part ${DATA}/echr_fr.db"
echo "== check: french_originals in /api/stats (needs the lang=fr API code)"
curl -s "https://150.254.115.204/echr-api/api/stats" | python3 -c "import sys,json; print('   french_originals =', json.load(sys.stdin).get('french_originals'))" || true
echo "Done. Next: deploy/deploy_api_main.sh (if needed), then deploy/demo_prewarm.sh."
