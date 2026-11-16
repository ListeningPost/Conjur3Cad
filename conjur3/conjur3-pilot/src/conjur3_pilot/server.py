"""Conjur3 — FastMCP server.

Each @mcp.tool is a thin wrapper around a PilotClient RPC method. Mutating
tools automatically append a viewport screenshot to the response so the LLM
sees the 3D result of its last edit.

Run with:   uvx --from . conjur3-pilot     (or) python -m conjur3_pilot
Register with Claude Code via `.mcp.json` or `claude mcp add`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ImageContent, TextContent

from .rpc_client import PilotClient


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("conjur3_pilot")


_CLIENT: PilotClient | None = None
_ONLY_TEXT = False


def _client() -> PilotClient:
    global _CLIENT
    if _CLIENT is None:
        host = os.environ.get("FREECAD_PILOT_HOST", "localhost")
        port = int(os.environ.get("FREECAD_PILOT_PORT", "9875"))
        _CLIENT = PilotClient(host=host, port=port)
        if not _CLIENT.ping():
            log.warning(
                "Conjur3 RPC not reachable at %s:%d. Launch FreeCAD, switch to the "
                "Conjur3 workbench — the server should auto-start.",
                host, port,
            )
    return _CLIENT


@asynccontextmanager
async def lifespan(_: FastMCP) -> AsyncIterator[dict]:
    _client()  # best-effort warm-up
    try:
        yield {}
    finally:
        if _CLIENT is not None:
            _CLIENT.disconnect()


mcp = FastMCP(
    "Conjur3",
    instructions=(
        "Live parametric CAD piloting. Create a document; create a PartDesign body; "
        "add sketches; pad/pocket/revolve; fillet/chamfer/shell; pattern; boolean; "
        "export. After every mutation a viewport screenshot is attached so you "
        "can visually verify the result. Prefer first-class tools over execute_code."
    ),
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _summary(label: str, res: dict | list | str | bool) -> str:
    if isinstance(res, (dict, list)):
        return f"{label}: {json.dumps(res, default=str)[:2000]}"
    return f"{label}: {res}"


def _wrap(label: str, res: Any, *, with_screenshot: bool = True) -> list:
    content: list = [TextContent(type="text", text=_summary(label, res))]
    if with_screenshot and not _ONLY_TEXT:
        try:
            b64 = _client().capture_viewport("Isometric")
            if b64:
                content.append(ImageContent(type="image", mimeType="image/png", data=b64))
        except Exception as e:
            log.debug("screenshot skipped: %s", e)
    return content


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@mcp.tool()
def ping(ctx: Context) -> list[TextContent]:
    """Check the Conjur3 bridge is reachable. Returns FreeCAD version info."""
    return [TextContent(type="text", text=_summary("ping", _client()._call("ping")))]


@mcp.tool()
def list_documents(ctx: Context) -> list[TextContent]:
    """List open FreeCAD documents by name."""
    return [TextContent(type="text", text=_summary("documents", _client().list_documents()))]


@mcp.tool()
def create_document(ctx: Context, name: str = "Untitled") -> list:
    """Create a new, empty FreeCAD document and make it active."""
    return _wrap("create_document", _client().create_document(name))


@mcp.tool()
def switch_document(ctx: Context, doc_name: str) -> list[TextContent]:
    """Set the active document by name."""
    return [TextContent(type="text", text=_summary("switch_document", _client().switch_document(doc_name)))]


@mcp.tool()
def save_document(ctx: Context, doc_name: str | None = None, path: str | None = None) -> list[TextContent]:
    """Save the document. Provide `path` to save-as. Without `path` saves in place (requires prior saveAs)."""
    return [TextContent(type="text", text=_summary("save_document", _client().save_document(doc_name, path)))]


@mcp.tool()
def close_document(ctx: Context, doc_name: str) -> list[TextContent]:
    """Close a FreeCAD document. Does not save."""
    return [TextContent(type="text", text=_summary("close_document", _client().close_document(doc_name)))]


@mcp.tool()
def undo(ctx: Context, doc_name: str | None = None) -> list:
    """Undo the last change to the document."""
    return _wrap("undo", _client().undo(doc_name))


@mcp.tool()
def redo(ctx: Context, doc_name: str | None = None) -> list:
    """Redo the last undone change."""
    return _wrap("redo", _client().redo(doc_name))


# ---------------------------------------------------------------------------
# Snapshots (feature-tree checkpoint store)
# ---------------------------------------------------------------------------


@mcp.tool()
def snapshot(ctx: Context, label: str, doc_name: str | None = None) -> list[TextContent]:
    """Save a named milestone snapshot of the current document.

    Stored under `<doc>.snapshots/milestones/<label>.FCStd` beside the live
    file. Unbounded (does not evict like the auto ring) and overwrites if the
    label already exists. Use this to bookmark known-good states before risky
    edits — restore later via `restore_snapshot(milestone=...)`.

    Requires the document to have been saved with a path first.
    """
    return [TextContent(type="text", text=_summary("snapshot", _client().snapshot(doc_name, label)))]


@mcp.tool()
def list_snapshots(ctx: Context, doc_name: str | None = None) -> list[TextContent]:
    """List ring snapshots (auto, last 30 mutations) and named milestones.

    Returns `{ring: [{n, action, params, timestamp, size, sha256}], milestones: [...]}`,
    newest-first within each list. Use `n` from a ring entry or `label` from a
    milestone with `restore_snapshot` to roll back.
    """
    return [TextContent(type="text", text=_summary("list_snapshots", _client().list_snapshots(doc_name)))]


@mcp.tool()
def restore_snapshot(
    ctx: Context,
    doc_name: str | None = None,
    n: int | None = None,
    milestone: str | None = None,
) -> list:
    """Replace the live document with a snapshot. Specify exactly one of `n` or `milestone`.

    Closes the current document, copies the snapshot file over the live path,
    and reopens. The current state is NOT preserved automatically — call
    `snapshot(label)` first if you want to bookmark before restoring.
    """
    return _wrap("restore_snapshot", _client().restore_snapshot(doc_name, n, milestone))


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


@mcp.tool()
def describe_model(ctx: Context, doc_name: str | None = None) -> list[TextContent]:
    """Get a compact summary of the current model — object tree, volumes, face/edge counts."""
    return [TextContent(type="text", text=_summary("describe_model", _client().describe_model(doc_name)))]


@mcp.tool()
def list_objects(ctx: Context, doc_name: str | None = None) -> list[TextContent]:
    """List {Name, Label, TypeId} for every object in the document."""
    return [TextContent(type="text", text=_summary("list_objects", _client().list_objects(doc_name)))]


@mcp.tool()
def get_object(ctx: Context, doc_name: str, obj_name: str) -> list[TextContent]:
    """Full serialized snapshot of one object — properties, shape stats, view settings."""
    return [TextContent(type="text", text=_summary("get_object", _client().get_object(doc_name, obj_name)))]


@mcp.tool()
def list_faces(ctx: Context, doc_name: str, obj_name: str) -> list[TextContent]:
    """List faces by index (1-based) with area + centroid. Use indices as inputs to fillet/chamfer/shell."""
    return [TextContent(type="text", text=_summary("list_faces", _client().list_faces(doc_name, obj_name)))]


@mcp.tool()
def list_edges(ctx: Context, doc_name: str, obj_name: str) -> list[TextContent]:
    """List edges by index (1-based) with length. Use indices as inputs to fillet/chamfer."""
    return [TextContent(type="text", text=_summary("list_edges", _client().list_edges(doc_name, obj_name)))]


@mcp.tool()
def measure(
    ctx: Context,
    doc_name: str,
    obj_name: str,
    kind: Literal["bounding_box", "volume", "area", "center_of_mass"] = "bounding_box",
) -> list[TextContent]:
    """Measure a geometric property of an object."""
    return [TextContent(type="text", text=_summary("measure", _client().measure(doc_name, obj_name, kind)))]


# ---------------------------------------------------------------------------
# Viewport
# ---------------------------------------------------------------------------


@mcp.tool()
def capture_viewport(
    ctx: Context,
    view_name: Literal["Isometric", "Front", "Top", "Right", "Back", "Left", "Bottom", "Dimetric", "Trimetric"] = "Isometric",
    width: int | None = None,
    height: int | None = None,
    focus_object: str | None = None,
    timeout_ms: int | None = None,
) -> list:
    """Take a screenshot of the active 3D view. Returns both text confirmation and the PNG.

    The server auto-recovers the ``ActiveView`` when it's unset right after a
    document open/swap, so this now works reliably after ``openDocument``.
    ``timeout_ms`` overrides the default per-call GUI timeout (30 s).
    """
    b64 = _client().capture_viewport(view_name, width, height, focus_object, timeout_ms)
    out: list = [TextContent(type="text", text=f"capture_viewport: view={view_name} focus={focus_object or 'all'}")]
    if b64:
        out.append(ImageContent(type="image", mimeType="image/png", data=b64))
    else:
        out.append(TextContent(type="text", text="(no screenshot available — is the active view a 3D view?)"))
    return out


@mcp.tool()
def set_view(
    ctx: Context,
    view_name: Literal["Isometric", "Front", "Top", "Right", "Back", "Left", "Bottom", "Dimetric", "Trimetric"] = "Isometric",
) -> list:
    """Orient the 3D view to a standard preset and fit-all."""
    return _wrap("set_view", _client().set_view(view_name))


@mcp.tool()
def fit_all(ctx: Context) -> list:
    """Fit the 3D view to all objects."""
    return _wrap("fit_all", _client().fit_all())


@mcp.tool()
def zoom_object(ctx: Context, doc_name: str, obj_name: str) -> list:
    """Frame the 3D view on one specific object."""
    return _wrap("zoom_object", _client().zoom_object(doc_name, obj_name))


@mcp.tool()
def set_visibility(
    ctx: Context,
    obj_name: str,
    visible: bool = True,
    doc_name: str | None = None,
) -> list:
    """Show or hide a single object in the 3D viewport."""
    return _wrap("set_visibility",
                 _client().set_visibility(doc_name, obj_name, visible))


@mcp.tool()
def isolate_object(
    ctx: Context,
    obj_names: list[str] | str,
    doc_name: str | None = None,
) -> list:
    """Hide every object in the doc except those listed.

    Returns a `prior_visibility` map (`{name: bool}`) — pass it to
    `restore_visibility` to put things back exactly as they were. Useful
    when the part you want to inspect is occluded by other geometry.
    """
    return _wrap("isolate_object",
                 _client().isolate_object(doc_name, obj_names))


@mcp.tool()
def restore_visibility(
    ctx: Context,
    prior_visibility: dict[str, bool],
    doc_name: str | None = None,
) -> list:
    """Restore Visibility flags from a {name: bool} map (typically the one
    returned by `isolate_object`)."""
    return _wrap("restore_visibility",
                 _client().restore_visibility(doc_name, prior_visibility))


@mcp.tool()
def capture_views(
    ctx: Context,
    views: list[str] | str | None = None,
    focus_object: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> list:
    """Capture the model from multiple standard views in one call.

    Default sequence: Top, Front, Right, Isometric. The camera is restored
    to Isometric afterwards so the user's working view isn't changed.

    For a long thin part where Iso alone is uninformative, this is the
    fastest way to actually see what was built.
    """
    res = _client().capture_views(views, focus_object, width, height)
    label = views if views else "Top,Front,Right,Isometric"
    out: list = [TextContent(
        type="text",
        text=f"capture_views: views={label} focus={focus_object or 'all'}",
    )]
    if isinstance(res, dict) and res.get("success") and "images" in res:
        for v_name, payload in res["images"].items():
            if isinstance(payload, str):
                out.append(TextContent(type="text", text=f"--- {v_name} ---"))
                out.append(ImageContent(type="image", mimeType="image/png", data=payload))
            else:
                err = payload.get("error", "unknown error") if isinstance(payload, dict) else str(payload)
                out.append(TextContent(type="text", text=f"{v_name}: error: {err}"))
    else:
        out.append(TextContent(type="text", text=json.dumps(res, default=str)))
    return out


@mcp.tool()
def cross_section(
    ctx: Context,
    obj_name: str,
    plane: Literal["XY", "XZ", "YZ"] = "XY",
    offset: float = 0.0,
    doc_name: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> list:
    """Slice a part with a plane and screenshot the resulting profile.

    `plane='XY'` cuts at z=offset (top-down view), 'XZ' at y=offset (front),
    'YZ' at x=offset (right). The intersection edges are drawn red so they're
    visible against the rest of the model. Returns a JSON summary
    (edge_count, wire_count, per-wire areas) plus the screenshot.

    Use this to verify internal voids, bores, and pocket geometry that's
    invisible from outside views — e.g. confirm a Tesla-valve channel
    actually has the meander shape it's supposed to.
    """
    res = _client().cross_section(doc_name, obj_name, plane, offset, width, height)
    out: list = [TextContent(
        type="text",
        text=f"cross_section: {plane}={offset} obj={obj_name}",
    )]
    if isinstance(res, dict):
        b64 = res.pop("image", None)
        out.append(TextContent(type="text", text=json.dumps(res, default=str)))
        if b64:
            out.append(ImageContent(type="image", mimeType="image/png", data=b64))
    else:
        out.append(TextContent(type="text", text=str(res)))
    return out


@mcp.tool()
def query_sketch(
    ctx: Context,
    sketch_name: str,
    doc_name: str | None = None,
) -> list:
    """Inspect a sketch's resolved geometry: closed face count, area of
    each face, open-chain count, total enclosed area.

    Run this BEFORE `pad_sketch` / `pocket_through` to confirm the sketch
    forms the closed profile you intended. Catches:
      - polylines that didn't close
      - wires with tiny coincident-but-not-snapped gaps
      - winding issues that produce a smaller face than expected
    """
    return _wrap("query_sketch",
                 _client().query_sketch(doc_name, sketch_name))


# ---------------------------------------------------------------------------
# Bodies + primitives
# ---------------------------------------------------------------------------


@mcp.tool()
def create_body(ctx: Context, doc_name: str | None = None, name: str = "Body") -> list:
    """Create a PartDesign Body — the container for sketches + features."""
    return _wrap("create_body", _client().create_body(doc_name, name))


@mcp.tool()
def create_primitive(
    ctx: Context,
    kind: Literal["box", "cylinder", "sphere", "cone", "torus"],
    doc_name: str | None = None,
    name: str | None = None,
    properties: dict[str, Any] | None = None,
    placement: dict[str, Any] | None = None,
) -> list:
    """Add a Part primitive (box/cylinder/sphere/cone/torus).

    `properties` maps FreeCAD property names to values (e.g. `{"Length": 30, "Width": 20, "Height": 10}` for a Box).
    `placement` is `{Base: {x,y,z}, Rotation: {Axis: {x,y,z}, Angle: deg}}`.
    """
    return _wrap("create_primitive", _client().create_primitive(doc_name, kind, name, properties or {}, placement or {}))


@mcp.tool()
def transform_object(
    ctx: Context,
    doc_name: str,
    obj_name: str,
    placement: dict[str, Any] | None = None,
    translation: dict[str, float] | None = None,
    rotation_deg: float | None = None,
    axis: dict[str, float] | None = None,
) -> list:
    """Move or rotate an object. Use `placement` for absolute; `translation`/`rotation_deg`+`axis` for relative."""
    return _wrap(
        "transform_object",
        _client().transform_object(doc_name, obj_name, placement or {}, translation or {}, rotation_deg, axis or {}),
    )


@mcp.tool()
def delete_object(ctx: Context, doc_name: str, obj_name: str) -> list:
    """Delete an object (undoable)."""
    return _wrap("delete_object", _client().delete_object(doc_name, obj_name))


# ---------------------------------------------------------------------------
# Sketch
# ---------------------------------------------------------------------------


@mcp.tool()
def create_sketch(
    ctx: Context,
    doc_name: str | None = None,
    body_name: str | None = None,
    plane: Literal["XY", "XZ", "YZ"] = "XY",
    name: str | None = None,
) -> list:
    """Create a Sketcher sketch. If `body_name` is given, the sketch is inside that PartDesign Body on its origin plane."""
    return _wrap("create_sketch", _client().create_sketch(doc_name, body_name, plane, name))


@mcp.tool()
def add_sketch_rectangle(
    ctx: Context, doc_name: str, sketch_name: str, x: float, y: float, width: float, height: float,
) -> list:
    """Add 4 line segments forming a rectangle with bottom-left at (x, y)."""
    return _wrap("add_sketch_rectangle", _client().add_sketch_rectangle(doc_name, sketch_name, x, y, width, height))


@mcp.tool()
def add_sketch_circle(
    ctx: Context, doc_name: str, sketch_name: str, cx: float, cy: float, radius: float,
) -> list:
    """Add a circle to a sketch."""
    return _wrap("add_sketch_circle", _client().add_sketch_circle(doc_name, sketch_name, cx, cy, radius))


@mcp.tool()
def add_sketch_line(
    ctx: Context, doc_name: str, sketch_name: str, x1: float, y1: float, x2: float, y2: float,
) -> list:
    """Add a line segment to a sketch."""
    return _wrap("add_sketch_line", _client().add_sketch_line(doc_name, sketch_name, x1, y1, x2, y2))


@mcp.tool()
def add_sketch_polyline(
    ctx: Context, doc_name: str, sketch_name: str, points: list[list[float]], closed: bool = True,
) -> list:
    """Add a polyline (list of [x, y] points). `closed=True` closes the loop."""
    return _wrap("add_sketch_polyline", _client().add_sketch_polyline(doc_name, sketch_name, points, closed))


# ---------------------------------------------------------------------------
# PartDesign features
# ---------------------------------------------------------------------------


@mcp.tool()
def pad_sketch(
    ctx: Context,
    doc_name: str,
    body_name: str,
    sketch_name: str,
    length: float = 10.0,
    reversed: bool = False,
    midplane: bool = False,
    name: str | None = None,
) -> list:
    """Pad (extrude) a sketch inside a PartDesign Body. `midplane=True` extrudes symmetrically about the sketch plane."""
    return _wrap(
        "pad_sketch",
        _client().pad_sketch(doc_name, body_name, sketch_name, length, reversed, midplane, name),
    )


@mcp.tool()
def pocket_sketch(
    ctx: Context,
    doc_name: str,
    body_name: str,
    sketch_name: str,
    depth: float = 10.0,
    reversed: bool = False,
    midplane: bool = False,
    name: str | None = None,
    timeout_ms: int | None = None,
) -> list:
    """Pocket (subtract extrude) a sketch inside a PartDesign Body.

    ``midplane=True`` cuts symmetrically about the sketch plane — preferred
    when pocketing through a thin panel so the cut exits both sides.
    Consider ``pocket_through`` for through-holes (no thickness guessing)
    and ``pocket_blind`` for blind pockets from one face.
    """
    return _wrap(
        "pocket_sketch",
        _client().pocket_sketch(doc_name, body_name, sketch_name, depth, reversed, midplane, name, timeout_ms),
    )


@mcp.tool()
def revolve_sketch(
    ctx: Context,
    doc_name: str,
    body_name: str,
    sketch_name: str,
    axis: Literal["X", "Y", "Z"] = "X",
    angle: float = 360.0,
    name: str | None = None,
) -> list:
    """Revolve a sketch around one of the body origin axes."""
    return _wrap("revolve_sketch", _client().revolve_sketch(doc_name, body_name, sketch_name, axis, angle, name))


@mcp.tool()
def fillet_edges(
    ctx: Context,
    doc_name: str,
    body_name: str,
    base_name: str,
    edges: list[int],
    radius: float = 1.0,
    name: str | None = None,
) -> list:
    """Fillet a set of edges on `base_name` inside `body_name`. Edge indices are 1-based (from list_edges)."""
    return _wrap("fillet_edges", _client().fillet_edges(doc_name, body_name, base_name, edges, radius, name))


@mcp.tool()
def chamfer_edges(
    ctx: Context,
    doc_name: str,
    body_name: str,
    base_name: str,
    edges: list[int],
    size: float = 1.0,
    name: str | None = None,
) -> list:
    """Chamfer a set of edges on `base_name` inside `body_name`. Edge indices are 1-based."""
    return _wrap("chamfer_edges", _client().chamfer_edges(doc_name, body_name, base_name, edges, size, name))


@mcp.tool()
def shell_object(
    ctx: Context,
    doc_name: str,
    body_name: str,
    base_name: str,
    faces: list[int],
    thickness: float = 1.0,
    name: str | None = None,
) -> list:
    """Hollow a solid; `faces` is the set of face indices to remove (the open-face list)."""
    return _wrap("shell_object", _client().shell_object(doc_name, body_name, base_name, faces, thickness, name))


@mcp.tool()
def linear_pattern(
    ctx: Context,
    doc_name: str,
    body_name: str,
    feature_names: list[str],
    direction: Literal["X", "Y", "Z"] = "X",
    length: float = 10.0,
    occurrences: int = 2,
    name: str | None = None,
) -> list:
    """Linear-pattern one or more PartDesign features inside a body."""
    return _wrap(
        "linear_pattern",
        _client().linear_pattern(doc_name, body_name, feature_names, direction, length, occurrences, name),
    )


@mcp.tool()
def polar_pattern(
    ctx: Context,
    doc_name: str,
    body_name: str,
    feature_names: list[str],
    axis: Literal["X", "Y", "Z"] = "Z",
    angle: float = 360.0,
    occurrences: int = 4,
    name: str | None = None,
) -> list:
    """Polar-pattern one or more PartDesign features around a body origin axis."""
    return _wrap(
        "polar_pattern",
        _client().polar_pattern(doc_name, body_name, feature_names, axis, angle, occurrences, name),
    )


@mcp.tool()
def create_sketch_offset(
    ctx: Context,
    doc_name: str,
    body_name: str,
    plane: Literal["XY", "XZ", "YZ"],
    offset_mm: float,
    name: str | None = None,
) -> list:
    """Create a sketch on a datum plane parallel to a body origin plane, offset by offset_mm along the plane normal."""
    return _wrap(
        "create_sketch_offset",
        _client().create_sketch_offset(doc_name, body_name, plane, offset_mm, name),
    )


@mcp.tool()
def create_sketch_on_face(
    ctx: Context,
    doc_name: str,
    body_name: str,
    base_name: str,
    face_index: int = 1,
    name: str | None = None,
) -> list:
    """Attach a new sketch to face face_index (1-based) of base_name. Use base_name='tip' for body.Tip."""
    return _wrap(
        "create_sketch_on_face",
        _client().create_sketch_on_face(doc_name, body_name, base_name, face_index, name),
    )


@mcp.tool()
def groove_sketch(
    ctx: Context,
    doc_name: str,
    body_name: str,
    sketch_name: str,
    axis: Literal["X", "Y", "Z"] = "Z",
    angle: float = 360.0,
    name: str | None = None,
) -> list:
    """Revolve-cut a sketch around a body origin axis to remove material (PartDesign::Groove)."""
    return _wrap(
        "groove_sketch",
        _client().groove_sketch(doc_name, body_name, sketch_name, axis, angle, name),
    )


@mcp.tool()
def sweep_sketch(
    ctx: Context,
    doc_name: str,
    body_name: str,
    profile_name: str,
    spine_name: str,
    name: str | None = None,
    timeout_ms: int | None = None,
) -> list:
    """Sweep a profile sketch along a spine sketch to add material (PartDesign::Pipe)."""
    return _wrap(
        "sweep_sketch",
        _client().sweep_sketch(doc_name, body_name, profile_name, spine_name, name, timeout_ms),
    )


@mcp.tool()
def mirrored(
    ctx: Context,
    doc_name: str,
    body_name: str,
    feature_names: list[str],
    plane: Literal["XY", "XZ", "YZ"] = "XY",
    name: str | None = None,
) -> list:
    """Mirror one or more PartDesign features across a body origin plane (PartDesign::Mirrored)."""
    return _wrap(
        "mirrored",
        _client().mirrored(doc_name, body_name, feature_names, plane, name),
    )


@mcp.tool()
def duplicate_body(
    ctx: Context,
    doc_name: str,
    source_name: str,
    name: str | None = None,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    rot_x_deg: float = 0.0,
    rot_y_deg: float = 0.0,
    rot_z_deg: float = 0.0,
) -> list:
    """Copy a body as a Part::Feature (baked shape) and place it at a new position/orientation."""
    return _wrap(
        "duplicate_body",
        _client().duplicate_body(doc_name, source_name, name, x, y, z, rot_x_deg, rot_y_deg, rot_z_deg),
    )


# ---------------------------------------------------------------------------
# Boolean
# ---------------------------------------------------------------------------


@mcp.tool()
def boolean(
    ctx: Context,
    doc_name: str,
    op: Literal["union", "cut", "common"],
    a: str,
    b: str,
    name: str | None = None,
    timeout_ms: int | None = None,
) -> list:
    """Apply a Part-workbench boolean between two top-level shapes. Prefer PartDesign pockets inside a body when possible."""
    return _wrap("boolean", _client().boolean(doc_name, op, a, b, name, timeout_ms))


# ---------------------------------------------------------------------------
# Parametric
# ---------------------------------------------------------------------------


@mcp.tool()
def create_spreadsheet(ctx: Context, doc_name: str | None = None, name: str = "Variables") -> list:
    """Create a Spreadsheet object to hold named parameters. Cells become aliases for use in `set_expression`."""
    return _wrap("create_spreadsheet", _client().create_spreadsheet(doc_name, name))


@mcp.tool()
def set_cell(
    ctx: Context,
    doc_name: str,
    sheet_name: str,
    cell: str,
    value: str | float,
    alias: str | None = None,
) -> list:
    """Set a spreadsheet cell value. Pass `alias` (e.g. `wall_thickness`) to make it addressable by name."""
    return _wrap("set_cell", _client().set_cell(doc_name, sheet_name, cell, value, alias))


@mcp.tool()
def set_expression(
    ctx: Context, doc_name: str, obj_name: str, property_path: str, expression: str,
) -> list:
    """Bind an object property to a spreadsheet expression, e.g. `<<Variables>>.wall_thickness`.
    Pass empty `expression` to clear the binding."""
    return _wrap("set_expression", _client().set_expression(doc_name, obj_name, property_path, expression))


@mcp.tool()
def modify_property(
    ctx: Context, doc_name: str, obj_name: str, property_name: str, value: Any,
) -> list:
    """Directly set an object property. Accepts numbers, strings, and dicts for Vector/Placement properties."""
    return _wrap("modify_property", _client().modify_property(doc_name, obj_name, property_name, value))


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@mcp.tool()
def export_step(
    ctx: Context,
    doc_name: str,
    obj_names: list[str],
    path: str,
    timeout_ms: int | None = None,
) -> list[TextContent]:
    """Export one or more objects as a STEP file.  Default timeout 300 s — override via ``timeout_ms`` for very large assemblies."""
    return [TextContent(type="text", text=_summary("export_step", _client().export_step(doc_name, obj_names, path, timeout_ms)))]


@mcp.tool()
def export_stl(
    ctx: Context,
    doc_name: str,
    obj_names: list[str],
    path: str,
    timeout_ms: int | None = None,
) -> list[TextContent]:
    """Export one or more objects as an STL mesh.  Default timeout 300 s."""
    return [TextContent(type="text", text=_summary("export_stl", _client().export_stl(doc_name, obj_names, path, timeout_ms)))]


@mcp.tool()
def export_fcstd(
    ctx: Context,
    doc_name: str,
    path: str,
    timeout_ms: int | None = None,
) -> list[TextContent]:
    """Save the full parametric document to a .FCStd file.  Default timeout 300 s."""
    return [TextContent(type="text", text=_summary("export_fcstd", _client().export_fcstd(doc_name, path, timeout_ms)))]


# ---------------------------------------------------------------------------
# Escape hatches
# ---------------------------------------------------------------------------


@mcp.tool()
def execute_code(ctx: Context, code: str, timeout_ms: int | None = None) -> list:
    """Run arbitrary Python in the FreeCAD process. Last-resort escape hatch — prefer the curated tools.

    Default timeout is 60 s.  Pass ``timeout_ms`` for longer scripts (frame
    sequences, heavy geometry generation, STEP batch export).  If your script
    times out, the task keeps running on the GUI thread but its late result is
    safely discarded — subsequent calls won't see stale output.
    """
    return _wrap("execute_code", _client().execute_code(code, timeout_ms))


# ---------------------------------------------------------------------------
# High-level helpers — promoted from common `execute_code` patterns
# ---------------------------------------------------------------------------


@mcp.tool()
def rotate_about_axis(
    ctx: Context,
    doc_name: str,
    obj_name: str,
    pivot: dict,
    axis: dict,
    angle_deg: float,
) -> list:
    """Rotate ``obj_name`` around a world-space axis through ``pivot``.

    ``pivot`` and ``axis`` are ``{"x": ..., "y": ..., "z": ...}`` dicts.  Unlike
    ``transform_object`` — which rotates around the object's own origin —
    this rotates around an arbitrary world point, so it works for hinges,
    revolute joints, and assembly pivots.
    """
    return _wrap("rotate_about_axis", _client().rotate_about_axis(doc_name, obj_name, pivot, axis, angle_deg))


@mcp.tool()
def pocket_through(
    ctx: Context,
    doc_name: str,
    body_name: str,
    sketch_name: str,
    margin: float = 1.0,
    name: str | None = None,
    timeout_ms: int | None = None,
) -> list:
    """Pocket that cuts cleanly through the body's thickness in the sketch-normal direction.

    Picks up the body's bounding thickness automatically — no need to guess
    ``depth``, ``midplane``, or ``reversed``.  ``margin`` (mm) extends the cut
    past both faces so it exits cleanly.
    """
    return _wrap(
        "pocket_through",
        _client().pocket_through(doc_name, body_name, sketch_name, margin, name, timeout_ms),
    )


@mcp.tool()
def pocket_blind(
    ctx: Context,
    doc_name: str,
    body_name: str,
    sketch_name: str,
    depth: float,
    reverse: bool = False,
    name: str | None = None,
    timeout_ms: int | None = None,
) -> list:
    """Blind pocket of ``depth`` mm from the sketch plane.

    ``reverse=False`` cuts toward +normal of the sketch plane;
    ``reverse=True`` cuts toward -normal.  Never midplane — pick a direction.
    """
    return _wrap(
        "pocket_blind",
        _client().pocket_blind(doc_name, body_name, sketch_name, depth, reverse, name, timeout_ms),
    )


@mcp.tool()
def hex_grid_sketch(
    ctx: Context,
    doc_name: str,
    sketch_name: str,
    umin: float,
    umax: float,
    vmin: float,
    vmax: float,
    side: float = 9.0,
    wall: float = 3.0,
    exclusions: list | None = None,
    clear: bool = True,
    timeout_ms: int | None = None,
) -> list:
    """Populate a sketch with a flat-top honeycomb grid of hexes in one call.

    Column pitch = ``1.5*side + wall``; row pitch = ``side*sqrt(3) + wall``;
    odd columns offset by half a row for the staggered honeycomb pattern.

    ``exclusions`` is a list of ``[u0, u1, v0, v1]`` rectangles; any hex whose
    center falls inside one is skipped (use to reserve solid islands for
    mounting hardware, latch bosses, etc.).  Default timeout 120 s.
    """
    return _wrap(
        "hex_grid_sketch",
        _client().hex_grid_sketch(
            doc_name, sketch_name, umin, umax, vmin, vmax,
            side, wall, exclusions, clear, timeout_ms,
        ),
    )


@mcp.tool()
def countersunk_hole(
    ctx: Context,
    doc_name: str,
    body_name: str,
    plane_tag: Literal["XY", "XZ", "YZ"],
    u: float,
    v: float,
    shaft_r: float,
    csink_r: float,
    csink_depth: float,
    shaft_depth: float,
    reverse: bool = False,
    name: str | None = None,
) -> list:
    """Clearance hole + countersink on a body origin plane, in one call.

    Creates two sketches and two pockets inside ``body_name`` (both reusable
    parametric features).  ``plane_tag`` picks the body origin plane (XY/XZ/YZ);
    ``u``/``v`` are the plane-local coordinates of the hole center.
    """
    return _wrap(
        "countersunk_hole",
        _client().countersunk_hole(
            doc_name, body_name, plane_tag, u, v,
            shaft_r, csink_r, csink_depth, shaft_depth, reverse, name,
        ),
    )


@mcp.tool()
def clear_sketch_geometry(ctx: Context, doc_name: str, sketch_name: str) -> list:
    """Delete every line/arc/circle in a sketch. Use before redrawing."""
    return _wrap("clear_sketch_geometry", _client().clear_sketch_geometry(doc_name, sketch_name))


@mcp.tool()
def set_sketch_rectangle(
    ctx: Context,
    doc_name: str,
    sketch_name: str,
    x: float,
    y: float,
    width: float,
    height: float,
    clear: bool = True,
) -> list:
    """Replace a sketch's contents with a single rectangle.

    Same (x, y, width, height) semantics as ``add_sketch_rectangle`` but
    clears existing geometry first — useful for resizing a padded panel
    without rebuilding the body.
    """
    return _wrap(
        "set_sketch_rectangle",
        _client().set_sketch_rectangle(doc_name, sketch_name, x, y, width, height, clear),
    )


@mcp.tool()
def get_origin_plane(
    ctx: Context,
    doc_name: str,
    body_name: str,
    plane_tag: Literal["XY", "XZ", "YZ"],
) -> list[TextContent]:
    """Look up a body's origin plane object name (e.g. 'YZ_Plane032').

    FreeCAD suffixes origin-plane names with a body index, so hard-coding
    ``"YZ_Plane"`` in ``AttachmentSupport`` fails on the second body in a doc.
    Use this helper first, then pass the returned name into sketch attachment.
    """
    return [TextContent(type="text", text=_summary("get_origin_plane", _client().get_origin_plane(doc_name, body_name, plane_tag)))]


@mcp.tool()
def insert_part_from_library(ctx: Context, relative_path: str) -> list:
    """Insert a part from the optional FreeCAD parts_library addon (if installed)."""
    return _wrap("insert_part_from_library", _client().insert_part_from_library(relative_path))


@mcp.tool()
def get_parts_list(ctx: Context) -> list[TextContent]:
    """List parts available in the parts_library addon (empty list if not installed)."""
    return [TextContent(type="text", text=_summary("get_parts_list", _client().get_parts_list()))]


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------


@mcp.tool()
def run_design_program(
    ctx: Context, program_path: str, out_fcstd: str | None = None, out_step: str | None = None,
) -> list[TextContent]:
    """Replay a woodbloks-ai DesignProgram JSON via the headless subprocess executor.

    This path does not require a running FreeCAD GUI — it spawns FreeCAD's bundled Python
    and runs the existing woodbloks runner. Use it for CI or STEP-only jobs.
    """
    from .batch import run as run_batch
    res = run_batch(program_path, out_fcstd=out_fcstd, out_step=out_step)
    return [TextContent(type="text", text=_summary("run_design_program", res))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    global _ONLY_TEXT
    ap = argparse.ArgumentParser(prog="conjur3-pilot", description="Conjur3 MCP server")
    ap.add_argument("--only-text-feedback", action="store_true",
                    help="Skip attaching screenshot images to tool results.")
    ap.add_argument("--host", default="localhost", help="Conjur3 RPC host")
    ap.add_argument("--port", type=int, default=9875, help="Conjur3 RPC port")
    ap.add_argument("--http", action="store_true",
                    help="Serve MCP over Streamable HTTP (at /mcp) instead of stdio.")
    ap.add_argument("--http-host", default="127.0.0.1",
                    help="HTTP bind host (used with --http).")
    ap.add_argument("--http-port", type=int, default=8765,
                    help="HTTP bind port (used with --http).")
    args = ap.parse_args()
    _ONLY_TEXT = args.only_text_feedback
    os.environ["FREECAD_PILOT_HOST"] = args.host
    os.environ["FREECAD_PILOT_PORT"] = str(args.port)

    if args.http:
        # Streamable-HTTP transport — for hosting behind the Conjur3 MCP gateway.
        # Wrap the ASGI app to capture the gateway's X-Conjur3-Seat header into a
        # contextvar, so the relay can route each RPC to the right FreeCAD.
        import uvicorn
        from .seat_context import current_seat

        try:
            mcp.settings.host = args.http_host
            mcp.settings.port = args.http_port
        except Exception:  # pragma: no cover - older FastMCP fallback
            pass

        app = mcp.streamable_http_app()

        # Optional bearer auth: with MCP_AUTH_TOKEN set, every HTTP request must
        # carry `Authorization: Bearer <token>` or it gets a 401.
        import hmac

        auth_token = os.environ.get("MCP_AUTH_TOKEN", "").strip()
        expected = f"Bearer {auth_token}".encode() if auth_token else None

        def seat_asgi(inner):
            async def wrapped(scope, receive, send):
                if scope.get("type") == "http":
                    if expected is not None:
                        got = dict(scope.get("headers") or []).get(b"authorization", b"")
                        if not hmac.compare_digest(got, expected):
                            await send({"type": "http.response.start", "status": 401,
                                        "headers": [(b"content-type", b"text/plain"),
                                                    (b"www-authenticate", b"Bearer")]})
                            await send({"type": "http.response.body", "body": b"unauthorized"})
                            return
                    for k, v in scope.get("headers") or []:
                        if k == b"x-conjur3-seat" and v:
                            current_seat.set(v.decode())
                            break
                await inner(scope, receive, send)
            return wrapped

        log.info(
            "Conjur3 MCP server starting — Streamable HTTP on http://%s:%d/mcp (RPC %s:%d)",
            args.http_host, args.http_port, args.host, args.port,
        )
        uvicorn.run(seat_asgi(app), host=args.http_host, port=args.http_port, log_level="warning")
    else:
        log.info("Conjur3 MCP server starting (stdio) — RPC target %s:%d", args.host, args.port)
        mcp.run()


if __name__ == "__main__":
    main()
