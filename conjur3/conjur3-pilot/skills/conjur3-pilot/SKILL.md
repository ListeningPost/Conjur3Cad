---
name: conjur3-pilot
description: Drive a running FreeCAD GUI in real time via the `conjur3-pilot` MCP server. Every mutation returns a 3D viewport screenshot so you see what changed. Use this for any CAD modeling task — parts, assemblies, parametric tweaks, exports.
---

# Conjur3

You are piloting a **live** FreeCAD instance. The user's 3D viewport updates as you call tools. Use that feedback loop — check the screenshot after every mutating call and self-correct.

## Core workflow (document-first, parametric-first, screenshot-often)

1. **Connect.** Start with `ping` or `list_documents` to confirm the bridge. If the ping fails, tell the user to launch FreeCAD and switch to the "Conjur3" workbench — the RPC auto-starts.
2. **Create a document.** `create_document(name="...")` — everything below lives in it.
3. **Create a Body.** For anything beyond a single primitive, use `create_body`. PartDesign features (pad/pocket/revolve/fillet/pattern) **must** be inside a Body.
4. **Parameterize early.** Before the first sketch, create a spreadsheet (`create_spreadsheet` → `set_cell(... alias="wall_thickness")`) and bind feature dimensions to it (`set_expression("Pad001", "Length", "<<Variables>>.wall_thickness")`). This is the difference between a "dead" STL and a real parametric model the user can tweak.
5. **Sketch → feature.** `create_sketch(body_name=..., plane="XY")`, add geometry, then `pad_sketch` / `pocket_sketch` / `revolve_sketch`.
6. **Refine.** Use `list_edges` / `list_faces` to get 1-based indices, then `fillet_edges` / `chamfer_edges` / `shell_object` / `linear_pattern` / `polar_pattern`.
7. **Verify.** After any uncertain step, call `capture_viewport` (or rely on the auto-screenshot attached to mutating tools) and check: is the feature on the right body, the right face, the right depth? If not, `undo` and retry.
8. **Export.** `export_fcstd` for the full parametric doc; `export_step` for CAM-ready geometry; `export_stl` for print.

## Tool preference order

1. **First-class tools** (sketch/pad/pocket/fillet/pattern/...) — always prefer these.
2. **`create_primitive`** — for simple blocks/cylinders/spheres when you don't need a Body.
3. **`create_object`** — low-level, when you need a TypeId not covered above.
4. **`execute_code`** — last resort. Use only when nothing else works. Explain why in your reply.

## Hard rules

- **Never hardcode dimensions** you expect the user might want to change. Put them in a spreadsheet and bind via `set_expression`.
- **Always create a Body** before using any `PartDesign::*` tool (pad/pocket/revolve/fillet/chamfer/shell/pattern). Without a Body these fail or produce orphaned features.
- **Sketch plane = body origin plane.** Pass `body_name` to `create_sketch` and the sketch attaches to that body's XY/XZ/YZ plane. Sketches created without a body are loose and won't participate in PartDesign operations.
- **Edge / face indices are 1-based** and re-number when the topology changes. Call `list_edges` right before `fillet_edges`, not after several other mutations.
- **Undo is your friend.** If a call's screenshot looks wrong, `undo` before trying a different approach.
- **One document per task** unless the user asks for an assembly across files.
- **Repeated features → `linear_pattern` / `polar_pattern`, never a loop.** If you find yourself about to create N nearly-identical pockets/pads at a fixed pitch, stop. Create **one** feature, then call `linear_pattern(feature_names=[...], direction=..., length=..., occurrences=N)`. This is FreeCAD's name for what SolidWorks calls "Linear Pattern" and Fusion calls "Rectangular Pattern" — the canonical way to say "every N inches / mm, add a hole." If the within-unit spacing is non-uniform (e.g. EIA-310's 15.875 / 15.875 / 12.7 mm), create one feature per unique offset inside a single unit, then `linear_pattern` all of them together with `length = (U-1) * U_pitch` and `occurrences = U`.

## When uncertain

- Call `describe_model` to see what objects exist and their types.
- Call `get_object` for one specific object's properties.
- Call `set_view("Top")` or `set_view("Front")` + `capture_viewport` to look at geometry from a different angle before deciding where to cut.

