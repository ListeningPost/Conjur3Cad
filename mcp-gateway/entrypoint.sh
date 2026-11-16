#!/bin/sh
# Gateway entrypoint. If TS_AUTHKEY is set, join the tailnet first (userspace
# networking — no NET_ADMIN needed, works on Cloud Run) and expose a local
# HTTP/SOCKS5 proxy so outbound calls can reach tailnet-only hosts (e.g. the
# on-prem observability box via its MagicDNS name). Telemetry then defaults to
# routing through that proxy. Without TS_AUTHKEY this is a plain `node` start.
set -e

if [ -n "${TS_AUTHKEY:-}" ]; then
  echo "[entrypoint] joining tailnet as ${TS_HOSTNAME:-conjur3-gateway}…"
  tailscaled --state=mem: --tun=userspace-networking \
    --socks5-server=localhost:1055 --outbound-http-proxy-listener=localhost:1055 &
  # Ephemeral node: state lives in memory; use an ephemeral+reusable auth key.
  tailscale up --authkey="${TS_AUTHKEY}" \
    --hostname="${TS_HOSTNAME:-conjur3-gateway}" --accept-routes
  export TELEMETRY_PROXY="${TELEMETRY_PROXY:-http://localhost:1055}"
  echo "[entrypoint] tailnet up; outbound proxy on localhost:1055"
fi

exec node dist/index.js
