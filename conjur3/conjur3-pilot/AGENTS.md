# AGENTS.md — conjur3-pilot field guide

Non-obvious lore for agents (human or LLM) building parametric CAD through
this MCP.  Read before your first complex build; re-read after your first
mysterious failure.

## Architecture in two sentences

`server.py` publishes `@mcp.tool()` functions that call `rpc_client.py`,
which speaks XML-RPC to `rpc_server.py` running *inside* the FreeCAD GUI.
Every mutation is serialized onto the Qt main thread via a per-call request
token so timeouts never leak one call's result into another's return value.

## Coordinate conventions you need memorized

### Sketch-plane → body-local axis mapping

A sketch attached to a body's origin plane uses the plane's "in-plane"
coordinates as `(u, v)`.  The mapping from sketch-local `(u, v)` to
body-local `(X, Y, Z)` is:

| Plane | sketch u → | sketch v → | sketch normal (pad direction) |
|---|---|---|---|
| `XY_Plane` | body X | body Y | body +Z |
| `XZ_Plane` | body X | body Z | body +Y |
| `YZ_Plane` | body Y | body Z | body +X |

The origin plane's name in FreeCAD is *suffixed with the body index*
(e.g. `YZ_Plane032`).  Never hard-code the suffix — call
`get_origin_plane(body, "YZ")` to resolve the actual object name.

### World coordinates vs body-local

A body's `Placement.Base` translates body-local → world.  When you pocket
through a panel, the sketch is in body-local coords; the result inherits
the body's Placement, so a pocket at body-local `(u=10, v=20)` on a YZ
sketch lands at world `(body.X, body.Y + 10 - local_origin, body.Z + 20 - ...)`.

When in doubt, check `body.Shape.BoundBox` in world space and
`sketch.Shape.BoundBox` in sketch space before you reason about cuts.

## Feature-order gotchas (I hit this, don't repeat it)

When you delete and re-add a pocket inside a body whose *downstream* chain
includes other pockets, FreeCAD re-interprets each pocket's `Reversed` flag
relative to the new "last feature's" face orientation.  A pocket that was
cutting correctly (e.g., from inside face outward) can silently flip to
cutting from outside inward, removing vastly more material than intended.

**Symptom**: after a seemingly unrelated edit, a panel's volume drops to
near zero.  The pocket feature reports `.Shape.Volume == <tiny>` because
its interpretation flipped.

**Fix**: don't splice a new pocket into the middle of an existing chain.
Rebuild the whole downstream chain (delete all features after the pad,
then re-add them in the intended order).

This is specifically why `pocket_through` / `pocket_blind` don't try to
"insert before" existing features — they append to the Tip.

## Timeouts

The server routes every call through the GUI thread with a per-call
timeout.  Defaults:

| Tool | Default timeout | Notes |
|---|---|---|
| most mutations | 30 s | |
| `execute_code` | 60 s | bump for heavy scripts |
| `hex_grid_sketch` | 120 s | hex-polyline generation is slow |
| `export_step`, `export_fcstd`, `export_stl` | 300 s | 50+ bodies can take minutes |

All of these accept `timeout_ms` to override.  Rule of thumb: if your
operation touches hundreds or thousands of edges/faces, bump `timeout_ms`
by 10× before you first run it.

