#!/usr/bin/env python3
"""End-to-end test: ask Claude to ping the Conjur3 MCP through the
Anthropic Messages API's remote-MCP `mcp_servers` parameter.

Usage:
    pip install anthropic  # one-time
    export ANTHROPIC_API_KEY=sk-ant-...
    # If MCP is exposed somewhere other than localhost, override:
    export MCP_URL=https://your-tunnel.trycloudflare.com/mcp
    export MCP_AUTH_TOKEN=...        # only if you set one in .env
    python3 scripts/anthropic_e2e.py

The script prints the model's response and exits non-zero on tool-call error.

Note: the Anthropic API must be able to REACH `MCP_URL`. For local dev set
CONJUR3_DEV_TUNNEL=1 in .env and use the printed trycloudflare URL.
"""

from __future__ import annotations

import os
import sys

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("anthropic SDK missing — `pip install anthropic`")


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set — see .env.example")

    mcp_url = os.environ.get("MCP_URL", "http://localhost:8765/mcp")
    mcp_token = os.environ.get("MCP_AUTH_TOKEN", "").strip()

    server: dict[str, object] = {
        "type": "url",
        "url": mcp_url,
        "name": "conjur3-pilot",
    }
    if mcp_token:
        server["authorization_token"] = mcp_token

    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                "Call the conjur3-pilot MCP's `ping` tool and tell me the "
                "FreeCAD version it reports."
            ),
        }],
        mcp_servers=[server],
        extra_headers={"anthropic-beta": "mcp-client-2025-04-04"},
    )

    had_tool_use = False
    for block in msg.content:
        kind = getattr(block, "type", None)
        if kind == "text":
            print(block.text)
        elif kind == "mcp_tool_use":
            had_tool_use = True
            print(f"[mcp_tool_use] {block.name}")
        elif kind == "mcp_tool_result":
            print(f"[mcp_tool_result is_error={block.is_error}]")
            for c in (block.content or []):
                if getattr(c, "type", None) == "text":
                    print(c.text)
            if block.is_error:
                return 2
    return 0 if had_tool_use else 3


if __name__ == "__main__":
    sys.exit(main())
