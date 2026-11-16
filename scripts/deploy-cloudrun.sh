#!/usr/bin/env bash
# Build + push the gateway and MCP images to Artifact Registry, then deploy the
# autoscaling Cloud Run service (multi-container) in your Firebase/GCP project.
#
#   PROJECT_ID=your-project-id REGION=us-central1 ./scripts/deploy-cloudrun.sh
#
# Prereqs: gcloud auth + Artifact Registry repo "conjur3"; a Redis URL secret
# (conjur3-redis-url) e.g. an Upstash rediss:// URL; the VM's service account
# replaced by Cloud Run's runtime SA with Datastore User + Firebase Auth Viewer.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-conjur3}"
HOST="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}"
CONJUR3_PILOT_DIR="${CONJUR3_PILOT_DIR:-conjur3/conjur3-pilot}"

echo "→ vendoring conjur3-pilot into the MCP image…"
rsync -a --delete --exclude .venv --exclude .git --exclude .pytest_cache \
  "$CONJUR3_PILOT_DIR/" deploy/mcp/conjur3-pilot/

echo "→ staging connector bundle into mcp-gateway/public/…"
npm --prefix connector install >/dev/null 2>&1 && npm --prefix connector run bundle >/dev/null 2>&1
mkdir -p mcp-gateway/public
cp connector/dist/conjur3-connector.js mcp-gateway/public/conjur3-connector.js
cp connector/install.sh     mcp-gateway/public/install.sh
cp connector/install.ps1    mcp-gateway/public/install.ps1
cp connector/update-mcp.sh  mcp-gateway/public/update-mcp.sh
cp connector/update-mcp.ps1 mcp-gateway/public/update-mcp.ps1
rm -rf /tmp/Conjur3 && cp -r conjur3/conjur3-pilot/addon/conjur3_pilot /tmp/Conjur3 && find /tmp/Conjur3 -name __pycache__ -type d -prune -exec rm -rf {} + && tar -czf mcp-gateway/public/conjur3-addon.tar.gz -C /tmp Conjur3 && rm -rf /tmp/Conjur3

echo "→ building + pushing images (Cloud Build)…"
gcloud builds submit mcp-gateway --tag "$HOST/gateway:latest" --project "$PROJECT_ID"
gcloud builds submit deploy/mcp  --tag "$HOST/mcp:latest"     --project "$PROJECT_ID"

echo "→ rendering service.yaml…"
tmp="$(mktemp)"
sed -e "s|__PROJECT_ID__|$PROJECT_ID|g" -e "s|__REGION__|$REGION|g" \
  deploy/cloudrun/service.yaml > "$tmp"

echo "→ deploying Cloud Run service…"
gcloud run services replace "$tmp" --region "$REGION" --project "$PROJECT_ID"
rm -f "$tmp"

echo "✓ Deployed. URL:"
gcloud run services describe conjur3-mcp --region "$REGION" --project "$PROJECT_ID" \
  --format 'value(status.url)'
echo "  Add a Firebase Hosting rewrite (or custom domain) → this service for mcp.conjur3.com"
