#!/usr/bin/env bash
#
# deploy_api_main.sh — put api/main.py on the production VM and restart only the
# echr-api container, with health gates and an automatic rollback.
#
#   ./deploy/deploy_api_main.sh
#
# Also ships the modules main.py imports that are not in the image yet (MODULES below), into
# the same host directory and /app.
#
# This is the procedure used on 2026-10-08, as a script. It does NOT use
# deploy/deploy.sh, which is out of date and would overwrite the live compose file.
#
# Steps: compile-check the file inside the container; keep a copy of the old file
# on the VM (backend/main.py.bak-<stamp>); write the new file to the host's
# backend/main.py and into the container at /app/main.py; restart echr-api; then
# require /health, a COLD /api/stats (up to ~4 minutes after a restart) and
# /api/facets to answer. If any gate fails the old file is restored and the
# container is restarted again.
#
# Do not run it shortly before a demo: the restart leaves /api/stats cold for
# minutes. Run deploy/demo_prewarm.sh afterwards.
set -euo pipefail

HOST="${VM_HOST:-amuvmuser@150.254.115.204}"
CONTAINER="${CONTAINER:-echr-api}"
API="${API:-https://150.254.115.204/echr-api}"
REMOTE_DIR="${REMOTE_DIR:-/home/amuvmuser/echr/backend}"
STAMP="$(date -u +%Y%m%d-%H%M)"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/api/main.py"
MODULES=(citation_check.py rag_mod.py)   # imported by main.py; copied next to it
SSH=(ssh -o BatchMode=yes "${HOST}")

python3 -m py_compile "${SRC}"
for m in "${MODULES[@]}"; do python3 -m py_compile "${ROOT}/api/${m}"; done
echo "== local compile OK: ${SRC}"

echo "== uploading and compile-checking inside ${CONTAINER}"
scp -q -o BatchMode=yes "${SRC}" "${HOST}:/tmp/main.py.new"
for m in "${MODULES[@]}"; do scp -q -o BatchMode=yes "${ROOT}/api/${m}" "${HOST}:/tmp/${m}.new"; done
"${SSH[@]}" "docker cp /tmp/main.py.new ${CONTAINER}:/tmp/main.py.new && \
  docker exec ${CONTAINER} python3 -c \"import py_compile; py_compile.compile('/tmp/main.py.new', cfile='/tmp/main.pyc.check', doraise=True); print('container compile OK')\""

echo "== installing the modules (new files; main.py still the old one until the next step)"
for m in "${MODULES[@]}"; do
  "${SSH[@]}" "if [ -f ${REMOTE_DIR}/${m} ]; then cp ${REMOTE_DIR}/${m} ${REMOTE_DIR}/${m}.bak-${STAMP}; fi && \
    cp /tmp/${m}.new ${REMOTE_DIR}/${m} && docker cp ${REMOTE_DIR}/${m} ${CONTAINER}:/app/${m} && \
    docker exec ${CONTAINER} python3 -c \"import py_compile; py_compile.compile('/app/${m}', cfile='/tmp/${m}c', doraise=True)\" && echo '  ${m} OK'"
  # the image copies files one by one: a later rebuild must copy the module too
  "${SSH[@]}" "grep -q '^COPY ${m} ' ${REMOTE_DIR}/Dockerfile || (cp ${REMOTE_DIR}/Dockerfile ${REMOTE_DIR}/Dockerfile.bak-${STAMP} && \
    sed -i '/^COPY ranking.py \./a COPY ${m} .' ${REMOTE_DIR}/Dockerfile && echo '  Dockerfile: COPY ${m} added')"
done

echo "== backing up the live file and installing the new one"
"${SSH[@]}" "cp ${REMOTE_DIR}/main.py ${REMOTE_DIR}/main.py.bak-${STAMP} && \
  cp /tmp/main.py.new ${REMOTE_DIR}/main.py && \
  docker cp ${REMOTE_DIR}/main.py ${CONTAINER}:/app/main.py && \
  docker restart ${CONTAINER} >/dev/null && echo restarted"

wait_for() {  # label, path, max seconds
  local label="$1" path="$2" max="$3" t=0 code
  while [ "${t}" -lt "${max}" ]; do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "${API}${path}" || true)"
    if [ "${code}" = "200" ]; then echo "  ${label}: OK after ~${t}s"; return 0; fi
    sleep 5; t=$((t + 5))
  done
  echo "  ${label}: FAILED (last HTTP ${code})" >&2
  return 1
}

rollback() {
  echo "== a gate failed: restoring ${REMOTE_DIR}/main.py.bak-${STAMP}" >&2
  "${SSH[@]}" "cp ${REMOTE_DIR}/main.py.bak-${STAMP} ${REMOTE_DIR}/main.py && \
    docker cp ${REMOTE_DIR}/main.py ${CONTAINER}:/app/main.py && docker restart ${CONTAINER} >/dev/null"
  exit 1
}

echo "== health gates"
wait_for "/health" "/health" 120 || rollback
wait_for "/api/stats (cold)" "/api/stats" 300 || rollback
wait_for "/api/facets" "/api/facets" 120 || rollback
curl -s --max-time 60 -G "${API}/api/search" --data-urlencode 'q="pressing social need"' --data-urlencode "page_size=3" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print("  search OK:", d.get("total_cases"), "cases")' || rollback
curl -s --max-time 60 -X POST "${API}/api/check/resolve" -H 'Content-Type: application/json' \
  -d '{"items":[{"key":"k","appnos":["30210/96"],"name":"Kudla v. Poland","gc":true}]}' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin)["items"][0]; assert d["status"] == "found", d; print("  check/resolve OK:", d["match"]["title"])' || rollback

echo "Done. Old file kept as ${REMOTE_DIR}/main.py.bak-${STAMP}. Run deploy/demo_prewarm.sh next."
