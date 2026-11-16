---
name: conjur3-pilot-fastener-hole
description: Add parametric fastener holes (through, blind, counterbore, countersink) to existing features. Always drives through sketches so the hole participates in the PartDesign tree.
---

# Fastener Hole

**For grids / rows of holes at a fixed pitch, use `linear_pattern` (NOT a loop of pockets).**
Define one hole (single-circle sketch + `pocket_sketch`), then:

```
linear_pattern(
    body_name=..., feature_names=["Hole1"],
    direction="Z", length=(N-1)*pitch, occurrences=N,
)
```

For a 2-D grid, stack two patterns: the row first, then pattern the row in the perpendicular direction. For EIA-310 racks (3 holes per U at 15.875 / 15.875 / 12.7 mm offsets), define 3 holes inside the first U, then pattern all 3 with `length=(U-1)*44.45` and `occurrences=U`.

Given a target face (1-based index from `list_faces`) on an existing pad/feature:

## Through hole

1. `create_sketch(body_name=..., plane="XY", name="HolePattern")` — or attach to the target face via `execute_code` if needed.
2. `add_sketch_circle(cx=X, cy=Y, radius=d/2)` for each hole center.
3. `pocket_sketch(body_name, sketch_name="HolePattern", depth=H + 1)` → passes fully through.

## Blind hole

Same as through, but `depth = target_depth` (minus a safety margin to avoid breakthrough).

## Counterbore (M3: head ⌀5.5 × ≥3 deep, clearance ⌀3.4)

Two sketches, two pockets in order:
1. Clearance sketch: circles at ⌀3.4/2. Pocket depth = full thickness.
2. Counterbore sketch (same centers): circles at ⌀5.5/2. Pocket depth = 3.0.

## Countersink (M3: head ⌀6 × 90°)

1. Through clearance pocket at ⌀3.4/2.
2. A revolved or lofted feature for the conical seat, OR (simpler) two coaxial circles lofted:
   - Sketch1 at depth 0: circle ⌀6/2.
   - Sketch2 at depth 3: circle ⌀3.4/2.
   - `loft_sketches` (if available; else approximate with `chamfer_edges` on the outer pocket edge).

## Parameterization

Put `hole_d`, `head_d`, `head_depth`, `cs_angle` into the main `Vars` spreadsheet. Then `set_expression` each pocket's `Length` to bind.

Verify with `list_edges` + `capture_viewport` — countersinks should show a clean conical face; counterbores a stepped cylinder.
