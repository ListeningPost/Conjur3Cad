#!/usr/bin/env bash
# Conjur3 container entrypoint. Starts the full stack in order:
#   Xvfb → fluxbox → x11vnc → websockify (noVNC) → FreeCAD GUI → MCP server
#   → cloudflared (optional, dev tunnel).
#
# Each background process gets its PID tracked; SIGTERM tears them all down.

set -euo pipefail

: "${DISPLAY:=:0}"
: "${VNC_PORT:=5900}"
: "${NOVNC_PORT:=6080}"
: "${MCP_PORT:=8765}"
: "${RPC_PORT:=9875}"
: "${SCREEN_GEOMETRY:=1440x900x24}"
: "${VNC_PASSWORD:=}"
: "${MCP_AUTH_TOKEN:=}"
: "${CONJUR3_DEV_TUNNEL:=0}"

export DISPLAY

# XDG_RUNTIME_DIR must exist with mode 700 before FreeCAD/Qt start, or Qt logs
# "QStandardPaths: XDG_RUNTIME_DIR not set" and may misbehave.
if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
    mkdir -p "${XDG_RUNTIME_DIR}"
    chmod 700 "${XDG_RUNTIME_DIR}"
fi

pids=()

cleanup() {
    echo "[entrypoint] shutting down" >&2
    for p in "${pids[@]:-}"; do
        kill "$p" 2>/dev/null || true
    done
    wait || true
}
trap cleanup TERM INT EXIT

# --- 1. Xvfb ---------------------------------------------------------------
echo "[entrypoint] starting Xvfb on ${DISPLAY} (${SCREEN_GEOMETRY})"
Xvfb "${DISPLAY}" -screen 0 "${SCREEN_GEOMETRY}" -nolisten tcp &
pids+=($!)

# Wait for X to be ready.
for i in $(seq 1 40); do
    if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then break; fi
    sleep 0.1
done

# --- 2. fluxbox (minimal WM, gives FreeCAD a manager so windows decorate) --
echo "[entrypoint] starting fluxbox"
fluxbox >/var/log/fluxbox.log 2>&1 &
pids+=($!)

# --- 3. x11vnc (binds to :0, localhost only — noVNC is the public face) ----
vnc_args=(-display "${DISPLAY}" -forever -shared -rfbport "${VNC_PORT}" -localhost -bg -o /var/log/x11vnc.log)
if [[ -n "${VNC_PASSWORD}" ]]; then
    mkdir -p /root/.vnc
    x11vnc -storepasswd "${VNC_PASSWORD}" /root/.vnc/passwd >/dev/null
    vnc_args+=(-rfbauth /root/.vnc/passwd)
    echo "[entrypoint] x11vnc starting (password-protected)"
else
    vnc_args+=(-nopw)
    echo "[entrypoint] x11vnc starting (no password — set VNC_PASSWORD for auth)"
fi
x11vnc "${vnc_args[@]}"

# --- 4. websockify / noVNC -------------------------------------------------
echo "[entrypoint] starting noVNC on :${NOVNC_PORT}"
websockify --web /usr/share/novnc "${NOVNC_PORT}" "localhost:${VNC_PORT}" \
    >/var/log/websockify.log 2>&1 &
pids+=($!)

# --- 5. FreeCAD GUI --------------------------------------------------------
# Run as a regular GUI app under DISPLAY=:0. The Conjur3 workbench's InitGui.py
# registers itself with FreeCAD on startup and the addon auto-starts its
# XML-RPC server on :${RPC_PORT}.
echo "[entrypoint] launching FreeCAD GUI"
freecad >/var/log/freecad.log 2>&1 &
pids+=($!)

# --- 6. Wait for the Conjur3 RPC bridge to come up --------------------------
echo "[entrypoint] waiting for Conjur3 RPC on localhost:${RPC_PORT}"
ready=0
for i in $(seq 1 120); do
    if nc -z localhost "${RPC_PORT}" 2>/dev/null; then
        ready=1
        break
    fi
    sleep 1
done
if [[ "${ready}" == "1" ]]; then
    echo "[entrypoint] Conjur3 RPC is up"
else
    echo "[entrypoint] WARNING: Conjur3 RPC not reachable after 120s. " \
         "FreeCAD may have failed to load the addon. See /var/log/freecad.log" >&2
    echo "[entrypoint] continuing anyway — MCP tool calls will fail until RPC is up" >&2
fi

# --- 7. conjur3-pilot MCP server (HTTP) ------------------------------------
mcp_args=(--http --http-host 0.0.0.0 --http-port "${MCP_PORT}")
if [[ -n "${MCP_AUTH_TOKEN}" ]]; then
    export MCP_AUTH_TOKEN
    echo "[entrypoint] MCP bearer-token auth enabled (set via MCP_AUTH_TOKEN)"
fi
echo "[entrypoint] starting conjur3-pilot MCP on :${MCP_PORT}"
conjur3-pilot "${mcp_args[@]}" 2>&1 | sed 's/^/[mcp] /' &
pids+=($!)

# --- 8. cloudflared (optional dev tunnel) ----------------------------------
if [[ "${CONJUR3_DEV_TUNNEL}" == "1" ]] && command -v cloudflared >/dev/null; then
    echo "[entrypoint] starting cloudflared quick-tunnel for MCP"

    # Start cloudflared in background and capture URL in a subshell
    {
        cloudflared tunnel --no-autoupdate \
            --url "http://127.0.0.1:${MCP_PORT}" 2>&1 |
        while IFS= read -r line; do
            echo "[cloudflared] $line"
            if echo "$line" | grep -q "https://.*trycloudflare.com"; then
                TUNNEL_URL=$(echo "$line" | grep -oP 'https://[a-z0-9\-]+\.trycloudflare\.com' | head -1)
                if [[ -n "${TUNNEL_URL}" ]]; then
                    mkdir -p /opt/conjur3/out
                    echo "${TUNNEL_URL}/mcp" > /opt/conjur3/out/tunnel_url.txt
                    chmod 644 /opt/conjur3/out/tunnel_url.txt
                    echo "[entrypoint] Cloudflare tunnel ready: ${TUNNEL_URL}"
                fi
            fi
        done
    } &
    pids+=($!)
fi

echo "[entrypoint] all services up. noVNC: http://<host>:${NOVNC_PORT}  MCP: http://<host>:${MCP_PORT}/mcp"
if [[ -f /opt/conjur3/out/tunnel_url.txt ]]; then
    echo "[entrypoint] Tunnel URL: $(cat /opt/conjur3/out/tunnel_url.txt)"
fi
wait
