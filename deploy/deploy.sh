#!/usr/bin/env bash
# deploy.sh — Deploy ECHR Dashboard backend to the VM
# Usage: ./deploy.sh <ssh_password>
#
# Prerequisites on the VM (already in place after 2026-04-28 separation):
#   - Docker + docker-compose installed
#   - Nginx installed with HTTPS (Let's Encrypt) routing /echr-api/* → port 8000
#   - Project folder /home/amuvmuser/echr/ (renamed from echr-search/ on 2026-04-28)
#   - Sibling project /home/amuvmuser/uhri/ (separate UHRI dataset API container,
#     do NOT touch — owned by lszoszk/uhri-dataset-api private repo)
#
# This script:
#   1. Uploads backend files and database to the VM
#   2. Builds and starts the Docker container (echr-api)
#   3. Reminds about Nginx config (already in place; no change needed)

set -euo pipefail

VM_HOST="amuvmuser@150.254.115.204"
VM_DIR="/home/amuvmuser/echr"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSHPASS_BIN="/opt/homebrew/bin/sshpass"

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <ssh_password>"
  exit 1
fi

SSH_PASS="$1"
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

echo "=== Step 3: Upload SQLite database (1.1 GB — this may take a while) ==="
$SCP_CMD "$PROJECT_ROOT/data/echr_search.db" "$VM_HOST:$VM_DIR/data/"

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
