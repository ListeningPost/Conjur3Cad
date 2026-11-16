#!/usr/bin/env bash
# Conjur3 init wrapper for the hermes-agent container.
# Runs as root (same as the upstream entrypoint), writes MCP config and API key
# into the shared hermes-home volume, then hands off to the official entrypoint.
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-/home/hermes/.hermes}"
mkdir -p "${HERMES_HOME}"

# Resolve the live MCP URL — prefer tunnel URL if cloudflared is active.
MCP_URL="${MCP_URL:-http://conjur3:8765/mcp}"
TUNNEL_FILE="/opt/conjur3/out/tunnel_url.txt"
if [[ -f "${TUNNEL_FILE}" ]]; then
  _tunnel=$(cat "${TUNNEL_FILE}" 2>/dev/null || true)
  [[ -n "${_tunnel}" ]] && MCP_URL="${_tunnel}"
fi

echo "[hermes-init] writing config.yaml → ${HERMES_HOME}/config.yaml"
echo "[hermes-init] MCP URL: ${MCP_URL}"

# Always write config.yaml so changes to env vars take effect on restart.
# The upstream entrypoint's own guard (`if [ ! -f config.yaml ]`) will be
# skipped because the file already exists — that's intentional.
cat > "${HERMES_HOME}/config.yaml" <<EOF
mcp_servers:
  conjur3-pilot:
    url: "${MCP_URL}"
EOF

if [[ -n "${MCP_AUTH_TOKEN:-}" ]]; then
  cat >> "${HERMES_HOME}/config.yaml" <<EOF
    headers:
      Authorization: "Bearer ${MCP_AUTH_TOKEN}"
EOF
fi

# Write .env with the Anthropic API key so hermes-agent picks it up
# even if the upstream entrypoint has already copied .env.example.
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "[hermes-init] writing API key → ${HERMES_HOME}/.env"
  printf 'ANTHROPIC_API_KEY=%s\n' "${ANTHROPIC_API_KEY}" > "${HERMES_HOME}/.env"
fi

# Hand off to the official hermes-agent entrypoint (wrapped by tini).
echo "[hermes-init] handing off to /opt/hermes/docker/entrypoint.sh"
exec /opt/hermes/docker/entrypoint.sh "$@"
