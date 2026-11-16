"""Per-request seat key, used in hosted (relay) mode.

The Conjur3 gateway sets the `X-Conjur3-Seat` header on each MCP request; the
ASGI middleware in `server.main()` stashes it here, and the XML-RPC client tags
its calls with it so the relay can route to that seat's connector → FreeCAD.
Empty in local/stdio mode — harmless.
"""
from contextvars import ContextVar

current_seat: ContextVar[str | None] = ContextVar("conjur3_current_seat", default=None)
