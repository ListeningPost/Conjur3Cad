# Task {sample_id}: edit an existing part

Requested change:

{description}

Pictures of the starting part (iso, front, top, right), to open with your
image-reading tool:
{image_list}

The starting solid is a STEP file at `{input_step}`. It has no feature
history, so you edit it by adding and removing material.

## Method

**1. Load and look.** Import the part:

```python
import FreeCAD, Part
doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("Edit")
s = Part.Shape(); s.read("{input_step}")
o = doc.addObject("Part::Feature", "Input"); o.Shape = s
doc.recompute()
b = s.BoundBox
print(len(s.Solids), round(s.Volume, 3), b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax)
```

Open the provided pictures, then call `capture_views` on your session and
confirm the axes: which way is +X, +Y, +Z on this part. The request names
directions and faces in that frame.

**2. Locate exactly what the request refers to.** Use `list_faces` and
`list_edges` on `Input` to find the faces and edges involved, and read their
positions, normals, radii and areas. Use `cross_section` to see pockets and
bores. Write down which faces move, in which direction, by how much, and
what the new coordinates will be. Count the features the request names; if it
says "four pockets", find four.

**3. Make the change with solids.** Build tool solids (`create_primitive`,
or a sketch and pad) and combine them with `boolean`: `op="union"` to add material,
`op="cut"` to remove it. To move a wall inward, union a slab against it; to move it
outward, cut a slab. For anything the first-class tools cannot express, use
`execute_code` with the Part API. Do **not** move, rotate or rescale the
part: the result must stay in the input's coordinate frame.

**4. Verify the edit and only the edit.**

- `capture_views` again, and compare with the starting pictures: the
  requested change is visible, nothing else moved.
- `cross_section` through the changed region.
- The volume changed in the expected direction and by roughly the amount
  the request implies (added material → larger, removed → smaller).
- The bounding box changed only if the request implies it.

**5. Finalize.** Run the script below with `execute_code`, after setting
`OBJ_NAME` to the edited solid.

```python
{finalize_script}
```

It prints `FINALIZE {{...}}`. You are done only when it reports `"ok": true`.
If it lists `problems`, fix the model and run it again. Finish with a
two-line summary: what you changed, and what you were unsure of.
