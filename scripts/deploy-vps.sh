#!/usr/bin/env bash
# Ship the MCP stack to the GCP VM and (re)start it via Docker Compose.
#
#   VM_HOST=ubuntu@34.x.x.x ./scripts/deploy-vps.sh
#
# Prereqs on the VM: Docker + Compose, an attached service account (Datastore
# User + Firebase Auth Viewer), DNS A record → VM IP, and a populated
# deploy/.env (kept on the VM, never synced). The MCP image vendors the in-repo
# conjur3/conjur3-pilot source automatically (below).
set -euo pipefail
cd "$(dirname "$0")/.."

: "${VM_HOST:?set VM_HOST=user@host}"
REMOTE_DIR="${VM_PATH:-/opt/conjur3-mcp}"
CONJUR3_PILOT_DIR="${CONJUR3_PILOT_DIR:-conjur3/conjur3-pilot}"

# Vendor conjur3-pilot into the MCP image build context (the hosted MCP).
if [ -d "$CONJUR3_PILOT_DIR" ]; then
  echo "→ vendoring conjur3-pilot into deploy/mcp/…"
  rsync -a --delete --exclude .venv --exclude .git --exclude .pytest_cache \
    "$CONJUR3_PILOT_DIR/" deploy/mcp/conjur3-pilot/
else
  echo "⚠ CONJUR3_PILOT_DIR not found; skipping vendor (MCP image won't build)."
fi

# Stage the connector bundle + installer so the gateway can serve them
# (curl https://host/install.sh | bash). Must happen BEFORE the rsync.
echo "→ staging connector bundle into mcp-gateway/public/…"
npm --prefix connector install >/dev/null 2>&1 && npm --prefix connector run bundle >/dev/null 2>&1
mkdir -p mcp-gateway/public
cp connector/dist/conjur3-connector.js mcp-gateway/public/conjur3-connector.js
cp connector/install.sh     mcp-gateway/public/install.sh
cp connector/install.ps1    mcp-gateway/public/install.ps1
cp connector/update-mcp.sh  mcp-gateway/public/update-mcp.sh
cp connector/update-mcp.ps1 mcp-gateway/public/update-mcp.ps1
rm -rf /tmp/Conjur3 && cp -r conjur3/conjur3-pilot/addon/conjur3_pilot /tmp/Conjur3 && find /tmp/Conjur3 -name __pycache__ -type d -prune -exec rm -rf {} + && tar -czf mcp-gateway/public/conjur3-addon.tar.gz -C /tmp Conjur3 && rm -rf /tmp/Conjur3

echo "→ syncing to $VM_HOST:$REMOTE_DIR…"
ssh "$VM_HOST" "mkdir -p $REMOTE_DIR"
rsync -az --delete \
  --exclude node_modules --exclude dist --exclude .env --exclude .git \
  deploy mcp-gateway connector "$VM_HOST:$REMOTE_DIR/"

echo "→ building + starting the stack on the VM…"
ssh "$VM_HOST" "cd $REMOTE_DIR/deploy && [ -f .env ] || cp .env.prod.example .env; \
  docker compose -f docker-compose.prod.yml up -d --build && \
  docker compose -f docker-compose.prod.yml ps"

echo "✓ VPS deploy complete. Check: curl -s https://mcp.conjur3.com/health (after DNS+TLS)."
