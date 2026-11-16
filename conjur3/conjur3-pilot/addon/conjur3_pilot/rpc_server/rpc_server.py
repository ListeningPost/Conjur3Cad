"""Conjur3 — in-process XML-RPC bridge.

Runs inside the FreeCAD GUI. Every RPC method schedules work onto the Qt main
thread via a queue, wraps mutations in an undo transaction, and calls
doc.recompute() so the 3D viewport updates live.

Bridge pattern (FilteredXMLRPCServer, GUI task queue, settings, auto-start,
commands) is adapted from neka-nat/freecad-mcp (MIT). The tool handler
surface is original; it mirrors the curated shape of ghbalf/freecad-ai.
"""

import base64
import contextlib
import io
import ipaddress
import json
import os
import queue
import re
import tempfile
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any
from xmlrpc.server import SimpleXMLRPCServer

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets

from .feasibility import (
    check_chamfer_size,
    check_countersink_geometry,
    check_fillet_radius,
    check_positive,
    check_pocket_depth,
)
from .parts_library import get_parts_list, insert_part_from_library
from .serialize import serialize_object
from .snapshots import SnapshotStore


rpc_server_thread = None
rpc_server_instance = None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

_SETTINGS_FILENAME = "conjur3_settings.json"
_DEFAULT_SETTINGS = {
    "remote_enabled": False,
    "allowed_ips": "127.0.0.1",
    "auto_start_rpc": True,  # Conjur3 defaults to auto-start.
}


def _get_settings_path():
    return os.path.join(FreeCAD.getUserAppDataDir(), _SETTINGS_FILENAME)


def load_settings():
    path = _get_settings_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                settings = json.load(f)
            for k, v in _DEFAULT_SETTINGS.items():
                settings.setdefault(k, v)
            return settings
        except Exception as e:
            FreeCAD.Console.PrintWarning(f"[Conjur3] failed to load settings: {e}\n")
    return dict(_DEFAULT_SETTINGS)


