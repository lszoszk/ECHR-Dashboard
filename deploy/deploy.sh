#!/usr/bin/env bash
# deploy.sh — Deploy ECHR Dashboard backend to the VM
# Usage: ./deploy.sh <ssh_password> [--with-db]
#
#   <ssh_password>  VM SSH password (passed to sshpass).
#   --with-db       ALSO upload the local SQLite DB, OVERWRITING the one on
#                   the VM.  OMITTED BY DEFAULT and that default is load-
#                   bearing: the VM database is healed IN PLACE by the P5x
#                   passes (run via `docker exec` on the VM), and the local
#                   data/echr_search.db is usually stale.  A blind upload
#                   would silently discard every in-place heal.  Pass
#                   --with-db ONLY when you have deliberately rebuilt the
#                   local DB and want it to become the VM DB.
#
# Prerequisites on the VM (already in place after 2026-04-28 separation):
#   - Docker + docker-compose installed
#   - Nginx installed with HTTPS (Let's Encrypt) routing /echr-api/* → port 8000
#   - Project folder /home/amuvmuser/echr/ (renamed from echr-search/ on 2026-04-28)
#   - Sibling project /home/amuvmuser/uhri/ (separate UHRI dataset API container,
#     do NOT touch — owned by lszoszk/uhri-dataset-api private repo)
#
# This script:
#   1. Uploads backend code files to the VM
#   2. Uploads the SQLite database — ONLY with --with-db (skipped by default)
#   3. Builds and starts the Docker container (echr-api)
#   4. Reminds about Nginx config (already in place; no change needed)

set -euo pipefail

VM_HOST="amuvmuser@150.254.115.204"
VM_DIR="/home/amuvmuser/echr"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSHPASS_BIN="/opt/homebrew/bin/sshpass"

SSH_PASS=""
UPLOAD_DB=0
for arg in "$@"; do
  case "$arg" in
    --with-db)  UPLOAD_DB=1 ;;
    -h|--help)
      echo "Usage: $0 <ssh_password> [--with-db]"
      exit 0 ;;
    --*)
      echo "Unknown flag: $arg" >&2
      echo "Usage: $0 <ssh_password> [--with-db]" >&2
      exit 1 ;;
    *)
      if [ -z "$SSH_PASS" ]; then
        SSH_PASS="$arg"
      else
        echo "Unexpected argument: $arg" >&2
        exit 1
      fi ;;
  esac
done

if [ -z "$SSH_PASS" ]; then
  echo "Usage: $0 <ssh_password> [--with-db]"
  echo "  --with-db  ALSO overwrite the VM database with the local copy."
  echo "             Omit it for a safe code-only redeploy (default)."
  exit 1
fi
SSH_CMD="$SSHPASS_BIN -p $SSH_PASS ssh -o StrictHostKeyChecking=no -o PubkeyAuthentication=no $VM_HOST"
SCP_CMD="$SSHPASS_BIN -p $SSH_PASS scp -o StrictHostKeyChecking=no -o PubkeyAuthentication=no"

echo "=== Step 1: Create remote directories ==="
$SSH_CMD "mkdir -p $VM_DIR/backend $VM_DIR/data"

echo "=== Step 2: Upload backend files ==="
$SCP_CMD "$PROJECT_ROOT/backend/main.py" "$VM_HOST:$VM_DIR/backend/"
$SCP_CMD "$PROJECT_ROOT/backend/build_db.py" "$VM_HOST:$VM_DIR/backend/"
$SCP_CMD "$PROJECT_ROOT/backend/requirements.txt" "$VM_HOST:$VM_DIR/backend/"
$SCP_CMD "$PROJECT_ROOT/backend/Dockerfile" "$VM_HOST:$VM_DIR/backend/"
$SCP_CMD "$PROJECT_ROOT/backend/entrypoint.sh" "$VM_HOST:$VM_DIR/backend/"
$SCP_CMD "$PROJECT_ROOT/docker-compose.yml" "$VM_HOST:$VM_DIR/"
$SCP_CMD "$PROJECT_ROOT/deploy/nginx-echr-api.conf" "$VM_HOST:$VM_DIR/"

if [ "$UPLOAD_DB" -eq 1 ]; then
  echo "=== Step 3: Upload SQLite database (multi-GB — this may take a while) ==="
  echo "    WARNING: this OVERWRITES /data/echr_search.db on the VM and"
  echo "    discards any in-place P5x heal passes applied since the last"
  echo "    upload.  Press Ctrl-C now if that is not what you intend."
  sleep 5
  $SCP_CMD "$PROJECT_ROOT/data/echr_search.db" "$VM_HOST:$VM_DIR/data/"
else
  echo "=== Step 3: SKIPPED — database upload (code-only redeploy) ==="
  echo "    The VM keeps its current /data/echr_search.db, including any"
  echo "    in-place heal passes.  Re-run with --with-db to replace it."
fi

echo "=== Step 4: Build and start Docker container ==="
$SSH_CMD "cd $VM_DIR && docker compose down 2>/dev/null; docker compose up --build -d"

echo "=== Step 5: Wait for health check ==="
sleep 5
$SSH_CMD "curl -s http://localhost:8000/health"
echo ""

echo "=== Step 6: Nginx ==="
echo "Nginx is already configured (post-2026-04-28). The shared site config at"
echo "/etc/nginx/sites-enabled/default routes:"
echo "  /echr-api/api/   → upstream echr_api (port 8000)  [this app]"
echo "  /uhri-api/, /api/data/, /api/feedback/  → upstream uhri_api (port 8001)  [separate UHRI app — do NOT touch]"
echo "No nginx changes are required for an ECHR-only redeploy."

echo ""
echo "=== Done! ==="
echo "API should be available at: https://150.254.115.204/echr-api/health"
