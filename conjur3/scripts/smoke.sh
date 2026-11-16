#!/usr/bin/env bash
# Conjur3 stack smoke test. Exits 0 only if every check passes.
# Used by the Ralph Loop to gate STACK VALID.

set -uo pipefail

NOVNC_PORT="${NOVNC_PORT:-6080}"
MCP_PORT="${MCP_PORT:-8765}"
RPC_PORT="${RPC_PORT:-9875}"
CONTAINER="${CONTAINER:-conjur3}"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "PASS: $*"; }

# 1. Container running & not restart-looping.
state=$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo missing)
[[ "$state" == "running" ]] || fail "container state=$state"
restarts=$(docker inspect -f '{{.RestartCount}}' "$CONTAINER")
(( restarts <= 2 )) || fail "restart count=$restarts (looping)"
ok "container running, restarts=$restarts"

# 2. noVNC web UI returns 200 (retry — startup is async).
for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${NOVNC_PORT}/vnc.html" || true)
    [[ "$code" == "200" ]] && break
    sleep 1
done
[[ "$code" == "200" ]] || fail "noVNC /vnc.html returned HTTP $code after 30s"
ok "noVNC /vnc.html 200"

# 3. Conjur3 RPC up inside container (give it time to come up).
rpc_ready=0
for i in $(seq 1 90); do
    if docker exec "$CONTAINER" nc -z localhost "$RPC_PORT" 2>/dev/null; then
        rpc_ready=1; break
    fi
    sleep 1
done
(( rpc_ready == 1 )) || fail "RPC port $RPC_PORT not reachable inside container after 90s"
ok "RPC :$RPC_PORT reachable inside container"

# 4. FreeCAD GUI process exists.
docker exec "$CONTAINER" pgrep -af 'freecad' | grep -vi pilot | grep -q . \
    || fail "no freecad GUI process found"
ok "FreeCAD GUI process running"

# 5. MCP wrapper process exists.
docker exec "$CONTAINER" pgrep -af 'conjur3-pilot' | grep -q . \
    || fail "no conjur3-pilot MCP process found"
ok "conjur3-pilot MCP process running"

# 6. MCP HTTP initialize.
init_payload='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0.1"}}}'
init_resp=$(curl -sS -X POST "http://localhost:${MCP_PORT}/mcp" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H 'MCP-Protocol-Version: 2025-06-18' \
    --data "$init_payload" 2>&1 || true)
echo "  initialize raw response: $(printf '%s' "$init_resp" | head -c 400)"
echo "$init_resp" | grep -q '"conjur3-pilot"' || fail "MCP initialize did not return serverInfo.name=conjur3-pilot"
ok "MCP initialize OK"

# Capture session id (streamable-http sends Mcp-Session-Id header).
session_hdrs=$(curl -sS -D - -o /dev/null -X POST "http://localhost:${MCP_PORT}/mcp" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H 'MCP-Protocol-Version: 2025-06-18' \
    --data "$init_payload")
session_id=$(printf '%s' "$session_hdrs" | awk -v IGNORECASE=1 '/^mcp-session-id:/ {gsub(/\r/,""); print $2; exit}')
[[ -n "${session_id:-}" ]] || fail "no Mcp-Session-Id header returned"
ok "MCP session id captured: $session_id"

# 7. tools/list >= 50.
# Need to send initialized notification first per MCP spec.
curl -sS -X POST "http://localhost:${MCP_PORT}/mcp" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H 'MCP-Protocol-Version: 2025-06-18' \
    -H "Mcp-Session-Id: $session_id" \
    --data '{"jsonrpc":"2.0","method":"notifications/initialized"}' >/dev/null

tools_resp=$(curl -sS -X POST "http://localhost:${MCP_PORT}/mcp" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H 'MCP-Protocol-Version: 2025-06-18' \
    -H "Mcp-Session-Id: $session_id" \
    --data '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}')
echo "  tools/list raw (first 400 chars): $(printf '%s' "$tools_resp" | head -c 400)"
# Streamable HTTP may return SSE frames; pull JSON out of any 'data: ' lines.
tools_json=$(printf '%s' "$tools_resp" | sed -n 's/^data: //p' | tail -1)
[[ -z "$tools_json" ]] && tools_json="$tools_resp"
tools_count=$(printf '%s' "$tools_json" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d.get("result",{}).get("tools",[])))' 2>/dev/null || echo 0)
(( tools_count >= 50 )) || fail "tools/list returned $tools_count tools (want >= 50)"
ok "tools/list returned $tools_count tools"

# 8. Call MCP tool 'ping' end-to-end.
ping_resp=$(curl -sS -X POST "http://localhost:${MCP_PORT}/mcp" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H 'MCP-Protocol-Version: 2025-06-18' \
    -H "Mcp-Session-Id: $session_id" \
    --data '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ping","arguments":{}}}')
echo "  ping raw: $(printf '%s' "$ping_resp" | head -c 400)"
ping_json=$(printf '%s' "$ping_resp" | sed -n 's/^data: //p' | tail -1)
[[ -z "$ping_json" ]] && ping_json="$ping_resp"
printf '%s' "$ping_json" | python3 -c '
import json,sys
d = json.load(sys.stdin)
r = d.get("result", {})
if r.get("isError"):
    sys.exit(2)
content = r.get("content", [])
if not content: sys.exit(3)
print("  ping content[0]:", json.dumps(content[0])[:300])
' || fail "ping tool call did not return a clean result"
ok "MCP ping tool call returned ok"

echo "ALL CHECKS PASSED"
