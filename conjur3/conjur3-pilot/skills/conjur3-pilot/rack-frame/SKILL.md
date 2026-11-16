---
name: conjur3-pilot-rack-frame
description: Build EIA-310 19-inch server racks (4-post, configurable U-height). Ports the woodbloks-ai rk-gen-001 recipe.
---

# 19" Server Rack (EIA-310)

Produces a 4-post open rack with square-hole mounting strips, top/bottom channels, and leveling feet.

## Parameters (spreadsheet `Vars`)

| alias | meaning | typical |
|---|---|---|
| `U` | height in rack units | 42 |
| `U_mm` | 1U in mm | 44.45 |
| `W_ext` | outer width | 600 mm |
| `D_ext` | outer depth | 1000 mm |
| `post_sq` | post square-tube size | 40 mm |
| `wall` | tube wall thickness | 2 mm |
| `hole_w` | square-hole width | 9.5 mm |
| `hole_p` | hole pitch pattern | 15.875 / 15.875 / 12.7 mm (EIA pattern) |
| `foot_h` | leveling-foot stem | 25 mm |

Total height: `H = U * U_mm + top_frame + bottom_frame + foot_h`.

## Strategy

For a model this size (~12 parts × many holes each), **prefer the batch path**:

```
run_design_program(
    program_path="/path/to/woodbloks-ai/designs/rk-gen-001.json",
    out_fcstd="/tmp/rack.FCStd",
    out_step="/tmp/rack.step",
)
```

Then open `/tmp/rack.FCStd` in FreeCAD and continue editing live with the other tools (add side panels, cable management, etc).

## Live path (if building from scratch)

1. Body: `Rack_Frame`.
2. Sketches for 4 vertical posts (square tubes) — pad to full height.
3. One hole-pattern sketch on the inside face of the front-left post. Use `linear_pattern` with `occurrences = U * 3` (3 holes per U) and the EIA `15.875 / 15.875 / 12.7` pitch.
4. Mirror the hole pattern to the 3 other posts (either by 4 separate sketches or by `mirror_feature` across XZ/YZ planes).
5. Top and bottom horizontal frames connecting the posts.
6. 4× leveling feet — separate body; place with `place_duplicate` (or 4 separate Parts).
7. `export_step` the whole set; keep `.FCStd` as the parametric source.

## Sanity check

- `measure(kind="bounding_box")` on `Rack_Frame` should read ≈ `W_ext × D_ext × H`.
- `describe_model` should list ≥ 10 objects and ≥ 100 features (holes).
- `set_view("Front")` + `capture_viewport` should show a familiar ladder-of-holes silhouette.
