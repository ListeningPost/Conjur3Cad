# Conjur3 benchmark finalize step. Runs INSIDE FreeCAD (via the execute_code
# tool, or the runner's own check). Validates the solid, optionally moves it to
# the benchmark's canonical pose, writes the STEP file, re-reads it to confirm
# it round-trips, and prints one JSON line.
#
# The runner fills OUT_PATH and CANONICAL_POSE; the agent sets OBJ_NAME (and
# FLIP_Z if the part's mounting face ended up on top).
import json

import FreeCAD
import Part

OBJ_NAME = "Body"            # the object to export
OUT_PATH = "__OUT_PATH__"
CANONICAL_POSE = __CANONICAL_POSE__   # generation: True, editing: False
FLIP_Z = False               # True → rotate 180° about X after posing


def _bbox(shape):
    # An untessellated shape's BoundBox can overshoot by several percent on
    # curved faces; meshing it first makes the box tight. (optimalBoundingBox
    # would be exact, but it crashes FreeCAD 0.21 on Python 3.12.)
    try:
        shape.tessellate(0.05)
    except Exception:
        pass
    return shape.BoundBox


def _report(shape):
    bb = _bbox(shape)
    return {
        "is_valid": bool(shape.isValid()),
        "solids": len(shape.Solids),
        "shells": len(shape.Shells),
        "all_shells_closed": all(s.isClosed() for s in shape.Shells) if shape.Shells else False,
        "faces": len(shape.Faces),
        "volume_mm3": round(float(shape.Volume), 3),
        "bbox_mm": [round(bb.XLength, 3), round(bb.YLength, 3), round(bb.ZLength, 3)],
        "bbox_center": [round(bb.Center.x, 3), round(bb.Center.y, 3), round(bb.Center.z, 3)],
    }


def _canonical(shape):
    """Bounding-box centre at the origin, extents ordered Lx >= Ly >= Lz, using
    rotations only (never a mirror)."""
    bb = _bbox(shape)
    ext = [bb.XLength, bb.YLength, bb.ZLength]
    order = sorted(range(3), key=lambda i: -ext[i])       # stable: ties keep axis order
    rows = [[0.0, 0.0, 0.0] for _ in range(3)]
    for new_axis, old_axis in enumerate(order):
        rows[new_axis][old_axis] = 1.0
    det = (rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
           - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
           + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0]))
    if det < 0:                                            # odd permutation → fix handedness
        rows[2] = [-v for v in rows[2]]
    m = FreeCAD.Matrix(rows[0][0], rows[0][1], rows[0][2], 0,
                       rows[1][0], rows[1][1], rows[1][2], 0,
                       rows[2][0], rows[2][1], rows[2][2], 0,
                       0, 0, 0, 1)
    shape = shape.transformed(m, True)
    if FLIP_Z:
        shape = shape.rotated(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(1, 0, 0), 180)
    c = _bbox(shape).Center
    return shape.translated(FreeCAD.Vector(-c.x, -c.y, -c.z))


def finalize():
    doc = FreeCAD.ActiveDocument
    obj = doc.getObject(OBJ_NAME) if doc else None
    if obj is None or getattr(obj, "Shape", None) is None or obj.Shape.isNull():
        return {"ok": False, "error": f"object {OBJ_NAME!r} not found or has no shape"}
    shape = obj.Shape.copy()
    problems = []
    if not shape.isValid():
        problems.append("shape is not valid (self-intersection or bad topology)")
    if len(shape.Solids) != 1:
        problems.append(f"expected exactly 1 solid, found {len(shape.Solids)} "
                        "(fuse separate bodies, or remove leftover construction solids)")
    if shape.Shells and not all(s.isClosed() for s in shape.Shells):
        problems.append("a shell is open (not watertight)")
    if shape.Volume <= 0:
        problems.append("volume is not positive")
    if problems:
        return {"ok": False, "problems": problems, "shape": _report(shape)}
    if CANONICAL_POSE:
        shape = _canonical(shape)
    shape.exportStep(OUT_PATH)
    back = Part.Shape()
    back.read(OUT_PATH)
    rt = _report(back)
    ok = rt["is_valid"] and rt["solids"] == 1 and rt["all_shells_closed"]
    return {"ok": ok, "path": OUT_PATH, "written": _report(shape), "reread": rt}


print("FINALIZE " + json.dumps(finalize()))
