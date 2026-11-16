# Conjur3

A fork of `freecad-mcp-api` that ships with the FreeCAD **Fasteners
Workbench** preinstalled, plus first-class MCP tools for inserting standard
ISO/DIN/ANSI fasteners parametrically.

```
.
├── Dockerfile                       # freecad/freecad-cli + FastenersWB + Conjur3 MCP
├── docker-compose.yml               # One-command launch for the MCP server
├── scripts/
│   └── install_fasteners_wb.sh      # Idempotent installer for FreeCAD_FastenersWB
└── conjur3-pilot/                   # The MCP server + workbench addon
    ├── addon/conjur3_pilot/         # FreeCAD Mod (XML-RPC bridge, runs in-process)
    ├── src/conjur3_pilot/           # FastMCP server (talks XML-RPC to the addon)
    └── tests/
```

## What changed vs. freecad-mcp-api

- **`scripts/install_fasteners_wb.sh`** clones
  [shaise/FreeCAD_FastenersWB](https://github.com/shaise/FreeCAD_FastenersWB)
  into `$FREECAD_MOD_DIR` (defaults to `~/.local/share/FreeCAD/Mod`).
  Idempotent; runs at host-setup time and inside the Docker build.
- **`Dockerfile`** uses the official `freecad/freecad-cli` image, drops the
  Fasteners Workbench into the Mod dir, installs the Conjur3 addon as a
  sibling Mod, and `pip install`s the MCP package so `conjur3-pilot` is on
  PATH.
- **New MCP tools** in `conjur3-pilot/src/conjur3_pilot/server.py`:
  - `list_fasteners(standard=None)` — catalog of supported standards →
    diameters → length tables.
  - `insert_fastener(standard, diameter, length=None, ...)` — adds a
    parametric `Part::FeaturePython` backed by FastenersWB's
    `FSScrewObject` proxy. Recomputes live; the viewport screenshot comes
    back with the result.

## Quick start (local)

```bash
# 1. Install the Fasteners Workbench into your FreeCAD Mod dir
./scripts/install_fasteners_wb.sh

# 2. Install the Conjur3 addon + MCP server (see conjur3-pilot/README.md)
cd conjur3-pilot
uv pip install -e .

# 3. Restart FreeCAD, activate the Conjur3 workbench, then in Claude
#    ask: "list_fasteners('ISO4762')" or
#         "insert_fastener('ISO4762', 'M6', 20)"
```

## Quick start (Docker Compose)

```bash
docker compose up --build
```

That brings up one container running:

| Port | What | How to use |
|---|---|---|
| `6080` | noVNC | Open `http://localhost:6080/vnc.html` → live FreeCAD viewport in your browser |
| `8765` | conjur3-pilot MCP (streamable-http) | Point Anthropic Messages API `mcp_servers[].url` at `http://<host>:8765/mcp` |

Inside the container, FreeCAD GUI runs under Xvfb and auto-loads the
**Conjur3** addon, which starts an XML-RPC bridge on port 9875
(container-internal). The `conjur3-pilot` MCP wrapper forwards remote MCP
calls to that bridge so the Anthropic API can drive the live viewport.

Output `.FCStd` / `.step` / `.stl` files written by the server land in `./out/`
on the host.

### Locking it down

**The defaults are open** — no VNC password, no MCP auth. Only safe on a
loopback or trusted private network. Before exposing publicly, set both:

```bash
VNC_PASSWORD=changeme MCP_AUTH_TOKEN=$(openssl rand -hex 24) docker compose up
```

With `MCP_AUTH_TOKEN` set, the MCP endpoint requires
`Authorization: Bearer <token>` on every request and returns 401 otherwise.
Pass the same token in your Anthropic Messages API call's
`mcp_servers[].authorization_token`.

### Dev tunneling (so Anthropic's API can reach a localhost MCP)

```bash
CONJUR3_DEV_TUNNEL=1 docker compose up
# Watch the logs — a https://*.trycloudflare.com URL appears.
# Pass that URL (plus your MCP_AUTH_TOKEN) to mcp_servers[] in your API call.
```

For production, expose `8765` privately to wherever the API runs — do not use
the trycloudflare tunnel.

### Build args

```bash
FASTENERS_WB_REF=v0.6.10 CLOUDFLARED_VER=2024.10.0 docker compose build
# Or omit cloudflared entirely:
CLOUDFLARED_VER=skip docker compose build
```

## Fastener tool examples

```python
# Enumerate supported standards
list_fasteners()
# → {"standards": ["ASMEB18.2.1.6", "DIN125-1A", "DIN912", "DIN933", "ISO4762", ...]}

# Drill into one standard
list_fasteners("ISO4762")
# → {"standard": "ISO4762", "family": "Screw",
#    "diameters": {"M3": ["5","6","8","10",...], "M4": [...], ...}}

# Insert specific fasteners
insert_fastener("ISO4762", "M6", 20)            # M6×20 socket-head cap screw
insert_fastener("DIN933", "M8", "30")           # M8×30 hex-head bolt
insert_fastener("DIN125-1A", "M6")              # M6 flat washer (no length)
insert_fastener("ISO4762", "M3", 10, thread="real")  # real 3D helix — slow
```

Every call is undo-wrapped and returns a viewport screenshot so the model
can verify the result visually.

## Credits

- **Fasteners Workbench** by Shai Seger and contributors — LGPL-2.1.
  See `FastenersWorkbench/LICENSE` once installed.
- **conjur3-pilot** is this project's MCP server; credits in
  `conjur3-pilot/README.md`.
