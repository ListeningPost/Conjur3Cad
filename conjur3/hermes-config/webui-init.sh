#!/usr/bin/env bash
# Conjur3 wrapper around hermes-webui's upstream init.
#
# Upstream tries to install `hermes-agent[all]`, which transitively requires
# `mistralai>=2.3.0` — that package version isn't reachable from the default
# pip index, so the install fails and the container dies. We don't need the
# mistral provider for FreeCAD piloting, so we patch the upstream init to
# drop the `[all]` extras before running it.
set -euo pipefail

UPSTREAM="/hermeswebui_init.bash"
PATCHED="/tmp/hermeswebui_init.patched.bash"

# Replace `[all]` with `[mcp]` in the `uv pip install "$_agent_src[all]"` call.
# `[all]` transitively requires `mistralai>=2.3.0` which is unreachable from
# the default pip index, so the full extras install fails. We only need MCP
# client support to talk to conjur3-pilot — `[mcp]` pulls in the `mcp` SDK
# without dragging in mistral, telegram, matrix, etc.
sed 's|\$_agent_src\[all\]|\$_agent_src[mcp]|g' "${UPSTREAM}" > "${PATCHED}"
chmod +x "${PATCHED}"

echo "[conjur3-webui-init] patched upstream init: hermes-agent[all] → hermes-agent[mcp]"
exec "${PATCHED}" "$@"
