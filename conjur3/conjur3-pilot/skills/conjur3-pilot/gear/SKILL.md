---
name: conjur3-pilot-gear
description: Build spur gears with correct involute tooth profiles. For quick live gears, sketch the profile manually; for precise gears, use the woodbloks batch path.
---

# Spur Gear

## Quick path (live, approximate teeth)

1. Parameters: `module m`, `teeth z`, `face_width`. Pitch diameter `d = m * z`.
2. Create Body. Sketch on XY: add `add_sketch_circle(cx=0, cy=0, radius=d/2)` for the pitch circle (reference) — use a separate sketch (`construction_only=False` so it still builds) OR omit and draw teeth directly.
3. One-tooth sketch: polyline approximating the involute flank (see formula below) + tooth tip arc + root fillet.
4. `pad_sketch(length=face_width)` → get a single tooth.
5. `polar_pattern(feature=[Tooth_Pad], axis="Z", angle=360, occurrences=z)`.
6. Bore/hub: a concentric sketch + `pocket_sketch`.

The polar pattern + approximated flank is good enough for visualization and 3D-printed gears with ≤20° pressure angle and ≥12 teeth. For higher-precision gears use the woodbloks path.

## Precise path (batch replay)

The woodbloks-ai package implements a correct involute gear profile. Call:

```
run_design_program(program_path="/path/to/spur_gear_design.json", out_fcstd="/tmp/gear.FCStd", out_step="/tmp/gear.step")
```

Design program ops to emit (see `woodbloks/ops/schema.py`):
- `new_body`
- `new_sketch` (XY plane)
- `draw_spur_gear_root` or `draw_involute_gear_profile` with `{module, teeth, pressure_angle, profile_shift}`
- `pad`
- `export_step`

Then open the resulting `.FCStd` in FreeCAD and continue editing live with the other tools.

## Involute flank math (if sketching manually)

For a gear of module `m`, `z` teeth, pressure angle `α` (typically 20°):
- Base circle radius: `r_b = (m * z / 2) * cos(α)`
- Addendum circle: `r_a = (m * z / 2) + m`
- Dedendum circle: `r_d = (m * z / 2) - 1.25 * m`
- Parametric flank: `x(t) = r_b * (cos(t) + t * sin(t))`, `y(t) = r_b * (sin(t) - t * cos(t))`, for `t ∈ [0, t_max]` where `t_max = sqrt((r_a/r_b)² - 1)`.

Sample ~20 points per flank; mirror across the tooth centerline; add a small root fillet between adjacent teeth.
