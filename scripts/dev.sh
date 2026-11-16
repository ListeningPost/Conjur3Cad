#!/usr/bin/env bash
# One-command local dev stack for Conjur3:
#   Redis · Firebase emulators (auth/firestore/functions) · seed ·
#   conjur3-pilot (HTTP) · MCP gateway · Next.js web app
#
#   ./scripts/dev.sh           # full stack (web in foreground; Ctrl-C tears down)
#   SKIP_FREECAD=1 ./scripts/dev.sh   # skip conjur3-pilot (no local FreeCAD)
#
# Override the conjur3-pilot checkout with CONJUR3_PILOT_DIR=...
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LOGS="$ROOT/.dev-logs"; mkdir -p "$LOGS"
CONJUR3_PILOT_DIR="${CONJUR3_PILOT_DIR:-$ROOT/conjur3/conjur3-pilot}"

pids=()
cleanup() {
  echo; echo "→ tearing down dev stack…"
  for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done
  # emulators + freecad spawn children; nuke by port
  for port in 8088 9099 5001 4000 8765 8090; do
    for pid in $(ss -ltnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | sort -u); do
      kill "$pid" 2>/dev/null || true
    done
  done
}
trap cleanup EXIT INT TERM

echo "→ Redis (docker)…";            docker compose up -d redis >/dev/null 2>&1 || echo "  (docker/redis unavailable — gateway will fail-open)"
echo "→ Firebase emulators…";        ( firebase emulators:start --only auth,firestore,functions --project demo-conjur3 >"$LOGS/emulators.log" 2>&1 ) & pids+=("$!")
echo "  waiting for emulators…"
for i in $(seq 1 40); do grep -q "All emulators ready" "$LOGS/emulators.log" 2>/dev/null && break; sleep 2; done
echo "→ Seeding demo org…";          npm --prefix functions run seed 2>&1 | sed 's/^/  /' || echo "  (seed skipped)"

if [ "${SKIP_FREECAD:-0}" != "1" ] && [ -x "$CONJUR3_PILOT_DIR/.venv/bin/conjur3-pilot" ]; then
  echo "→ conjur3-pilot (HTTP :8765)…"
  ( cd "$CONJUR3_PILOT_DIR" && ./.venv/bin/conjur3-pilot --http --http-host 127.0.0.1 --http-port 8765 >"$LOGS/freecad.log" 2>&1 ) & pids+=("$!")
else
  echo "→ conjur3-pilot skipped (set CONJUR3_PILOT_DIR or SKIP_FREECAD=1)"
fi

echo "→ MCP gateway (:8090)…"
( cd mcp-gateway && PORT=8090 UPSTREAM_MCP_URL=http://127.0.0.1:8765/mcp \
    FIREBASE_PROJECT_ID=demo-conjur3 FIRESTORE_EMULATOR_HOST=127.0.0.1:8088 \
    REDIS_URL=redis://localhost:6379 npm run dev >"$LOGS/gateway.log" 2>&1 ) & pids+=("$!")

cat <<EOF

  ── Conjur3 dev stack up ───────────────────────────────
   Web app        http://localhost:3000      (starting…)
   Emulator UI    http://localhost:4000
   MCP gateway    http://localhost:8090/healthz
   conjur3-pilot  http://127.0.0.1:8765/mcp
   Logs           $LOGS/*.log
   Get started    sign up at http://localhost:3000 (no seeded accounts)
   Keys           minted by platform admins (PLATFORM_ADMIN_EMAILS) while Stripe is off
  ───────────────────────────────────────────────────────
  Ctrl-C to tear everything down.

EOF

echo "→ Next.js web app (foreground)…"
exec npm run dev