def save_settings(settings):
    try:
        with open(_get_settings_path(), "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        FreeCAD.Console.PrintError(f"[Conjur3] failed to save settings: {e}\n")


# ---------------------------------------------------------------------------
# IP filtering
# ---------------------------------------------------------------------------


class FilteredXMLRPCServer(SimpleXMLRPCServer):
    def __init__(self, addr, allowed_ips_str="127.0.0.1", **kwargs):
        self._allowed = _parse_allowed_ips(allowed_ips_str)
        super().__init__(addr, **kwargs)

    def verify_request(self, request, client_address):
        try:
            addr = ipaddress.ip_address(client_address[0])
            for network in self._allowed:
                if addr in network:
                    return True
        except ValueError:
            pass
        FreeCAD.Console.PrintWarning(
            f"[Conjur3] rejected connection from {client_address[0]}\n"
        )
        return False


_COMMA_SEP_RE = re.compile(r"^\s*[^,\s]+(\s*,\s*[^,\s]+)*\s*$")


def validate_allowed_ips(s):
    if not s or not s.strip():
        return [], ["Input must not be empty."]
    if not _COMMA_SEP_RE.match(s):
        return [], ["Malformed list — check commas/spacing."]
    valid, errors = [], []
    for entry in s.split(","):
        entry = entry.strip()
        try:
            ipaddress.ip_network(entry, strict=False)
            valid.append(entry)
        except ValueError:
            errors.append(f"Invalid IP/subnet: '{entry}'")
    return valid, errors


def _parse_allowed_ips(s):
    valid, errors = validate_allowed_ips(s)
    for m in errors:
        FreeCAD.Console.PrintWarning(f"[Conjur3] {m}\n")
    return [ipaddress.ip_network(e, strict=False) for e in valid]


# ---------------------------------------------------------------------------
# GUI task queue — XML-RPC threads submit closures; Qt main thread runs them.
#
# Each submitted task gets a unique token + a private response queue.  If the
# caller times out, the token is marked abandoned; when the task eventually
# completes, `process_gui_tasks` drops the result with a warning instead of
# leaking it into an unrelated next call.  This was a real bug — a 45 s
# execute_code that timed out would cause a follow-up list_objects to return
# the execute_code's stdout.
# ---------------------------------------------------------------------------

rpc_request_queue = queue.Queue()
_abandoned_tokens: set[str] = set()
_abandoned_lock = threading.Lock()


def process_gui_tasks():
    while not rpc_request_queue.empty():
        try:
            item = rpc_request_queue.get_nowait()
        except queue.Empty:
            break
        if isinstance(item, tuple) and len(item) == 3:
            token, resp_q, task = item
        else:  # legacy single-callable submission, still accepted
            token, resp_q, task = None, None, item
        try:
            res = task()
        except Exception as e:
            res = f"task error: {e}\n{traceback.format_exc()}"
        if token is not None:
            with _abandoned_lock:
                if token in _abandoned_tokens:
                    _abandoned_tokens.discard(token)
                    try:
                        FreeCAD.Console.PrintWarning(
                            f"[Conjur3] discarded stale result for timed-out task "
                            f"token={token[:8]}\n"
                        )
                    except Exception:
                        pass
                    continue
        if resp_q is not None:
            try:
                resp_q.put_nowait(res)
            except queue.Full:
                pass
    QtCore.QTimer.singleShot(200, process_gui_tasks)


def _run_on_gui(fn, timeout=30):
    """Submit a callable to the GUI thread; block until its result arrives.

    Uses a per-call UUID token + private response queue, so a late result from
    a prior timed-out call can't leak into this call's return value.  On
    timeout, marks the token as abandoned and returns a structured error dict
    (instead of raising) so callers always get a JSON-shaped response.
    """
    token = uuid.uuid4().hex
    resp_q: queue.Queue = queue.Queue(maxsize=1)
    rpc_request_queue.put((token, resp_q, fn))
    try:
        return resp_q.get(timeout=timeout)
    except queue.Empty:
        with _abandoned_lock:
            _abandoned_tokens.add(token)
        return {
            "success": False,
            "error": (
                f"task timed out after {timeout}s; the FreeCAD GUI may still "
                f"be processing it. Wait a few seconds and re-query state "
                f"(e.g., ping, list_objects) before retrying. Increase the "
                f"call's timeout_ms if this is a known-heavy operation "
                f"(STEP export, large hex mesh, etc.)."
            ),
            "timed_out": True,
            "timeout_seconds": timeout,
        }


def _set_support(obj, value):
    """Set a sketch/datum attachment: `AttachmentSupport` on FreeCAD 1.0+,
    `Support` on 0.21."""
    if hasattr(obj, "AttachmentSupport"):
        obj.AttachmentSupport = value
    else:
        obj.Support = value


def _ensure_active_view():
    """Return a usable View3DInventor, or None.

    capture_viewport historically failed with 'no 3D view' right after
    openDocument because FreeCADGui.ActiveDocument.ActiveView was None
    even though the document existed.  Recover by:
        1. Looking up the Gui doc for the active Python doc
        2. Asking Qt to create a view via Std_ViewCreate
    """
    def _ok(v):
        return v is not None and hasattr(v, "saveImage")

    try:
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return None
        gdoc = None
        try:
            gdoc = FreeCADGui.getDocument(doc.Name)
        except Exception:
            pass
        if gdoc is None:
            return None
        v = getattr(gdoc, "ActiveView", None)
        if _ok(v):
            return v
        # Recovery: activate the GUI doc, try creating a 3D view.
        try:
            if hasattr(FreeCADGui, "setActiveDocument"):
                FreeCADGui.setActiveDocument(gdoc)
            if hasattr(FreeCADGui, "runCommand"):
                FreeCADGui.runCommand("Std_ViewCreate")
        except Exception:
            pass
        v = getattr(gdoc, "ActiveView", None)
        if _ok(v):
            return v
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Transaction wrapper (the ghbalf `_with_undo` pattern).
# ---------------------------------------------------------------------------


class ValidationError(Exception):
    """Raised by `_with_undo` when post-execution validation rejects the result.

    Carries enough context for `_err` to produce a structured corrective-reprompt
    payload: failure type, the offending feature (so measurements can be
    extracted from the rolled-back state), and a human-readable suggestion.
    """

    def __init__(self, failure_type, *, obj=None, suggestion=None, **details):
        self.failure_type = failure_type
        self.obj = obj
        self.suggestion = suggestion
        self.details = details
        super().__init__(f"{failure_type}: {details or suggestion or ''}".strip(": "))


# ---------------------------------------------------------------------------
# Snapshot store (feature-tree checkpoint store)
# ---------------------------------------------------------------------------


_SNAPSHOT_STORES: dict[str, SnapshotStore] = {}
_RING_SIZE = 30


def _get_store(doc):
    """Get or create the SnapshotStore for `doc`. Returns None if doc is unsaved.

    Snapshots only kick in once the document has a FileName on disk — the
    user must `save_document(path=...)` first. This keeps anonymous scratch
    docs from littering the working directory.
    """
    fn = getattr(doc, "FileName", None)
    if not fn:
        return None
    store = _SNAPSHOT_STORES.get(doc.Name)
    if store is None or str(store.doc_path) != fn:
        store = SnapshotStore(fn, ring_size=_RING_SIZE)
        _SNAPSHOT_STORES[doc.Name] = store
    return store


def _with_undo(doc, label, fn, *, params=None):
    """Snapshot → openTransaction → fn → recompute → validate → commit → auto-save.

    Wraps every mutation in three layers of safety:

    1. Pre-action snapshot: copies the live `part.FCStd` to
       `part.snapshots/ring/part.N.FCStd` so the pre-action state is
       restorable from disk even after process death.
    2. In-memory transaction: openTransaction/abortTransaction provides
       atomic rollback within the running FreeCAD session.
    3. Post-exec validity check: `Shape.isValid()` on the new feature; on
       failure abort the transaction (atomic rollback) and raise
       ValidationError so `_err()` produces a structured corrective-reprompt
       payload.

    On successful commit the live doc is saved so `part.FCStd` always
    reflects current kernel state.
    """
    store = _get_store(doc)
    if store is not None:
        try:
            store.snapshot_action(label, params or {})
        except Exception as e:
            FreeCAD.Console.PrintWarning(f"[Conjur3] snapshot failed: {e}\n")

    doc.openTransaction(label)
    try:
        result = fn(doc)
        doc.recompute()
        shape = getattr(result, "Shape", None) if result is not None else None
        if shape is not None:
            try:
                valid = bool(shape.isValid())
            except Exception:
                valid = True  # isValid threw — treat as inconclusive, don't block
            if not valid:
                raise ValidationError(
                    "invalid_geometry",
                    obj=result,
                    suggestion=(
                        "the operation produced a non-manifold or self-intersecting "
                        "solid; reduce parameters (smaller fillet radius, shallower "
                        "pocket, etc.) or verify the input sketch is closed and planar"
                    ),
                )
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise

    if store is not None and getattr(doc, "FileName", None):
        try:
            doc.save()
        except Exception as e:
            FreeCAD.Console.PrintWarning(f"[Conjur3] auto-save failed: {e}\n")

    return result


def _measure(obj):
    """Deterministic geometric measurements for a feature: volume, bbox, face/edge/vertex counts, validity.

    Returns {} for objects without a usable Shape (sketches, spreadsheets, datum
    planes). Read-only — does not trigger recompute. Callers are expected to have
    recomputed the document already (via `_with_undo`).
    """
    shape = getattr(obj, "Shape", None)
    if shape is None:
        return {}
    out = {}
    try:
        b = shape.BoundBox
        out["bbox_mm"] = {"x": b.XLength, "y": b.YLength, "z": b.ZLength}
    except Exception:
        pass
    try:
        out["face_count"] = len(shape.Faces)
    except Exception:
        pass
    try:
        out["edge_count"] = len(shape.Edges)
    except Exception:
        pass
    try:
        out["vertex_count"] = len(shape.Vertexes)
    except Exception:
        pass
    try:
        out["volume_mm3"] = float(shape.Volume)
    except Exception:
        pass
    try:
        out["is_valid"] = bool(shape.isValid())
    except Exception:
        pass
    return out


def _ok(data=None, *, obj=None, **kw):
    """Build a success payload.

    Pass `obj=<FreeCAD feature>` to auto-attach the feature name and a
    deterministic geometric measurement block. Falls back to bare `_ok()` for
    void mutations and `_ok(name=...)` for cases where no object handle exists.
    """
    out = {"success": True}
    if data is not None:
        out["data"] = data
    if obj is not None:
        out["name"] = obj.Name
        meas = _measure(obj)
        if meas:
            out["measurements"] = meas
    out.update(kw)
    return out


def _check(failure_detail):
    """Convert a feasibility-check failure dict into a ValidationError raise.

    Pre-execution feasibility gate: each tool that has checks calls this on
    the result of one or more `check_*` functions before entering `_with_undo`.
    A failure aborts the operation BEFORE the kernel is invoked — the feature
    tree is never modified.
    """
    if failure_detail is not None:
        raise ValidationError(**failure_detail)


def _err(msg):
    """Build a failure payload.

    For `ValidationError` instances, emit a structured corrective-reprompt
    envelope (failure_type, current measurements after rollback, suggestion,
    details) so the agent has enough context to revise without a follow-up
    observation call. Plain exceptions get a flat `{success, error}` shape.
    """
    if isinstance(msg, ValidationError):
        out = {
            "success": False,
            "failure_type": msg.failure_type,
            "error": str(msg),
        }
        if msg.obj is not None:
            meas = _measure(msg.obj)
            if meas:
                out["measurements"] = meas
        if msg.suggestion:
            out["suggestion"] = msg.suggestion
        if msg.details:
            out["details"] = msg.details
        return out
    return {"success": False, "error": str(msg)}


def _resolve_doc(doc_name=None):
    if doc_name:
        doc = FreeCAD.getDocument(doc_name)
        if not doc:
            raise ValueError(f"document {doc_name!r} not found")
        return doc
    doc = FreeCAD.ActiveDocument
    if not doc:
        raise ValueError("no active document; create one first")
    return doc


def _resolve_obj(doc, obj_name):
    obj = doc.getObject(obj_name)
    if not obj:
        raise ValueError(f"object {obj_name!r} not found in {doc.Name!r}")
    return obj


# ---------------------------------------------------------------------------
# Placement helper
# ---------------------------------------------------------------------------


def _find_body_axis(body, axis):
    """Return the origin axis feature (X, Y, or Z) for a PartDesign Body.

    Matches by Label first (stable: 'X-axis'/'Y-axis'/'Z-axis') then by Name
    prefix, since FreeCAD suffixes Names (X_Axis001 in the 2nd body, etc.).
    """
    label_map = {"X": "X-axis", "Y": "Y-axis", "Z": "Z-axis"}
    prefix_map = {"X": "X_Axis", "Y": "Y_Axis", "Z": "Z_Axis"}
    want_label = label_map[axis]
    want_prefix = prefix_map[axis]
    for feat in body.Origin.OutList:
        if getattr(feat, "Label", "") == want_label:
            return feat
    for feat in body.Origin.OutList:
        if feat.Name.startswith(want_prefix):
            return feat
    return None


def _find_origin_plane(body, tag):
    """Return the origin plane feature ('XY', 'XZ', or 'YZ') for a Body.

    FreeCAD suffixes plane Names with the body index (e.g. 'YZ_Plane032');
    match by prefix on Name, falling back to the stable Label.
    """
    want_prefix = f"{tag}_Plane"
    for feat in body.Origin.OutList:
        if feat.Name.startswith(want_prefix):
            return feat
    label_map = {"XY": "XY-plane", "XZ": "XZ-plane", "YZ": "YZ-plane"}
    want_label = label_map.get(tag)
    if want_label:
        for feat in body.Origin.OutList:
            if getattr(feat, "Label", "") == want_label:
                return feat
    return None


def _placement_from_dict(pl):
    if not isinstance(pl, dict):
        return FreeCAD.Placement()
    base = pl.get("Base") or pl.get("Position") or {}
    rot = pl.get("Rotation") or {}
    axis = rot.get("Axis", {})
    return FreeCAD.Placement(
        FreeCAD.Vector(base.get("x", 0), base.get("y", 0), base.get("z", 0)),
        FreeCAD.Rotation(
            FreeCAD.Vector(axis.get("x", 0), axis.get("y", 0), axis.get("z", 1)),
            rot.get("Angle", 0),
        ),
    )


# ---------------------------------------------------------------------------
# The RPC service
# ---------------------------------------------------------------------------


class Conjur3RPC:
    """Every mutating method schedules onto the Qt GUI thread so recompute()
    refreshes the live viewport. Every method returns {success, ...} JSON."""

    TIMEOUT = 30

    # ---------- Session ----------

    def ping(self):
        return {"success": True, "version": FreeCAD.Version(), "pid": os.getpid()}

    def list_documents(self):
        return _ok(list(FreeCAD.listDocuments().keys()))

    def create_document(self, name="Untitled"):
        def task():
            try:
                doc = FreeCAD.newDocument(name)
                FreeCADGui.ActiveDocument = FreeCADGui.getDocument(doc.Name)
                return _ok(document_name=doc.Name)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def switch_document(self, doc_name):
        def task():
            try:
                FreeCAD.setActiveDocument(doc_name)
                return _ok(document_name=doc_name)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def save_document(self, doc_name=None, path=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                if path:
                    doc.saveAs(path)
                else:
                    doc.save()
                return _ok(path=doc.FileName)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def close_document(self, doc_name):
        def task():
            try:
                FreeCAD.closeDocument(doc_name)
                _SNAPSHOT_STORES.pop(doc_name, None)
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    # ---------- Snapshots (feature-tree checkpoint store) ----------

    def snapshot(self, doc_name=None, label=None):
        """Save a named milestone snapshot of the current document state.

        Stored under part.snapshots/milestones/<label>.FCStd. Unbounded;
        re-using a label overwrites. Use this to bookmark known-good states
        independent of the auto-snapshot ring.
        """
        def task():
            try:
                if not label:
                    return _err("label is required")
                doc = _resolve_doc(doc_name)
                if not doc.FileName:
                    return _err("save the document with a path first; "
                                "snapshots require a saved file")
                store = _get_store(doc)
                doc.save()  # ensure on-disk state matches in-memory before snapshot
                entry = store.snapshot_milestone(label)
                return _ok(entry)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def list_snapshots(self, doc_name=None):
        """Return {ring: [...], milestones: [...]} sorted newest-first."""
        def task():
            try:
                doc = _resolve_doc(doc_name)
                store = _get_store(doc)
                if store is None:
                    return _ok({"ring": [], "milestones": [],
                                "note": "document is unsaved; no snapshots yet"})
                return _ok(store.list_all())
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def restore_snapshot(self, doc_name=None, n=None, milestone=None):
        """Replace the live doc with a snapshot from the ring (n) or milestones.

        Closes the current doc, copies the snapshot file over the live path,
        and reopens. The current state is NOT preserved — call `snapshot(label)`
        first if you want to bookmark before restoring.
        """
        def task():
            try:
                if (n is None) == (milestone is None):
                    return _err("specify exactly one of n= or milestone=")
                doc = _resolve_doc(doc_name)
                if not doc.FileName:
                    return _err("document is unsaved; nothing to restore over")
                store = _get_store(doc)
                snap = store.path_for(
                    n=int(n) if n is not None else None,
                    milestone=milestone,
                )
                live_path = doc.FileName
                doc_name_actual = doc.Name
                FreeCAD.closeDocument(doc_name_actual)
                _SNAPSHOT_STORES.pop(doc_name_actual, None)
                import shutil
                shutil.copy2(snap, live_path)
                reopened = FreeCAD.openDocument(live_path)
                FreeCAD.setActiveDocument(reopened.Name)
                return _ok({
                    "restored_from": str(snap),
                    "document": reopened.Name,
                })
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def undo(self, doc_name=None):
        def task():
            try:
                _resolve_doc(doc_name).undo()
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def redo(self, doc_name=None):
        def task():
            try:
                _resolve_doc(doc_name).redo()
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    # ---------- Introspection ----------

    def get_document_state(self, doc_name=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                return _ok({
                    "name": doc.Name,
                    "label": doc.Label,
                    "file": doc.FileName,
                    "modified": doc.Modified,
                    "objects": [serialize_object(o) for o in doc.Objects],
                })
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def list_objects(self, doc_name=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                return _ok([
                    {"Name": o.Name, "Label": o.Label, "TypeId": o.TypeId}
                    for o in doc.Objects
                ])
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def get_object(self, doc_name, obj_name):
        def task():
            try:
                return _ok(serialize_object(_resolve_obj(_resolve_doc(doc_name), obj_name)))
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def describe_model(self, doc_name=None):
        """Summary of the current model — object tree and top-level shape stats."""
        def task():
            try:
                doc = _resolve_doc(doc_name)
                objects = []
                for o in doc.Objects:
                    entry = {
                        "Name": o.Name, "Label": o.Label, "TypeId": o.TypeId,
                    }
                    shape = getattr(o, "Shape", None)
                    if shape is not None:
                        try:
                            entry["Volume"] = shape.Volume
                            entry["FaceCount"] = len(shape.Faces)
                            entry["EdgeCount"] = len(shape.Edges)
                        except Exception:
                            pass
                    objects.append(entry)
                return _ok({"document": doc.Name, "objects": objects})
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def list_faces(self, doc_name, obj_name):
        def task():
            try:
                obj = _resolve_obj(_resolve_doc(doc_name), obj_name)
                if obj.Shape is None:
                    return _err("object has no Shape")
                return _ok([
                    {
                        "Index": i + 1,
                        "Area": f.Area,
                        "Center": {"x": f.CenterOfMass.x, "y": f.CenterOfMass.y, "z": f.CenterOfMass.z},
                    }
                    for i, f in enumerate(obj.Shape.Faces)
                ])
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def list_edges(self, doc_name, obj_name):
        def task():
            try:
                obj = _resolve_obj(_resolve_doc(doc_name), obj_name)
                if obj.Shape is None:
                    return _err("object has no Shape")
                return _ok([
                    {"Index": i + 1, "Length": e.Length}
                    for i, e in enumerate(obj.Shape.Edges)
                ])
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def measure(self, doc_name, obj_name, kind="bounding_box"):
        """kind: 'bounding_box' | 'volume' | 'area' | 'center_of_mass'"""
        def task():
            try:
                obj = _resolve_obj(_resolve_doc(doc_name), obj_name)
                s = obj.Shape
                if s is None:
                    return _err("no Shape")
                if kind == "bounding_box":
                    b = s.BoundBox
                    return _ok({
                        "XLength": b.XLength, "YLength": b.YLength, "ZLength": b.ZLength,
                        "XMin": b.XMin, "YMin": b.YMin, "ZMin": b.ZMin,
                        "XMax": b.XMax, "YMax": b.YMax, "ZMax": b.ZMax,
                    })
                if kind == "volume":
                    return _ok({"Volume": s.Volume})
                if kind == "area":
                    return _ok({"Area": s.Area})
                if kind == "center_of_mass":
                    c = s.CenterOfMass
                    return _ok({"x": c.x, "y": c.y, "z": c.z})
                return _err(f"unknown kind: {kind}")
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    # ---------- Viewport ----------

    VIEW_NAMES = {
        "Isometric": "viewIsometric", "Front": "viewFront", "Top": "viewTop",
        "Right": "viewRight", "Back": "viewBack", "Left": "viewLeft",
        "Bottom": "viewBottom", "Dimetric": "viewDimetric", "Trimetric": "viewTrimetric",
    }

    def set_view(self, view_name="Isometric"):
        def task():
            try:
                view = FreeCADGui.ActiveDocument.ActiveView
                if view is None:
                    return _err("no active view")
                method = self.VIEW_NAMES.get(view_name)
                if not method or not hasattr(view, method):
                    return _err(f"unknown view: {view_name}")
                getattr(view, method)()
                view.fitAll()
                FreeCADGui.updateGui()
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def fit_all(self):
        def task():
            try:
                FreeCADGui.ActiveDocument.ActiveView.fitAll()
                FreeCADGui.updateGui()
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def zoom_object(self, doc_name, obj_name):
        def task():
            try:
                obj = _resolve_obj(_resolve_doc(doc_name), obj_name)
                FreeCADGui.Selection.clearSelection()
                FreeCADGui.Selection.addSelection(obj)
                FreeCADGui.SendMsgToActiveView("ViewSelection")
                FreeCADGui.updateGui()
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def capture_viewport(self, view_name="Isometric", width=None, height=None, focus_object=None, timeout_ms=None):
        """Return base64-encoded PNG of the active view, or None if unavailable.

        Recovers from the common 'no 3D view' case that used to hit right after
        openDocument — see `_ensure_active_view`.  Pass ``timeout_ms`` to override
        the default 30 s task timeout.
        """
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)

        def save():
            try:
                view = _ensure_active_view()
                if view is None:
                    return "no 3d view available"
                method = self.VIEW_NAMES.get(view_name)
                if method and hasattr(view, method):
                    getattr(view, method)()
                if focus_object:
                    doc = FreeCAD.ActiveDocument
                    obj = doc.getObject(focus_object) if doc else None
                    if obj:
                        FreeCADGui.Selection.clearSelection()
                        FreeCADGui.Selection.addSelection(obj)
                        FreeCADGui.SendMsgToActiveView("ViewSelection")
                    else:
                        view.fitAll()
                else:
                    view.fitAll()
                FreeCADGui.updateGui()
                if width and height:
                    view.saveImage(tmp, int(width), int(height))
                else:
                    view.saveImage(tmp)
                return True
            except Exception as e:
                return str(e)

        timeout = (timeout_ms / 1000.0) if timeout_ms else self.TIMEOUT
        res = _run_on_gui(save, timeout)
        try:
            if res is True and os.path.exists(tmp):
                with open(tmp, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return None

    # ---------- Visibility (show / hide / isolate) ----------

    def set_visibility(self, doc_name=None, obj_name=None, visible=True):
        """Show or hide a single object in the 3D viewport."""
        def task():
            try:
                if not obj_name:
                    return _err("obj_name is required")
                doc = _resolve_doc(doc_name)
                obj = _resolve_obj(doc, obj_name)
                vobj = getattr(obj, "ViewObject", None)
                if vobj is None:
                    return _err(f"{obj_name} has no ViewObject (is the GUI loaded?)")
                vobj.Visibility = bool(visible)
                FreeCADGui.updateGui()
                return _ok(name=obj_name, visible=bool(visible))
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def isolate_object(self, doc_name=None, obj_names=None):
        """Hide every object in the doc except those listed.

        Returns ``prior_visibility`` — a `{name: bool}` map of pre-isolation
        states — which can be passed to ``restore_visibility`` to put things
        back exactly as they were.
        """
        def task():
            try:
                if not obj_names:
                    return _err("obj_names is required (string or list)")
                if isinstance(obj_names, str):
                    keep = {n.strip() for n in obj_names.split(",") if n.strip()}
                else:
                    keep = {str(n) for n in obj_names}
                doc = _resolve_doc(doc_name)
                prior = {}
                for o in doc.Objects:
                    vobj = getattr(o, "ViewObject", None)
                    if vobj is None:
                        continue
                    try:
                        prior[o.Name] = bool(vobj.Visibility)
                    except Exception:
                        continue
                    try:
                        vobj.Visibility = (o.Name in keep)
                    except Exception:
                        pass
                FreeCADGui.updateGui()
                return _ok(prior_visibility=prior, kept=sorted(keep))
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def restore_visibility(self, doc_name=None, prior_visibility=None):
        """Restore Visibility flags from a {name: bool} map."""
        def task():
            try:
                if not prior_visibility:
                    return _err("prior_visibility mapping is required")
                doc = _resolve_doc(doc_name)
                restored = {}
                for name, want in prior_visibility.items():
                    obj = doc.getObject(name)
                    if obj is None:
                        continue
                    vobj = getattr(obj, "ViewObject", None)
                    if vobj is None:
                        continue
                    try:
                        vobj.Visibility = bool(want)
                        restored[name] = bool(want)
                    except Exception:
                        pass
                FreeCADGui.updateGui()
                return _ok(restored=restored)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    # ---------- Multi-view capture ----------

    def capture_views(self, views=None, focus_object=None, width=None, height=None):
        """Snapshot the active 3D view from several standard orientations in one
        round-trip. Default sequence: Top, Front, Right, Isometric. The camera
        is restored to Isometric when finished so the user's working view
        isn't disturbed.

        Returns ``{success, images: {view_name: base64_png_or_error}}``.
        """
        if not views:
            view_list = ["Top", "Front", "Right", "Isometric"]
        elif isinstance(views, str):
            view_list = [v.strip() for v in views.split(",") if v.strip()]
        else:
            view_list = [str(v) for v in views]

        files = []
        for v in view_list:
            fd, tmp = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            files.append((v, tmp))

        capture_errors = {}

        def render():
            view = _ensure_active_view()
            if view is None:
                return "no 3d view available"
            for v_name, tmp_path in files:
                try:
                    method = self.VIEW_NAMES.get(v_name)
                    if method and hasattr(view, method):
                        getattr(view, method)()
                    else:
                        capture_errors[v_name] = f"unknown view {v_name!r}"
                        continue
                    if focus_object:
                        doc = FreeCAD.ActiveDocument
                        obj = doc.getObject(focus_object) if doc else None
                        if obj:
                            FreeCADGui.Selection.clearSelection()
                            FreeCADGui.Selection.addSelection(obj)
                            FreeCADGui.SendMsgToActiveView("ViewSelection")
                            FreeCADGui.Selection.clearSelection()
                        else:
                            view.fitAll()
                    else:
                        view.fitAll()
                    FreeCADGui.updateGui()
                    if width and height:
                        view.saveImage(tmp_path, int(width), int(height))
                    else:
                        view.saveImage(tmp_path)
                except Exception as e:
                    capture_errors[v_name] = str(e)
            # Restore working view to Isometric + fit-all
            try:
                view.viewIsometric()
                view.fitAll()
                FreeCADGui.updateGui()
            except Exception:
                pass
            return True

        try:
            res = _run_on_gui(render, self.TIMEOUT)
            if res is not True:
                return _err(f"capture_views failed: {res}")
            images = {}
            for v_name, tmp_path in files:
                if v_name in capture_errors:
                    images[v_name] = {"error": capture_errors[v_name]}
                    continue
                if os.path.exists(tmp_path):
                    try:
                        with open(tmp_path, "rb") as f:
                            images[v_name] = base64.b64encode(f.read()).decode("utf-8")
                    except Exception as e:
                        images[v_name] = {"error": str(e)}
                else:
                    images[v_name] = {"error": "image not written"}
            return _ok(images=images, views=view_list)
        finally:
            for _, tmp_path in files:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

    # ---------- Cross-section ----------

    def cross_section(self, doc_name=None, obj_name=None, plane="XY",
                      offset=0.0, width=None, height=None):
        """Slice ``obj_name`` with a plane and return a screenshot from a
        view perpendicular to that plane plus a JSON summary of the section
        geometry (edge count, closed-wire count, per-wire area).

        plane=
          'XY' → slice at z=offset, screenshot from Top
          'XZ' → slice at y=offset, screenshot from Front
          'YZ' → slice at x=offset, screenshot from Right

        The screenshot shows the part cut open at the plane (the half nearer
        the camera removed, everything else hidden) with the section profile
        drawn red and thick. The temporary objects are removed and visibility
        is restored before returning, so the doc is unchanged.
        """
        import Part

        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        cleanup_state = {"section": None, "plane": None}

        def build_and_shoot():
            try:
                if not obj_name:
                    return _err("obj_name is required")
                doc = _resolve_doc(doc_name)
                obj = _resolve_obj(doc, obj_name)
                shape = getattr(obj, "Shape", None)
                if shape is None or shape.isNull():
                    return _err(f"{obj_name} has no usable Shape")
                bbox = shape.BoundBox
                c = bbox.Center
                big = max(bbox.DiagonalLength, 1.0) * 2 + 10.0
                off = float(offset)
                # `keep` is the half of space on the far side of the cut from
                # the camera, so the screenshot shows the cut face itself.
                if plane == "XY":      # viewed from +Z: keep z <= offset
                    normal = FreeCAD.Vector(0, 0, 1)
                    keep = Part.makeBox(2 * big, 2 * big, big, FreeCAD.Vector(c.x - big, c.y - big, off - big))
                    view_method = "viewTop"
                elif plane == "XZ":    # viewed from -Y: keep y >= offset
                    normal = FreeCAD.Vector(0, 1, 0)
                    keep = Part.makeBox(2 * big, big, 2 * big, FreeCAD.Vector(c.x - big, off, c.z - big))
                    view_method = "viewFront"
                elif plane == "YZ":    # viewed from +X: keep x <= offset
                    normal = FreeCAD.Vector(1, 0, 0)
                    keep = Part.makeBox(big, 2 * big, 2 * big, FreeCAD.Vector(off - big, c.y - big, c.z - big))
                    view_method = "viewRight"
                else:
                    return _err(f"unknown plane {plane!r}; expected XY, XZ, or YZ")

                try:
                    wires = shape.slice(normal, off)
                except Exception as e:
                    return _err(f"section failed: {e}")
                if not wires:
                    return _err(f"section produced no intersection at {plane}={offset}")
                section_shape = Part.Compound(wires)

                # Hide everything, then show only the cut-away half and the
                # section profile. cleanup() restores visibility.
                hidden = []
                for o in doc.Objects:
                    vo = getattr(o, "ViewObject", None)
                    try:
                        if vo is not None and vo.Visibility:
                            vo.Visibility = False
                            hidden.append(o.Name)
                    except Exception:
                        pass
                cleanup_state["hidden"] = hidden

                try:
                    cut_shape = shape.common(keep)
                    if cut_shape.isNull() or not cut_shape.Faces:
                        cut_shape = None
                except Exception:
                    cut_shape = None
                if cut_shape is not None:
                    cut_obj = doc.addObject("Part::Feature", "_TempCut")
                    cut_obj.Shape = cut_shape
                    cleanup_state["plane"] = cut_obj.Name

                section_obj = doc.addObject("Part::Feature", "_TempSection")
                section_obj.Shape = section_shape
                cleanup_state["section"] = section_obj.Name
                try:
                    section_obj.ViewObject.LineColor = (1.0, 0.15, 0.15)
                    section_obj.ViewObject.LineWidth = 3.0
                    section_obj.ViewObject.PointColor = (1.0, 0.15, 0.15)
                    section_obj.ViewObject.PointSize = 6.0
                except Exception:
                    pass

                doc.recompute()
                FreeCADGui.updateGui()

                view = _ensure_active_view()
                if view is None:
                    return _err("no 3D view available")
                try:
                    if hasattr(view, view_method):
                        getattr(view, view_method)()
                except Exception:
                    pass
                view.fitAll()
                FreeCADGui.updateGui()
                if width and height:
                    view.saveImage(tmp, int(width), int(height))
                else:
                    view.saveImage(tmp)

                edges = list(section_shape.Edges)
                edge_count = len(edges)
                wire_summary = []
                wire_count = 0
                try:
                    groups = Part.sortEdges(edges) if edges else []
                    wire_count = len(groups)
                    for group in groups:
                        try:
                            w = Part.Wire(group)
                            if w.isClosed():
                                try:
                                    f = Part.Face(w)
                                    wire_summary.append({
                                        "closed": True,
                                        "edge_count": len(group),
                                        "area": float(f.Area),
                                    })
                                except Exception:
                                    wire_summary.append({
                                        "closed": True,
                                        "edge_count": len(group),
                                        "length": float(w.Length),
                                    })
                            else:
                                wire_summary.append({
                                    "closed": False,
                                    "edge_count": len(group),
                                    "length": float(w.Length),
                                })
                        except Exception as e:
                            wire_summary.append({"error": str(e)})
                except Exception:
                    pass

                return _ok(
                    plane=plane,
                    offset=float(offset),
                    edge_count=edge_count,
                    wire_count=wire_count,
                    wires=wire_summary,
                )
            except Exception as e:
                return _err(e)

        def cleanup():
            try:
                doc = FreeCAD.ActiveDocument
                if doc is None:
                    return True
                for n in (cleanup_state["section"], cleanup_state["plane"]):
                    if n:
                        try:
                            doc.removeObject(n)
                        except Exception:
                            pass
                for n in cleanup_state.get("hidden") or []:
                    try:
                        doc.getObject(n).ViewObject.Visibility = True
                    except Exception:
                        pass
                doc.recompute()
                FreeCADGui.updateGui()
            except Exception:
                pass
            return True

        try:
            result = _run_on_gui(build_and_shoot, self.TIMEOUT)
            _run_on_gui(cleanup, self.TIMEOUT)
            if isinstance(result, dict) and result.get("success"):
                if os.path.exists(tmp):
                    with open(tmp, "rb") as f:
                        result["image"] = base64.b64encode(f.read()).decode("utf-8")
            return result
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass

    # ---------- Sketch introspection ----------

    def query_sketch(self, doc_name=None, sketch_name=None):
        """Inspect how the kernel resolves a sketch into closed faces.

        Returns ``edge_count`` (raw edges in the sketch), ``closed_face_count``
        (closed wires that successfully form a face), ``open_chain_count``
        (chains that don't close), plus per-face area + bbox.

        Use BEFORE ``pad_sketch`` / ``pocket_through`` to confirm the sketch
        encloses the area you intended. Catches problems like:
          - missing the closing segment of a polyline
          - polyline points coincident but not snapped (tiny gap → open wire)
          - winding-order issues that resolve to a smaller face than expected
        """
        import Part

        def task():
            try:
                if not sketch_name:
                    return _err("sketch_name is required")
                doc = _resolve_doc(doc_name)
                obj = _resolve_obj(doc, sketch_name)
                shape = getattr(obj, "Shape", None)
                if shape is None or shape.isNull():
                    return _err(f"{sketch_name} has no Shape")
                edges = list(shape.Edges)
                edge_count = len(edges)

                closed_faces = []
                open_chains = []
                try:
                    groups = Part.sortEdges(edges) if edges else []
                except Exception:
                    groups = []
                for group in groups:
                    try:
                        w = Part.Wire(group)
                        if w.isClosed():
                            try:
                                f = Part.Face(w)
                                bb = f.BoundBox
                                closed_faces.append({
                                    "edge_count": len(group),
                                    "area": float(f.Area),
                                    "perimeter": float(w.Length),
                                    "bbox": {
                                        "x_min": bb.XMin, "x_max": bb.XMax,
                                        "y_min": bb.YMin, "y_max": bb.YMax,
                                        "z_min": bb.ZMin, "z_max": bb.ZMax,
                                    },
                                })
                            except Exception as e:
                                closed_faces.append({
                                    "edge_count": len(group),
                                    "perimeter": float(w.Length),
                                    "face_error": str(e),
                                })
                        else:
                            open_chains.append({
                                "edge_count": len(group),
                                "length": float(w.Length),
                            })
                    except Exception as e:
                        open_chains.append({
                            "edge_count": len(group),
                            "error": str(e),
                        })

                return _ok(
                    name=sketch_name,
                    edge_count=edge_count,
                    closed_face_count=len(closed_faces),
                    open_chain_count=len(open_chains),
                    total_face_area=sum(
                        f.get("area", 0.0) for f in closed_faces if "area" in f
                    ),
                    closed_faces=closed_faces,
                    open_chains=open_chains,
                )
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    # ---------- Bodies / primitives ----------

    def create_body(self, doc_name=None, name="Body"):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _with_undo(doc, f"Create body {name}",
                                  lambda d: d.addObject("PartDesign::Body", name))
                return _ok(obj=body)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    _PRIMITIVE_TYPES = {
        "box": "Part::Box", "cylinder": "Part::Cylinder", "sphere": "Part::Sphere",
        "cone": "Part::Cone", "torus": "Part::Torus",
    }

    def create_primitive(self, doc_name=None, kind="box", name=None, properties=None, placement=None):
        def task():
            try:
                type_id = self._PRIMITIVE_TYPES.get(kind)
                if not type_id:
                    return _err(f"unknown primitive: {kind}")
                doc = _resolve_doc(doc_name)

                def build(d):
                    obj = d.addObject(type_id, name or kind.capitalize())
                    for prop, val in (properties or {}).items():
                        if prop in obj.PropertiesList:
                            try:
                                setattr(obj, prop, val)
                            except Exception:
                                pass
                    if placement:
                        obj.Placement = _placement_from_dict(placement)
                    return obj

                obj = _with_undo(doc, f"Create {kind}", build)
                return _ok(obj=obj)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def transform_object(self, doc_name, obj_name, placement=None, translation=None, rotation_deg=None, axis=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                obj = _resolve_obj(doc, obj_name)

                def apply(d):
                    if placement:
                        obj.Placement = _placement_from_dict(placement)
                        return
                    pl = obj.Placement
                    if translation:
                        pl.Base = pl.Base + FreeCAD.Vector(
                            translation.get("x", 0), translation.get("y", 0), translation.get("z", 0),
                        )
                    if rotation_deg is not None and axis:
                        pl.Rotation = pl.Rotation.multiply(FreeCAD.Rotation(
                            FreeCAD.Vector(axis.get("x", 0), axis.get("y", 0), axis.get("z", 1)),
                            float(rotation_deg),
                        ))
                    obj.Placement = pl

                _with_undo(doc, f"Transform {obj_name}", apply)
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def delete_object(self, doc_name, obj_name):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                _with_undo(doc, f"Delete {obj_name}", lambda d: d.removeObject(obj_name))
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    # ---------- Sketch ----------

    _PLANES = {"XY": "XY_Plane", "XZ": "XZ_Plane", "YZ": "YZ_Plane"}

    def create_sketch(self, doc_name=None, body_name=None, plane="XY", name=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)

                def build(d):
                    if body_name:
                        body = _resolve_obj(d, body_name)
                        sketch = body.newObject("Sketcher::SketchObject", name or "Sketch")
                        # Match on Label (stable across bodies) not Name (gets suffixed).
                        label_map = {"XY": "XY-plane", "XZ": "XZ-plane", "YZ": "YZ-plane"}
                        want_label = label_map[plane]
                        # Fallback: first 2 chars of Name (e.g. "XY_Plane001" → "XY")
                        want_prefix = plane.upper()
                        target = None
                        for feat in body.Origin.OutList:
                            if getattr(feat, "Label", "") == want_label:
                                target = feat
                                break
                        if target is None:
                            for feat in body.Origin.OutList:
                                if feat.Name.startswith(want_prefix) and "Plane" in feat.Name:
                                    target = feat
                                    break
                        if target is None:
                            raise ValueError(f"Could not find {plane} plane in body {body_name}")
                        attach_attr = "AttachmentSupport" if hasattr(sketch, "AttachmentSupport") else "Support"
                        setattr(sketch, attach_attr, (target, [""]))
                        sketch.MapMode = "FlatFace"
                    else:
                        sketch = d.addObject("Sketcher::SketchObject", name or "Sketch")
                        sketch.Placement = FreeCAD.Placement(
                            FreeCAD.Vector(),
                            FreeCAD.Rotation(
                                *{
                                    "XY": (FreeCAD.Vector(0, 0, 1), 0),
                                    "XZ": (FreeCAD.Vector(1, 0, 0), 90),
                                    "YZ": (FreeCAD.Vector(0, 1, 0), 90),
                                }[plane]
                            ),
                        )
                    return sketch

                sk = _with_undo(doc, "Create sketch", build)
                return _ok(obj=sk)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def add_sketch_rectangle(self, doc_name, sketch_name, x, y, width, height):
        def task():
            try:
                import Part as Part_
                doc = _resolve_doc(doc_name)
                sk = _resolve_obj(doc, sketch_name)

                def build(d):
                    x0, y0, x1, y1 = float(x), float(y), float(x) + float(width), float(y) + float(height)
                    p00 = FreeCAD.Vector(x0, y0, 0)
                    p10 = FreeCAD.Vector(x1, y0, 0)
                    p11 = FreeCAD.Vector(x1, y1, 0)
                    p01 = FreeCAD.Vector(x0, y1, 0)
                    base = len(sk.Geometry)
                    sk.addGeometry(Part_.LineSegment(p00, p10), False)
                    sk.addGeometry(Part_.LineSegment(p10, p11), False)
                    sk.addGeometry(Part_.LineSegment(p11, p01), False)
                    sk.addGeometry(Part_.LineSegment(p01, p00), False)
                    return [base + i for i in range(4)]

                ids = _with_undo(doc, "Sketch rectangle", build)
                return _ok(geometry_ids=ids)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def add_sketch_circle(self, doc_name, sketch_name, cx, cy, radius):
        def task():
            try:
                import Part as Part_
                doc = _resolve_doc(doc_name)
                sk = _resolve_obj(doc, sketch_name)

                def build(d):
                    circ = Part_.Circle(FreeCAD.Vector(float(cx), float(cy), 0),
                                        FreeCAD.Vector(0, 0, 1), float(radius))
                    return sk.addGeometry(circ, False)

                gid = _with_undo(doc, "Sketch circle", build)
                return _ok(geometry_id=gid)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def add_sketch_line(self, doc_name, sketch_name, x1, y1, x2, y2):
        def task():
            try:
                import Part as Part_
                doc = _resolve_doc(doc_name)
                sk = _resolve_obj(doc, sketch_name)

                def build(d):
                    seg = Part_.LineSegment(
                        FreeCAD.Vector(float(x1), float(y1), 0),
                        FreeCAD.Vector(float(x2), float(y2), 0),
                    )
                    return sk.addGeometry(seg, False)

                gid = _with_undo(doc, "Sketch line", build)
                return _ok(geometry_id=gid)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def add_sketch_polyline(self, doc_name, sketch_name, points, closed=True):
        def task():
            try:
                import Part as Part_
                doc = _resolve_doc(doc_name)
                sk = _resolve_obj(doc, sketch_name)
                pts = [FreeCAD.Vector(float(p[0]), float(p[1]), 0) for p in points]

                def build(d):
                    ids = []
                    base = len(sk.Geometry)
                    for i in range(len(pts) - 1):
                        sk.addGeometry(Part_.LineSegment(pts[i], pts[i + 1]), False)
                        ids.append(base + i)
                    if closed:
                        sk.addGeometry(Part_.LineSegment(pts[-1], pts[0]), False)
                        ids.append(base + len(pts) - 1)
                    return ids

                ids = _with_undo(doc, "Sketch polyline", build)
                return _ok(geometry_ids=ids)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    # ---------- PartDesign features ----------

    def pad_sketch(self, doc_name, body_name, sketch_name, length=10.0, reversed=False, midplane=False, name=None):
        def task():
            try:
                _check(check_positive("length", length))
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                sk = _resolve_obj(doc, sketch_name)

                def build(d):
                    pad = body.newObject("PartDesign::Pad", name or "Pad")
                    pad.Profile = sk
                    pad.Length = float(length)
                    pad.Reversed = bool(reversed)
                    if "Midplane" in pad.PropertiesList:
                        pad.Midplane = bool(midplane)
                    return pad

                pad = _with_undo(doc, "Pad", build)
                return _ok(obj=pad)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def pocket_sketch(self, doc_name, body_name, sketch_name, depth=10.0, reversed=False, midplane=False, name=None, timeout_ms=None):
        def task():
            try:
                _check(check_positive("depth", depth))
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                sk = _resolve_obj(doc, sketch_name)

                def build(d):
                    p = body.newObject("PartDesign::Pocket", name or "Pocket")
                    p.Profile = sk
                    p.Length = float(depth)
                    p.Reversed = bool(reversed)
                    if "Midplane" in p.PropertiesList:
                        p.Midplane = bool(midplane)
                    return p

                po = _with_undo(doc, "Pocket", build)
                return _ok(obj=po)
            except Exception as e:
                return _err(e)
        timeout = (timeout_ms / 1000.0) if timeout_ms else self.TIMEOUT
        return _run_on_gui(task, timeout)

    def revolve_sketch(self, doc_name, body_name, sketch_name, axis="X", angle=360.0, name=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                sk = _resolve_obj(doc, sketch_name)

                def build(d):
                    r = body.newObject("PartDesign::Revolution", name or "Revolution")
                    r.Profile = sk
                    r.Angle = float(angle)
                    axis_obj = _find_body_axis(body, axis)
                    if axis_obj is not None:
                        r.ReferenceAxis = (axis_obj, [""])
                    return r

                rv = _with_undo(doc, "Revolution", build)
                return _ok(obj=rv)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def fillet_edges(self, doc_name, body_name, base_name, edges, radius=1.0, name=None):
        """edges: list of 1-based edge indices on base_name."""
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                base = _resolve_obj(doc, base_name)
                # Pre-execution feasibility check: radius vs shortest selected edge.
                base_shape = getattr(base, "Shape", None)
                if base_shape is not None and getattr(base_shape, "Edges", None):
                    try:
                        lengths = [base_shape.Edges[int(i) - 1].Length for i in edges]
                        if lengths:
                            _check(check_fillet_radius(radius, min(lengths)))
                    except (IndexError, AttributeError):
                        pass  # selection check will fail downstream with a clearer error

                def build(d):
                    f = body.newObject("PartDesign::Fillet", name or "Fillet")
                    f.Base = (base, [f"Edge{int(i)}" for i in edges])
                    f.Radius = float(radius)
                    return f

                ff = _with_undo(doc, "Fillet", build)
                return _ok(obj=ff)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def chamfer_edges(self, doc_name, body_name, base_name, edges, size=1.0, name=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                base = _resolve_obj(doc, base_name)
                base_shape = getattr(base, "Shape", None)
                if base_shape is not None and getattr(base_shape, "Edges", None):
                    try:
                        lengths = [base_shape.Edges[int(i) - 1].Length for i in edges]
                        if lengths:
                            _check(check_chamfer_size(size, min(lengths)))
                    except (IndexError, AttributeError):
                        pass

                def build(d):
                    c = body.newObject("PartDesign::Chamfer", name or "Chamfer")
                    c.Base = (base, [f"Edge{int(i)}" for i in edges])
                    c.Size = float(size)
                    return c

                cc = _with_undo(doc, "Chamfer", build)
                return _ok(obj=cc)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def shell_object(self, doc_name, body_name, base_name, faces, thickness=1.0, name=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                base = _resolve_obj(doc, base_name)

                def build(d):
                    t = body.newObject("PartDesign::Thickness", name or "Shell")
                    t.Base = (base, [f"Face{int(i)}" for i in faces])
                    t.Value = float(thickness)
                    t.Mode = 0  # Skin
                    return t

                tt = _with_undo(doc, "Shell", build)
                return _ok(obj=tt)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def linear_pattern(self, doc_name, body_name, feature_names, direction="X", length=10.0, occurrences=2, name=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                features = [_resolve_obj(doc, f) for f in feature_names]

                def build(d):
                    lp = body.newObject("PartDesign::LinearPattern", name or "LinearPattern")
                    lp.Originals = features
                    lp.Length = float(length)
                    lp.Occurrences = int(occurrences)
                    axis_obj = _find_body_axis(body, direction)
                    if axis_obj is None:
                        raise ValueError(f"axis {direction} not found in body {body_name}")
                    lp.Direction = (axis_obj, [""])
                    # Transform features (pattern/mirror) don't auto-advance Tip; do it
                    # explicitly so subsequent features see the patterned geometry.
                    body.Tip = lp
                    return lp

                p = _with_undo(doc, "Linear pattern", build)
                return _ok(obj=p)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def polar_pattern(self, doc_name, body_name, feature_names, axis="Z", angle=360.0, occurrences=4, name=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                features = [_resolve_obj(doc, f) for f in feature_names]

                def build(d):
                    pp = body.newObject("PartDesign::PolarPattern", name or "PolarPattern")
                    pp.Originals = features
                    pp.Angle = float(angle)
                    pp.Occurrences = int(occurrences)
                    axis_obj = _find_body_axis(body, axis)
                    if axis_obj is None:
                        raise ValueError(f"axis {axis} not found in body {body_name}")
                    pp.Axis = (axis_obj, [""])
                    body.Tip = pp
                    return pp

                p = _with_undo(doc, "Polar pattern", build)
                return _ok(obj=p)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def create_sketch_offset(self, doc_name, body_name, plane, offset_mm, name=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                plane_feat = _find_origin_plane(body, plane)
                if plane_feat is None:
                    raise ValueError(f"plane {plane} not found in body {body_name}")

                offset_vecs = {
                    "XY": FreeCAD.Vector(0, 0, float(offset_mm)),
                    "XZ": FreeCAD.Vector(0, float(offset_mm), 0),
                    "YZ": FreeCAD.Vector(float(offset_mm), 0, 0),
                }
                offset_vec = offset_vecs[plane]

                def build(d):
                    dp = body.newObject("PartDesign::Plane", (name or "DatumPlane") + "_datum")
                    _set_support(dp, (plane_feat, [""]))
                    dp.MapMode = "FlatFace"
                    dp.AttachmentOffset = FreeCAD.Placement(offset_vec, FreeCAD.Rotation())
                    d.recompute()
                    sk = body.newObject("Sketcher::SketchObject", name or "Sketch")
                    attach_attr = "AttachmentSupport" if hasattr(sk, "AttachmentSupport") else "Support"
                    setattr(sk, attach_attr, (dp, [""]))
                    sk.MapMode = "FlatFace"
                    return sk

                sk = _with_undo(doc, "Sketch offset", build)
                return _ok(obj=sk)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def create_sketch_on_face(self, doc_name, body_name, base_name, face_index=1, name=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                base_feat = body.Tip if base_name == "tip" else _resolve_obj(doc, base_name)

                def build(d):
                    sk = body.newObject("Sketcher::SketchObject", name or "Sketch")
                    attach_attr = "AttachmentSupport" if hasattr(sk, "AttachmentSupport") else "Support"
                    setattr(sk, attach_attr, [(base_feat, f"Face{int(face_index)}")])
                    sk.MapMode = "FlatFace"
                    return sk

                sk = _with_undo(doc, "Sketch on face", build)
                return _ok(obj=sk)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def groove_sketch(self, doc_name, body_name, sketch_name, axis="Z", angle=360.0, name=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                sk = _resolve_obj(doc, sketch_name)

                def build(d):
                    g = body.newObject("PartDesign::Groove", name or "Groove")
                    g.Profile = sk
                    g.Angle = float(angle)
                    axis_obj = _find_body_axis(body, axis)
                    if axis_obj is not None:
                        g.ReferenceAxis = (axis_obj, [""])
                    return g

                gv = _with_undo(doc, "Groove", build)
                return _ok(obj=gv)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def sweep_sketch(self, doc_name, body_name, profile_name, spine_name, name=None, timeout_ms=None):
        timeout = int(timeout_ms) if timeout_ms else self.TIMEOUT

        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                profile_sk = _resolve_obj(doc, profile_name)
                spine_sk = _resolve_obj(doc, spine_name)

                def build(d):
                    pipe = body.newObject("PartDesign::Pipe", name or "Pipe")
                    pipe.Profile = profile_sk
                    pipe.Spine = (spine_sk, ["Edge1"])
                    return pipe

                pv = _with_undo(doc, "Sweep", build)
                return _ok(obj=pv)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, timeout)

    def mirrored(self, doc_name, body_name, feature_names, plane="XY", name=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                features = [_resolve_obj(doc, f) for f in feature_names]
                plane_feat = _find_origin_plane(body, plane)
                if plane_feat is None:
                    raise ValueError(f"plane {plane} not found in body {body_name}")

                def build(d):
                    mir = body.newObject("PartDesign::Mirrored", name or "Mirrored")
                    mir.Originals = features
                    mir.MirrorPlane = (plane_feat, [""])
                    body.Tip = mir
                    return mir

                mv = _with_undo(doc, "Mirrored", build)
                return _ok(obj=mv)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def duplicate_body(self, doc_name, source_name, name=None,
                       x=0.0, y=0.0, z=0.0,
                       rot_x_deg=0.0, rot_y_deg=0.0, rot_z_deg=0.0):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                source = _resolve_obj(doc, source_name)

                def build(d):
                    new_obj = doc.addObject("Part::Feature", name or f"{source_name}_copy")
                    new_obj.Shape = source.Shape.copy()
                    rx = FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), float(rot_x_deg))
                    ry = FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), float(rot_y_deg))
                    rz = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), float(rot_z_deg))
                    rot = rz.multiply(ry.multiply(rx))
                    new_obj.Placement = FreeCAD.Placement(FreeCAD.Vector(float(x), float(y), float(z)), rot)
                    return new_obj

                obj = _with_undo(doc, "Duplicate body", build)
                return _ok(obj=obj)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    # ---------- Boolean (Part workbench level) ----------

    def boolean(self, doc_name, op, a, b, name=None, timeout_ms=None):
        """op: 'union' | 'cut' | 'common'"""
        def task():
            try:
                doc = _resolve_doc(doc_name)
                obj_a = _resolve_obj(doc, a)
                obj_b = _resolve_obj(doc, b)
                type_map = {"union": "Part::Fuse", "cut": "Part::Cut", "common": "Part::Common"}
                type_id = type_map.get(op)
                if not type_id:
                    return _err(f"unknown boolean op: {op}")

                def build(d):
                    obj = d.addObject(type_id, name or op.capitalize())
                    obj.Base = obj_a
                    obj.Tool = obj_b
                    return obj

                o = _with_undo(doc, f"Boolean {op}", build)
                return _ok(obj=o)
            except Exception as e:
                return _err(e)
        timeout = (timeout_ms / 1000.0) if timeout_ms else self.TIMEOUT
        return _run_on_gui(task, timeout)

    # ---------- Parametric ----------

    def create_spreadsheet(self, doc_name=None, name="Variables"):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                obj = _with_undo(doc, f"Create spreadsheet {name}",
                                 lambda d: d.addObject("Spreadsheet::Sheet", name))
                return _ok(obj=obj)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def set_cell(self, doc_name, sheet_name, cell, value, alias=None):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                sheet = _resolve_obj(doc, sheet_name)

                def build(d):
                    sheet.set(cell, str(value))
                    if alias:
                        sheet.setAlias(cell, alias)
                    return None

                _with_undo(doc, f"Set cell {cell}", build)
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def set_expression(self, doc_name, obj_name, property_path, expression):
        """property_path: 'Length', 'Placement.Base.x', etc. Empty expression clears."""
        def task():
            try:
                doc = _resolve_doc(doc_name)
                obj = _resolve_obj(doc, obj_name)

                def build(d):
                    obj.setExpression(property_path, expression if expression else None)
                    return None

                _with_undo(doc, f"Expression {obj_name}.{property_path}", build)
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def modify_property(self, doc_name, obj_name, property_name, value):
        def task():
            try:
                doc = _resolve_doc(doc_name)
                obj = _resolve_obj(doc, obj_name)

                def build(d):
                    if property_name not in obj.PropertiesList:
                        raise ValueError(f"no such property: {property_name}")
                    cur = getattr(obj, property_name)
                    if isinstance(cur, FreeCAD.Vector) and isinstance(value, dict):
                        setattr(obj, property_name, FreeCAD.Vector(
                            value.get("x", 0), value.get("y", 0), value.get("z", 0),
                        ))
                    elif isinstance(cur, FreeCAD.Placement) and isinstance(value, dict):
                        setattr(obj, property_name, _placement_from_dict(value))
                    else:
                        setattr(obj, property_name, value)
                    return None

                _with_undo(doc, f"Set {obj_name}.{property_name}", build)
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    # ---------- Export ----------

    def export_step(self, doc_name, obj_names, path, timeout_ms=None):
        """Export objects to a STEP file.  Default timeout is 300 s — large
        assemblies (50+ bodies with perforated panels) take minutes."""
        def task():
            try:
                import Import as Import_
                doc = _resolve_doc(doc_name)
                objs = [_resolve_obj(doc, n) for n in obj_names]
                Import_.export(objs, path)
                return _ok(path=path)
            except Exception as e:
                return _err(e)
        timeout = (timeout_ms / 1000.0) if timeout_ms else 300
        return _run_on_gui(task, timeout)

    def export_stl(self, doc_name, obj_names, path, timeout_ms=None):
        """Export objects to an STL file.  Default timeout is 300 s."""
        def task():
            try:
                import Mesh as Mesh_
                doc = _resolve_doc(doc_name)
                objs = [_resolve_obj(doc, n) for n in obj_names]
                Mesh_.export(objs, path)
                return _ok(path=path)
            except Exception as e:
                return _err(e)
        timeout = (timeout_ms / 1000.0) if timeout_ms else 300
        return _run_on_gui(task, timeout)

    def export_fcstd(self, doc_name, path, timeout_ms=None):
        """Save the document to a .FCStd file.  Default timeout is 300 s."""
        def task():
            try:
                _resolve_doc(doc_name).saveAs(path)
                return _ok(path=path)
            except Exception as e:
                return _err(e)
        timeout = (timeout_ms / 1000.0) if timeout_ms else 300
        return _run_on_gui(task, timeout)

    # ---------- High-level helpers ----------
    #
    # Each of these was a common ~10-line pattern hand-written via execute_code
    # during complex builds.  Promoting them to first-class tools means agents
    # can discover and reuse them without re-deriving the coordinate algebra
    # or the plane-lookup trick.

    def rotate_about_axis(self, doc_name, obj_name, pivot, axis, angle_deg):
        """Rotate ``obj_name`` by ``angle_deg`` around a world-space axis.

        ``pivot`` and ``axis`` are ``{x, y, z}`` dicts.  The new placement is
        computed as ``T(pivot) · R(axis, θ) · T(-pivot) · original_placement``
        so the object pivots around an arbitrary world point, not its own
        local origin (which is what the base Placement rotation gives you).
        """
        def task():
            try:
                doc = _resolve_doc(doc_name)
                obj = _resolve_obj(doc, obj_name)
                px = float(pivot.get("x", 0)); py = float(pivot.get("y", 0)); pz = float(pivot.get("z", 0))
                ax = float(axis.get("x", 0));  ay = float(axis.get("y", 0));  az = float(axis.get("z", 1))
                pivot_v = FreeCAD.Vector(px, py, pz)
                axis_v = FreeCAD.Vector(ax, ay, az)
                T_back = FreeCAD.Placement(pivot_v, FreeCAD.Rotation())
                T_to = FreeCAD.Placement(FreeCAD.Vector(-px, -py, -pz), FreeCAD.Rotation())
                R = FreeCAD.Placement(FreeCAD.Vector(), FreeCAD.Rotation(axis_v, float(angle_deg)))
                composite = T_back.multiply(R).multiply(T_to).multiply(obj.Placement)

                def apply(d):
                    obj.Placement = composite
                    return obj

                _with_undo(doc, f"Rotate {obj_name}", apply)
                return _ok(obj=obj)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def pocket_through(self, doc_name, body_name, sketch_name, margin=1.0, name=None, timeout_ms=None):
        """Pocket that cuts cleanly through the body in the sketch-normal direction.

        Projects the body bbox onto the sketch normal to get the thickness,
        then creates a Midplane pocket of length ``thickness + 2*margin`` so
        the cut cleanly exits both sides of the body.  No direction guessing.
        """
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                sk = _resolve_obj(doc, sketch_name)
                sk_normal = sk.Placement.Rotation.multVec(FreeCAD.Vector(0, 0, 1))
                bb = body.Shape.BoundBox
                corners = [
                    FreeCAD.Vector(bb.XMin, bb.YMin, bb.ZMin),
                    FreeCAD.Vector(bb.XMax, bb.YMin, bb.ZMin),
                    FreeCAD.Vector(bb.XMin, bb.YMax, bb.ZMin),
                    FreeCAD.Vector(bb.XMax, bb.YMax, bb.ZMin),
                    FreeCAD.Vector(bb.XMin, bb.YMin, bb.ZMax),
                    FreeCAD.Vector(bb.XMax, bb.YMin, bb.ZMax),
                    FreeCAD.Vector(bb.XMin, bb.YMax, bb.ZMax),
                    FreeCAD.Vector(bb.XMax, bb.YMax, bb.ZMax),
                ]
                projs = [c.dot(sk_normal) for c in corners]
                thickness = max(projs) - min(projs)
                length = thickness + 2.0 * float(margin)

                def build(d):
                    p = body.newObject("PartDesign::Pocket", name or "PocketThrough")
                    p.Profile = sk
                    p.Length = length
                    if "Midplane" in p.PropertiesList:
                        p.Midplane = True
                    p.Reversed = False
                    return p

                po = _with_undo(doc, "Pocket through", build)
                return _ok(obj=po, length=length, thickness=thickness)
            except Exception as e:
                return _err(e)
        timeout = (timeout_ms / 1000.0) if timeout_ms else self.TIMEOUT
        return _run_on_gui(task, timeout)

    def pocket_blind(self, doc_name, body_name, sketch_name, depth, reverse=False, name=None, timeout_ms=None):
        """Blind pocket of ``depth`` mm from the sketch plane.

        ``reverse=False`` cuts toward +normal of the sketch plane;
        ``reverse=True`` cuts toward -normal.  Unlike ``pocket_sketch`` this
        never uses midplane — pick the direction and commit.
        """
        def task():
            try:
                # Pre-execution feasibility check: positive depth + body extent.
                # Body extent along the sketch normal is the natural upper bound.
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                sk = _resolve_obj(doc, sketch_name)
                body_extent = None
                try:
                    sk_normal = sk.Placement.Rotation.multVec(FreeCAD.Vector(0, 0, 1))
                    bb = body.Shape.BoundBox
                    corners = [
                        FreeCAD.Vector(bb.XMin, bb.YMin, bb.ZMin),
                        FreeCAD.Vector(bb.XMax, bb.YMin, bb.ZMin),
                        FreeCAD.Vector(bb.XMin, bb.YMax, bb.ZMin),
                        FreeCAD.Vector(bb.XMax, bb.YMax, bb.ZMin),
                        FreeCAD.Vector(bb.XMin, bb.YMin, bb.ZMax),
                        FreeCAD.Vector(bb.XMax, bb.YMin, bb.ZMax),
                        FreeCAD.Vector(bb.XMin, bb.YMax, bb.ZMax),
                        FreeCAD.Vector(bb.XMax, bb.YMax, bb.ZMax),
                    ]
                    projs = [c.dot(sk_normal) for c in corners]
                    body_extent = max(projs) - min(projs)
                except Exception:
                    body_extent = None  # bbox unavailable; fall back to depth-only check
                _check(check_pocket_depth(depth, body_extent_along_normal=body_extent))

                def build(d):
                    p = body.newObject("PartDesign::Pocket", name or "PocketBlind")
                    p.Profile = sk
                    p.Length = float(depth)
                    p.Reversed = bool(reverse)
                    if "Midplane" in p.PropertiesList:
                        p.Midplane = False
                    return p

                po = _with_undo(doc, "Pocket blind", build)
                return _ok(obj=po)
            except Exception as e:
                return _err(e)
        timeout = (timeout_ms / 1000.0) if timeout_ms else self.TIMEOUT
        return _run_on_gui(task, timeout)

    def hex_grid_sketch(self, doc_name, sketch_name, umin, umax, vmin, vmax,
                        side=9.0, wall=3.0, exclusions=None, clear=True, timeout_ms=None):
        """Populate ``sketch_name`` with a flat-top honeycomb grid of hexes.

        Each hex is six LineSegments closing into a hexagonal polygon.
        Column pitch = ``1.5*side + wall``; row pitch = ``side*sqrt(3) + wall``;
        every other column is offset by half a row for the honeycomb stagger.

        ``exclusions`` is a list of ``[u0, u1, v0, v1]`` rectangles; any hex
        whose center falls inside one is skipped (use this to leave solid
        islands around mounting hardware / latch bosses / etc.).

        Replaces what used to be ~1800 ``add_sketch_polyline`` round-trips
        with a single call.
        """
        def task():
            try:
                import Part
                import math
                doc = _resolve_doc(doc_name)
                sk = _resolve_obj(doc, sketch_name)
                excl = exclusions or []

                def build(d):
                    if clear:
                        while len(sk.Geometry) > 0:
                            sk.delGeometry(0)
                    s = float(side); wall_t = float(wall)
                    dx = 1.5 * s + wall_t
                    dy = s * math.sqrt(3) + wall_t
                    half_h = s * math.sqrt(3) / 2
                    col = 0; u = float(umin) + s; count = 0
                    while u + s <= float(umax):
                        v_off = (dy / 2) if (col % 2) else 0
                        v = float(vmin) + half_h + v_off
                        while v + half_h <= float(vmax):
                            skip = False
                            for e in excl:
                                u0, u1, v0, v1 = (float(e[0]), float(e[1]),
                                                  float(e[2]), float(e[3]))
                                if u0 <= u <= u1 and v0 <= v <= v1:
                                    skip = True
                                    break
                            if not skip:
                                verts = [
                                    (u + s * math.cos(math.radians(60 * k)),
                                     v + s * math.sin(math.radians(60 * k)))
                                    for k in range(6)
                                ]
                                for i in range(6):
                                    p1 = verts[i]; p2 = verts[(i + 1) % 6]
                                    sk.addGeometry(Part.LineSegment(
                                        FreeCAD.Vector(p1[0], p1[1], 0),
                                        FreeCAD.Vector(p2[0], p2[1], 0)), False)
                                count += 1
                            v += dy
                        col += 1; u += dx
                    return count

                n = _with_undo(doc, "Hex grid", build)
                return _ok(hex_count=n)
            except Exception as e:
                return _err(e)
        timeout = (timeout_ms / 1000.0) if timeout_ms else 120
        return _run_on_gui(task, timeout)

    def countersunk_hole(self, doc_name, body_name, plane_tag, u, v,
                         shaft_r, csink_r, csink_depth, shaft_depth,
                         reverse=False, name=None):
        """Cut a clearance hole with a countersink on a body origin plane.

        ``plane_tag`` is ``'XY'``, ``'XZ'``, or ``'YZ'`` (body-local).  Creates
        two sketches + two pockets (one per radius) inside ``body_name``.
        ``reverse`` flips the cut to the other side of the sketch plane.
        """
        def task():
            try:
                # Pre-execution feasibility: counterbore must be wider than the
                # through-bore and shallower than the total depth.
                _check(check_countersink_geometry(
                    counterbore_diam=float(csink_r) * 2.0,
                    bore_diam=float(shaft_r) * 2.0,
                    counterbore_depth=float(csink_depth),
                    total_depth=float(shaft_depth),
                ))
                import Part
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                plane = _find_origin_plane(body, plane_tag)
                if plane is None:
                    return _err(f"{body_name} has no {plane_tag}_Plane")
                prefix = name or "CSK"

                def build(d):
                    # countersink cone (represented as a cylindrical pocket of csink_r)
                    csk_sk = d.addObject("Sketcher::SketchObject", f"{prefix}_CsinkCS")
                    body.addObject(csk_sk)
                    _set_support(csk_sk, [(plane, "")])
                    csk_sk.MapMode = "FlatFace"
                    csk_sk.addGeometry(Part.Circle(
                        FreeCAD.Vector(float(u), float(v), 0),
                        FreeCAD.Vector(0, 0, 1),
                        float(csink_r)), False)
                    d.recompute()
                    csk_pocket = body.newObject("PartDesign::Pocket", f"{prefix}_CsinkPocket")
                    csk_pocket.Profile = csk_sk
                    csk_pocket.Length = float(csink_depth)
                    csk_pocket.Reversed = bool(reverse)
                    if "Midplane" in csk_pocket.PropertiesList:
                        csk_pocket.Midplane = False
                    # shaft clearance hole
                    sh_sk = d.addObject("Sketcher::SketchObject", f"{prefix}_ShaftCS")
                    body.addObject(sh_sk)
                    _set_support(sh_sk, [(plane, "")])
                    sh_sk.MapMode = "FlatFace"
                    sh_sk.addGeometry(Part.Circle(
                        FreeCAD.Vector(float(u), float(v), 0),
                        FreeCAD.Vector(0, 0, 1),
                        float(shaft_r)), False)
                    d.recompute()
                    sh_pocket = body.newObject("PartDesign::Pocket", f"{prefix}_ShaftPocket")
                    sh_pocket.Profile = sh_sk
                    sh_pocket.Length = float(shaft_depth)
                    sh_pocket.Reversed = bool(reverse)
                    if "Midplane" in sh_pocket.PropertiesList:
                        sh_pocket.Midplane = False
                    return {"csink": csk_pocket.Name, "shaft": sh_pocket.Name}

                names = _with_undo(doc, "Countersunk hole", build)
                return _ok(**names)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def clear_sketch_geometry(self, doc_name, sketch_name):
        """Delete all geometry (lines, arcs, circles) from a sketch.

        Useful when reshaping a parametric panel — instead of digging through
        Sketch.delGeometry calls, wipe and redraw.
        """
        def task():
            try:
                doc = _resolve_doc(doc_name)
                sk = _resolve_obj(doc, sketch_name)

                def build(d):
                    n = 0
                    while len(sk.Geometry) > 0:
                        sk.delGeometry(0)
                        n += 1
                    return n

                n = _with_undo(doc, "Clear sketch", build)
                return _ok(removed=n)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def set_sketch_rectangle(self, doc_name, sketch_name, x, y, width, height, clear=True):
        """Replace a sketch's contents with a single rectangle.

        Same (x, y) corner + width/height semantics as ``add_sketch_rectangle``
        but clears the sketch first — used when resizing a padded panel
        without recreating the whole body.
        """
        def task():
            try:
                import Part
                doc = _resolve_doc(doc_name)
                sk = _resolve_obj(doc, sketch_name)

                def build(d):
                    if clear:
                        while len(sk.Geometry) > 0:
                            sk.delGeometry(0)
                    x1 = float(x); y1 = float(y)
                    x2 = x1 + float(width); y2 = y1 + float(height)
                    pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
                    for i in range(4):
                        a = pts[i]; b = pts[(i + 1) % 4]
                        sk.addGeometry(Part.LineSegment(
                            FreeCAD.Vector(a[0], a[1], 0),
                            FreeCAD.Vector(b[0], b[1], 0)), False)
                    return True

                _with_undo(doc, "Set rectangle", build)
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def get_origin_plane(self, doc_name, body_name, plane_tag):
        """Return the object name + label of a body's origin plane.

        ``plane_tag`` is ``'XY'``, ``'XZ'``, or ``'YZ'``.  FreeCAD suffixes
        origin-plane names with a body index (``YZ_Plane032``), so this is
        the canonical way to resolve them by programmatic convention.
        """
        def task():
            try:
                doc = _resolve_doc(doc_name)
                body = _resolve_obj(doc, body_name)
                plane = _find_origin_plane(body, plane_tag)
                if plane is None:
                    return _err(f"{body_name} has no {plane_tag}_Plane")
                return _ok(name=plane.Name, label=plane.Label)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    # ---------- Escape hatches ----------

    def execute_code(self, code, timeout_ms=None):
        """Run arbitrary Python on the GUI thread.  Default timeout is 60 s —
        bump via ``timeout_ms`` for known-heavy scripts (large hex mesh
        sketches, batch transforms, frame-sequence renders)."""
        buf = io.StringIO()

        def task():
            try:
                with contextlib.redirect_stdout(buf):
                    exec(code, globals())
                if FreeCAD.ActiveDocument:
                    FreeCAD.ActiveDocument.recompute()
                return _ok(stdout=buf.getvalue())
            except Exception as e:
                return _err(f"{e}\n{traceback.format_exc()}\nstdout_so_far: {buf.getvalue()}")

        timeout = (timeout_ms / 1000.0) if timeout_ms else 60
        return _run_on_gui(task, timeout)

    def insert_part_from_library(self, relative_path):
        def task():
            try:
                insert_part_from_library(relative_path)
                return _ok()
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)

    def get_parts_list(self):
        try:
            return _ok(get_parts_list())
        except Exception as e:
            return _err(e)

    # Low-level passthroughs for forward-compat with neka-nat-style callers.

    def create_object(self, doc_name, obj_data):
        def task():
            try:
                doc = _resolve_doc(doc_name)

                def build(d):
                    obj = d.addObject(obj_data["Type"], obj_data.get("Name", "Object"))
                    for prop, val in (obj_data.get("Properties") or {}).items():
                        if prop in obj.PropertiesList:
                            try:
                                if prop == "Placement" and isinstance(val, dict):
                                    obj.Placement = _placement_from_dict(val)
                                else:
                                    setattr(obj, prop, val)
                            except Exception:
                                pass
                    return obj

                obj = _with_undo(doc, f"Create {obj_data.get('Type', 'object')}", build)
                return _ok(obj=obj)
            except Exception as e:
                return _err(e)
        return _run_on_gui(task, self.TIMEOUT)


# ---------------------------------------------------------------------------
# Lifecycle + commands
# ---------------------------------------------------------------------------


def start_rpc_server(port=9875):
    global rpc_server_thread, rpc_server_instance
    if rpc_server_instance:
        return "Conjur3 RPC already running."

    settings = load_settings()
    host = "0.0.0.0" if settings.get("remote_enabled") else "localhost"
    allowed = settings.get("allowed_ips", "127.0.0.1")

    rpc_server_instance = FilteredXMLRPCServer(
        (host, port), allowed_ips_str=allowed, allow_none=True, logRequests=False,
    )
    rpc_server_instance.register_instance(Conjur3RPC())

    def loop():
        FreeCAD.Console.PrintMessage(f"[Conjur3] serving at {host}:{port}\n")
        rpc_server_instance.serve_forever()

    rpc_server_thread = threading.Thread(target=loop, daemon=True)
    rpc_server_thread.start()
    QtCore.QTimer.singleShot(200, process_gui_tasks)
    return f"Conjur3 RPC started at {host}:{port}"


def stop_rpc_server():
    global rpc_server_instance, rpc_server_thread
    if rpc_server_instance:
        rpc_server_instance.shutdown()
        rpc_server_thread.join(timeout=5)
        rpc_server_instance = None
        rpc_server_thread = None
        return "Conjur3 RPC stopped."
    return "Conjur3 RPC was not running."


class _StartCmd:
    def GetResources(self):
        return {"MenuText": "Start Conjur3 Server", "ToolTip": "Start the Conjur3 RPC server"}

    def Activated(self):
        FreeCAD.Console.PrintMessage(start_rpc_server() + "\n")

    def IsActive(self):
        return True


class _StopCmd:
    def GetResources(self):
        return {"MenuText": "Stop Conjur3 Server", "ToolTip": "Stop the Conjur3 RPC server"}

    def Activated(self):
        FreeCAD.Console.PrintMessage(stop_rpc_server() + "\n")

    def IsActive(self):
        return True


class _ToggleRemoteCmd:
    def GetResources(self):
        return {
            "MenuText": "Allow Remote Connections",
            "ToolTip": "Bind to 0.0.0.0 instead of localhost.",
            "Checkable": True,
        }

    def Activated(self, checked=0):
        s = load_settings()
        s["remote_enabled"] = bool(checked)
        save_settings(s)

    def IsActive(self):
        return True


class _ConfigureIPsCmd:
    def GetResources(self):
        return {"MenuText": "Configure Allowed IPs", "ToolTip": "Comma-separated list of allowed IPs/subnets."}

    def Activated(self):
        s = load_settings()
        text, ok = QtWidgets.QInputDialog.getText(
            None, "Allowed IPs",
            "Enter allowed IPs or CIDR subnets, comma-separated:",
            QtWidgets.QLineEdit.Normal, s.get("allowed_ips", "127.0.0.1"),
        )
        if not ok or not text.strip():
            return
        valid, errors = validate_allowed_ips(text.strip())
        if errors:
            QtWidgets.QMessageBox.warning(None, "Invalid IPs", "\n".join(errors))
        if valid:
            s["allowed_ips"] = ", ".join(valid)
            save_settings(s)

    def IsActive(self):
        return True


class _ToggleAutoStartCmd:
    def GetResources(self):
        return {
            "MenuText": "Auto-Start on Launch",
            "ToolTip": "Automatically start the Conjur3 RPC server on FreeCAD launch.",
            "Checkable": True,
        }

    def Activated(self, checked=0):
        s = load_settings()
        s["auto_start_rpc"] = bool(checked)
        save_settings(s)

    def IsActive(self):
        return True


FreeCADGui.addCommand("Conjur3_Start_Server", _StartCmd())
FreeCADGui.addCommand("Conjur3_Stop_Server", _StopCmd())
FreeCADGui.addCommand("Conjur3_Toggle_Auto_Start", _ToggleAutoStartCmd())
FreeCADGui.addCommand("Conjur3_Toggle_Remote", _ToggleRemoteCmd())
FreeCADGui.addCommand("Conjur3_Configure_Allowed_IPs", _ConfigureIPsCmd())
