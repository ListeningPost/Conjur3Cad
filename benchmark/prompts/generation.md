# Task {sample_id}: build a part from an engineering drawing

{description}

Drawing image(s), to open with your image-reading tool:
{image_list}

## Method

**1. Read the drawing before touching CAD.** Open every image. Then write
down, in your own words:

- which views are shown and how they relate (which is top, front, side;
  whether a view is a section or a detail), and the units and scale;
- the overall envelope: length, width and height;
- every feature with its dimensions and where it sits: holes (diameter,
  through or blind, depth, position, how many), slots, pockets, bosses, ribs,
  steps, fillets, chamfers, patterns and their pitch;
- symmetry you can exploit, and anything you had to infer because it is not
  dimensioned.

**2. Plan the feature order.** Base solid first (the largest pad or
revolve), then added material, then cuts, then patterns and mirrors, then
fillets and chamfers. Choose the origin and sketch planes so the drawing's
dimensions can be typed in directly.

**3. Build one feature at a time.** After each one, check the returned
screenshot for shape and the `measurements` block for size. After the base
solid, the bounding box must match the drawing's envelope; fix it now if it
does not.

**4. Compare against the drawing, view by view.** When the main features
exist, call `capture_views`. Put each returned view next to the matching
drawing view and check: outline, number of holes, where each feature sits
relative to the edges, and which side features are on. If the drawing's side
view shows the opposite face from yours, capture `Left`, `Back` or `Bottom`
instead of assuming the feature is wrong. For anything internal that the
drawing shows with hidden lines or a section view, call `cross_section` at
the same cut and compare the red profile with the drawing.

**5. Fix what differs, then compare again.** Repeat step 4 once after your
last change, so the final model has been looked at from all sides.

**6. Finalize.** Run the script below with `execute_code`, after setting
`OBJ_NAME` to your final solid (for a PartDesign body, the body's name). If
the part has an obvious mounting or base face and it is on top after posing,
run it again with `FLIP_Z = True`.

```python
{finalize_script}
```

It prints `FINALIZE {{...}}`. You are done only when it reports `"ok": true`.
If it lists `problems`, fix the model and run it again. Finish with a
two-line summary: what you built, and what you were unsure of.
