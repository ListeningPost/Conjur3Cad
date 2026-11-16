---
name: conjur3-pilot-enclosure
description: Build parametric electronics/project enclosures in FreeCAD with walls, lid seat, corner bosses, and fastener holes. Use when the user asks for a "box", "case", "enclosure", or similar.
---

# Parametric Enclosure

Produce a clean, parametric enclosure that the user can resize by editing one spreadsheet.

## Parameters (always put in a spreadsheet named `Vars`)

| alias | meaning | typical |
|---|---|---|
| `L` | outer length (X) | 60 mm |
| `W` | outer width (Y) | 40 mm |
| `H` | outer height (Z) | 20 mm |
| `wall` | wall thickness | 2–3 mm |
| `lip` | lid lip depth | 1.5 mm |
| `boss_d` | boss outer diameter | 5 mm |
| `hole_d` | fastener through-hole diameter | 3.2 mm (M3 clearance) |
| `fillet_r` | outer edge fillet | 1–2 mm |

## Steps

1. Create document + Body + spreadsheet; set all cells with aliases.
2. Sketch the outer rectangle on XY plane, centered at origin: `add_sketch_rectangle(x=-L/2, y=-W/2, width=L, height=W)`. Bind to aliases via `set_expression` *after* creating the sketch (FreeCAD currently requires hardcoded geometry, then expression-bind feature Lengths).
3. `pad_sketch(length=H)` → bind `Length` to `<<Vars>>.H`.
4. `list_faces` on the pad → identify the top face (largest XY area).
5. `shell_object(base=pad, faces=[top_face], thickness=wall)` → bind `Value` to `<<Vars>>.wall`.
6. Outer fillet (optional): `list_edges` → `fillet_edges(edges=[vertical_corner_edges], radius=fillet_r)`.
7. Corner bosses: add a sketch on the inside-bottom face with 4 circles at `(±(L/2-wall-boss_d/2), ±(W/2-wall-boss_d/2))`. `pad_sketch(length=H-wall-lip)`.
8. Fastener holes: new sketch at same positions with `hole_d/2`. `pocket_sketch(depth=...)`.

## Verification

- After step 3: screenshot should show a solid box.
- After step 5: screenshot should show an open-topped shell.
- After step 7: four pillars inside the box.
- After step 8: four dark dots on the pillar tops (the through-holes).

If any step looks wrong, `undo` and retry with different face/edge indices.

## Finishing

- `set_view("Isometric")` + `capture_viewport` for the user.
- `export_step` for CAM, `export_stl` for print, `export_fcstd` for the parametric source.