**If a call does time out**, the response will carry `timed_out: True`
and a hint; the server will discard the late result (so it can't leak
into the *next* call's return value).  Wait a few seconds, then re-query
state (`ping`, `list_objects`) before retrying.

## Escape-hatch etiquette — `execute_code`

`execute_code` is the emergency exit, not the front door.  Use it when:

- You need a FreeCAD API that isn't wrapped yet (rare now).
- You need to batch tens of interrelated operations where the per-call
  RPC overhead would dominate (a frame-render loop).
- You need to read live object state (e.g., `body.Shape.BoundBox`) and
  branch on it.

Avoid it for things that have a dedicated tool.  Each curated tool has
undo wrapping, error shaping, and screenshot appending that a raw
`execute_code` does not.

When you *do* use `execute_code`, get output back reliably:

```python
# Write intermediate results to disk — stdout is captured, but returning
# data as a file is robust against timeouts.
with open("/tmp/fcpilot_debug.txt", "w") as f:
    f.write(json.dumps({"vol": body.Shape.Volume, "name": body.Name}))
```

Then `cat /tmp/fcpilot_debug.txt` from the host side.  This pattern
survives timeouts (the file exists regardless).

## Promoted helpers (use these instead of reinventing)

| Tool | What it replaces |
|---|---|
| `rotate_about_axis` | hand-composed `T · R · T⁻¹ · P` placement math |
| `pocket_through` | guessing `midplane` / `reversed` / `depth` for a thru-hole |
| `pocket_blind` | same, but for blind pockets |
| `hex_grid_sketch` | ~1800 `add_sketch_polyline` round-trips for a honeycomb |
| `countersunk_hole` | two sketches + two pockets for every flat-head fastener |
| `clear_sketch_geometry` | the `while sk.Geometry: sk.delGeometry(0)` ritual |
| `set_sketch_rectangle` | "shrink the door by 3mm" without rebuilding the body |
| `get_origin_plane` | finding `YZ_Plane032` vs `YZ_Plane055` by prefix search |

## Worked example — ventilated cover with a countersunk mounting hole

```python
doc = "demo"
create_document(name=doc)
create_body(doc_name=doc, name="Cover")
# Pad a 100×60×3 mm plate
create_sketch(doc_name=doc, body_name="Cover", name="CoverCS", plane="XY")
set_sketch_rectangle(doc_name=doc, sketch_name="CoverCS", x=0, y=0, width=100, height=60)
pad_sketch(doc_name=doc, body_name="Cover", sketch_name="CoverCS", length=3)

# Honeycomb-vent the central area; leave a 12 mm border plus a 15×15 mm island
# around the planned mounting hole at (85, 45).
create_sketch(doc_name=doc, body_name="Cover", name="HexCS", plane="XY")
hex_grid_sketch(
    doc_name=doc, sketch_name="HexCS",
    umin=12, umax=88, vmin=12, vmax=48,
    side=4, wall=1.5,
    exclusions=[[78, 92, 38, 52]],  # keep solid around the mounting hole
)
pocket_through(doc_name=doc, body_name="Cover", sketch_name="HexCS")

# Countersunk M3 clearance hole at (85, 45), on the XY_Plane
countersunk_hole(
    doc_name=doc, body_name="Cover", plane_tag="XY",
    u=85, v=45,
    shaft_r=1.7, csink_r=3.0,
    csink_depth=0.9, shaft_depth=4,
)

export_step(doc_name=doc, obj_names=["Cover"], path="/tmp/demo_cover.step")
capture_viewport()  # will include the PNG in the response
```

## When you inherit a document

Before editing someone else's FCStd:

1. `list_objects(doc_name=...)` — survey.
2. `describe_model(doc_name=...)` — volume + face count per body.
3. For each body you'll touch, dump its feature tree:
   ```python
   execute_code(code="""
   import FreeCAD, json
   doc = FreeCAD.getDocument('mydoc')
   tree = {b.Name: [f.Name for f in b.Group]
           for b in doc.Objects if b.TypeId == 'PartDesign::Body'}
   with open('/tmp/tree.json','w') as f:
       json.dump(tree, f, indent=2)
   """)
   ```
4. Read `/tmp/tree.json` — now you know what features chain from what, which
   is where the feature-order gotchas live.

## Where things live

- **Bridge addon (runs in FreeCAD)**: `addon/conjur3_pilot/rpc_server/rpc_server.py`
- **MCP server (runs separately)**: `src/conjur3_pilot/server.py`
- **Skill bundles** (workflow guidance for Claude): `skills/conjur3-pilot/`
- **Tests**: `tests/`