## Sub-skills (invoke as needed)

- `skills/conjur3-pilot/enclosure/SKILL.md` — parametric electronics enclosures with lid + bosses.
- `skills/conjur3-pilot/gear/SKILL.md` — spur gears via involute profile (uses the woodbloks batch path).
- `skills/conjur3-pilot/fastener-hole/SKILL.md` — through/blind/counterbore/countersink holes at face features.
- `skills/conjur3-pilot/rack-frame/SKILL.md` — EIA-310 19" server racks (4-post, 1–45U).

## Example: a 60×40×20 enclosure, 3 mm walls, M3 corner bosses

```
create_document(name="Enclosure")
create_spreadsheet(name="Vars")
set_cell(cell="B1", value=60, alias="L")
set_cell(cell="B2", value=40, alias="W")
set_cell(cell="B3", value=20, alias="H")
set_cell(cell="B4", value=3, alias="wall")
create_body(name="Case")
create_sketch(body_name="Case", plane="XY", name="Outline")
add_sketch_rectangle(sketch_name="Outline", x=-30, y=-20, width=60, height=40)
pad_sketch(body_name="Case", sketch_name="Outline", length=20, name="Shell_Pad")
# Bind to variables so the user can resize.
set_expression(obj_name="Shell_Pad", property_path="Length", expression="<<Vars>>.H")
list_faces(obj_name="Shell_Pad")   # find the top face
shell_object(body_name="Case", base_name="Shell_Pad", faces=[TOP_FACE_INDEX], thickness=3)
# ... bosses, fastener holes, etc.
export_step(obj_names=["Case"], path="/tmp/enclosure.step")
```

After each step the tool returns a thumbnail. If a step's thumbnail doesn't match your intent, `undo` and adjust.

## High-level helpers (promoted from common `execute_code` patterns)

These wrap moves that used to require hand-rolled Python.  Prefer them over
the old patterns in the cells below.

| Helper | Use when |
|---|---|
| `rotate_about_axis(doc, obj, pivot, axis, angle_deg)` | Animating a door around its hinge; rotating a sub-assembly around a mount point; any rotation where the pivot is **not** the object's own origin. |
| `pocket_through(doc, body, sketch, margin=1.0)` | Cutting cleanly through a plate — no more guessing `midplane` / `reversed` / `depth`. |
| `pocket_blind(doc, body, sketch, depth, reverse=False)` | Blind pocket from one face — explicit direction, no midplane. |
| `hex_grid_sketch(doc, sketch, umin, umax, vmin, vmax, side, wall, exclusions)` | Populating a panel with honeycomb ventilation in one call.  `exclusions=[[u0,u1,v0,v1],...]` reserves solid islands for mounting hardware. |
| `countersunk_hole(doc, body, plane_tag, u, v, shaft_r, csink_r, csink_depth, shaft_depth)` | Clearance hole + countersink in one call — the standard flat-head fastener recipe. |
| `clear_sketch_geometry(doc, sketch)` | Wipe a sketch before redrawing (e.g. resizing a padded panel). |
| `set_sketch_rectangle(doc, sketch, x, y, w, h, clear=True)` | Replace a sketch with a single rectangle in one shot. |
| `get_origin_plane(doc, body, plane_tag)` | Get the actual plane name (e.g. `YZ_Plane032`) before attaching a sketch programmatically. |

## Timeouts

Every tool that touches heavy geometry accepts `timeout_ms`.  Use it when:

- STEP export of a 50-body assembly: `timeout_ms=300000` (5 min).
- Hex mesh on a 500×300 mm panel: `timeout_ms=120000` (2 min).
- `execute_code` frame-render loops: bump proportionally.

If a call times out, state may still be mutating on the GUI side — wait a
few seconds and re-query with `ping` / `list_objects` before retrying.
Thanks to per-call response tokens, a timed-out call's late result will
**not** leak into your next call's return value (old bug, now fixed).

## See also

`AGENTS.md` at the repo root — longer field guide with coordinate conventions,
feature-order traps, and a worked example end-to-end script.
