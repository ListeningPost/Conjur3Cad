"""Shape test for MCP tool wrappers in `conjur3_pilot.server`.

Each `@mcp.tool()` is expected to forward its arguments into exactly one
`_client().<method>(...)` call.  This test:

1. Imports `server.py` with a stubbed PilotClient so the import succeeds.
2. Parses the source for `_client().<method>(...)` references.
3. Verifies the referenced method names look like valid RPC method names
   (snake_case, not dunders) — catches typos after refactors.
4. Confirms every high-level helper promoted in the hardening pass exposes
   both an RPC method *and* an MCP wrapper with matching names.
"""

from __future__ import annotations

import inspect
import re
import sys
import types


def _install_stubs():
    """Provide just enough mcp / rpc_client to import server.py."""
    if "mcp" in sys.modules:
        return
    mcp_pkg = types.ModuleType("mcp")
    sys.modules["mcp"] = mcp_pkg
    server_mod = types.ModuleType("mcp.server")
    sys.modules["mcp.server"] = server_mod
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    sys.modules["mcp.server.fastmcp"] = fastmcp

    class _FastMCP:
        def __init__(self, *args, **kw):
            self.tools: dict = {}

        def tool(self):
            def decorate(fn):
                self.tools[fn.__name__] = fn
                return fn
            return decorate

    class _Context:
        pass

    fastmcp.FastMCP = _FastMCP
    fastmcp.Context = _Context

    types_mod = types.ModuleType("mcp.types")
    sys.modules["mcp.types"] = types_mod

    class _TextContent:
        def __init__(self, *, type, text):
            self.type, self.text = type, text

    class _ImageContent:
        def __init__(self, *, type, mimeType, data):
            self.type, self.mimeType, self.data = type, mimeType, data

    types_mod.TextContent = _TextContent
    types_mod.ImageContent = _ImageContent


_install_stubs()

# Import server.py with stubs in place.
from conjur3_pilot import server as srv  # noqa: E402


def _extract_client_calls(src: str) -> set[str]:
    """Return set of method names referenced via `_client().<name>`."""
    return set(re.findall(r"_client\(\)\.([a-zA-Z_][a-zA-Z0-9_]*)", src))


def test_every_client_call_uses_plausible_method_name():
    """`_client().foo` reference should look like a valid RPC method —
    catches typos after refactors.  `_call` is the intentional low-level
    escape hatch on PilotClient and is allowed."""
    allowed_private = {"_call"}
    calls = _extract_client_calls(inspect.getsource(srv))
    assert calls, "expected to find _client() references in server.py"
    for name in calls:
        if name in allowed_private:
            continue
        assert not name.startswith("_"), f"private method exposed: {name}"
        assert name == name.lower(), f"non-snake_case method: {name}"


def test_new_helpers_are_wired_through():
    """Every helper promoted in the hardening pass must have an MCP wrapper
    of the same name and a matching `_client().<name>` call."""
    required = {
        "rotate_about_axis",
        "pocket_through",
        "pocket_blind",
        "hex_grid_sketch",
        "countersunk_hole",
        "clear_sketch_geometry",
        "set_sketch_rectangle",
        "get_origin_plane",
    }
    calls = _extract_client_calls(inspect.getsource(srv))
    # The MCP wrapper functions must be defined at module level.
    defined = {name for name in required if hasattr(srv, name)}
    assert defined == required, f"missing MCP wrappers: {required - defined}"
    # Each wrapper must forward to its same-named RPC method.
    missing_calls = required - calls
    assert not missing_calls, (
        f"MCP wrappers exist but don't call their RPC counterparts: {missing_calls}"
    )


def test_timeout_ms_exposed_on_known_heavy_tools():
    """Per-call timeout overrides are part of the hardening contract."""
    heavy = [
        "execute_code",
        "capture_viewport",
        "export_step",
        "export_fcstd",
        "export_stl",
        "pocket_sketch",
        "boolean",
        "pocket_through",
        "pocket_blind",
        "hex_grid_sketch",
    ]
    for name in heavy:
        fn = getattr(srv, name, None)
        assert fn is not None, f"{name} missing from server module"
        sig = inspect.signature(fn)
        assert "timeout_ms" in sig.parameters, f"{name} missing timeout_ms kwarg"
