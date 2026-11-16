"""Unit tests for the response envelope helpers in `rpc_server.py`.

These cover the multimodal response payload and the post-execution
validation with atomic rollback:

- `_measure(obj)`       — extracts {volume, bbox, face/edge/vertex counts, validity}
- `_ok(obj=...)`        — auto-attaches measurements to success payloads
- `_err(ValidationError)` — produces structured corrective-reprompt envelope
- `_with_undo(...)`     — aborts transaction on post-exec validity failure

The rpc_server module imports FreeCAD/PySide at top level — those are stubbed
here so the test runs outside of FreeCAD's bundled interpreter.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _install_freecad_stubs() -> None:
    """Provide enough fake FreeCAD/PySide for `rpc_server.py` to import cleanly."""
    if "FreeCAD" in sys.modules:
        return

    freecad = types.ModuleType("FreeCAD")
    freecad.ActiveDocument = None

    class _Console:
        @staticmethod
        def PrintMessage(*a, **kw): pass
        @staticmethod
        def PrintWarning(*a, **kw): pass
        @staticmethod
        def PrintError(*a, **kw): pass
    freecad.Console = _Console
    freecad.getUserAppDataDir = lambda: "/tmp"
    freecad.listDocuments = lambda: {}
    freecad.getDocument = lambda name: None
    freecad.Vector = lambda *a, **kw: None
    freecad.Placement = lambda *a, **kw: None
    freecad.Rotation = lambda *a, **kw: None
    sys.modules["FreeCAD"] = freecad

    freecadgui = types.ModuleType("FreeCADGui")
    freecadgui.activeDocument = lambda: None
    freecadgui.runCommand = lambda *a, **kw: None
    freecadgui.addCommand = lambda *a, **kw: None
    freecadgui.addWorkbench = lambda *a, **kw: None
    sys.modules["FreeCADGui"] = freecadgui

    pyside = types.ModuleType("PySide")
    qtcore = types.ModuleType("PySide.QtCore")
    qtwidgets = types.ModuleType("PySide.QtWidgets")

    class _QObject:
        def __init__(self, *a, **kw): pass
    class _QTimer(_QObject):
        @staticmethod
        def singleShot(*a, **kw): pass

    qtcore.QObject = _QObject
    qtcore.QTimer = _QTimer
    qtcore.Signal = lambda *a, **kw: None
    qtcore.Qt = types.SimpleNamespace(QueuedConnection=0)
    qtwidgets.QApplication = type("QApplication", (), {"instance": staticmethod(lambda: None)})

    pyside.QtCore = qtcore
    pyside.QtWidgets = qtwidgets
    sys.modules["PySide"] = pyside
    sys.modules["PySide.QtCore"] = qtcore
    sys.modules["PySide.QtWidgets"] = qtwidgets


def _load_rpc_server():
    """Import the rpc_server module after stubbing FreeCAD."""
    _install_freecad_stubs()
    if "conjur3_pilot_rpc_server" in sys.modules:
        return sys.modules["conjur3_pilot_rpc_server"]

    addon_root = Path(__file__).resolve().parents[1] / "addon"
    sys.path.insert(0, str(addon_root))

    # Stub the sibling modules that rpc_server imports relatively so that
    # `from .parts_library import ...` and `from .serialize import ...` resolve.
    pkg = types.ModuleType("conjur3_pilot")
    pkg.__path__ = [str(addon_root / "conjur3_pilot")]
    sys.modules["conjur3_pilot"] = pkg

    rpc_pkg = types.ModuleType("conjur3_pilot.rpc_server")
    rpc_pkg.__path__ = [str(addon_root / "conjur3_pilot" / "rpc_server")]
    sys.modules["conjur3_pilot.rpc_server"] = rpc_pkg

    parts_stub = types.ModuleType("conjur3_pilot.rpc_server.parts_library")
    parts_stub.get_parts_list = lambda *a, **kw: []
    parts_stub.insert_part_from_library = lambda *a, **kw: None
    sys.modules["conjur3_pilot.rpc_server.parts_library"] = parts_stub

    serialize_stub = types.ModuleType("conjur3_pilot.rpc_server.serialize")
    serialize_stub.serialize_object = lambda obj: {}
    sys.modules["conjur3_pilot.rpc_server.serialize"] = serialize_stub

    spec = importlib.util.spec_from_file_location(
        "conjur3_pilot.rpc_server.rpc_server",
        addon_root / "conjur3_pilot" / "rpc_server" / "rpc_server.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["conjur3_pilot.rpc_server.rpc_server"] = mod
    sys.modules["conjur3_pilot_rpc_server"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeShape:
    def __init__(self, *, volume=100.0, faces=6, edges=12, verts=8,
                 bbox=(10.0, 20.0, 30.0), valid=True):
        self.Volume = volume
        self.Faces = [object()] * faces
        self.Edges = [object()] * edges
        self.Vertexes = [object()] * verts
        self.BoundBox = types.SimpleNamespace(
            XLength=bbox[0], YLength=bbox[1], ZLength=bbox[2],
        )
        self._valid = valid

    def isValid(self):
        return self._valid


class FakeFeature:
    def __init__(self, name="Pad001", shape=None):
        self.Name = name
        self.Shape = shape


class FakeDoc:
    def __init__(self):
        self.transactions: list[str] = []
        self.aborted: list[str] = []
        self.committed: list[str] = []
        self.recomputed = 0

    def openTransaction(self, label):
        self.transactions.append(label)

    def commitTransaction(self):
        self.committed.append(self.transactions[-1])

    def abortTransaction(self):
        self.aborted.append(self.transactions[-1])

    def recompute(self):
        self.recomputed += 1


# ---------------------------------------------------------------------------
# `_measure`
# ---------------------------------------------------------------------------


def test_measure_extracts_full_block_for_solid():
    rs = _load_rpc_server()
    feat = FakeFeature(shape=FakeShape(volume=42.0, faces=6, edges=12,
                                       verts=8, bbox=(1.0, 2.0, 3.0)))
    m = rs._measure(feat)
    assert m["volume_mm3"] == 42.0
    assert m["bbox_mm"] == {"x": 1.0, "y": 2.0, "z": 3.0}
    assert m["face_count"] == 6
    assert m["edge_count"] == 12
    assert m["vertex_count"] == 8
    assert m["is_valid"] is True


def test_measure_returns_empty_for_shapeless_object():
    """Sketches, datum planes, spreadsheets have no Shape — must not blow up."""
    rs = _load_rpc_server()
    assert rs._measure(FakeFeature(shape=None)) == {}


def test_measure_swallows_partial_failures():
    """A Shape that throws on one attribute should still surface the others."""
    rs = _load_rpc_server()

    class FlakyShape(FakeShape):
        @property
        def Volume(self):  # type: ignore[override]
            raise RuntimeError("OCCT volume calc failed")

        @Volume.setter
        def Volume(self, _):  # absorb FakeShape.__init__ assignment
            pass

    m = rs._measure(FakeFeature(shape=FlakyShape()))
    assert "volume_mm3" not in m
    assert m["face_count"] == 6  # other fields still present


# ---------------------------------------------------------------------------
# `_ok` and `_err`
# ---------------------------------------------------------------------------


def test_ok_with_obj_attaches_name_and_measurements():
    rs = _load_rpc_server()
    feat = FakeFeature(name="Fillet001", shape=FakeShape(volume=99.0))
    out = rs._ok(obj=feat)
    assert out["success"] is True
    assert out["name"] == "Fillet001"
    assert out["measurements"]["volume_mm3"] == 99.0


def test_ok_void_mutation_is_unchanged():
    """`_ok()` with no obj/data is the legacy void-mutation shape."""
    rs = _load_rpc_server()
    assert rs._ok() == {"success": True}


def test_ok_extra_kwargs_merged():
    rs = _load_rpc_server()
    out = rs._ok(geometry_id=7)
    assert out == {"success": True, "geometry_id": 7}


def test_err_plain_exception_is_flat():
    rs = _load_rpc_server()
    out = rs._err(ValueError("nope"))
    assert out == {"success": False, "error": "nope"}


def test_err_validation_error_is_structured():
    """Corrective-reprompt envelope on validation failure."""
    rs = _load_rpc_server()
    feat = FakeFeature(name="BadPad", shape=FakeShape(volume=0.0, valid=False))
    err = rs.ValidationError(
        "invalid_geometry",
        obj=feat,
        suggestion="reduce fillet radius",
        param="radius",
        value=999.0,
    )
    out = rs._err(err)
    assert out["success"] is False
    assert out["failure_type"] == "invalid_geometry"
    assert out["suggestion"] == "reduce fillet radius"
    assert out["details"] == {"param": "radius", "value": 999.0}
    # Measurements come from the still-extant (rolled-back) feature
    assert out["measurements"]["face_count"] == 6


# ---------------------------------------------------------------------------
# `_with_undo` post-execution validation
# ---------------------------------------------------------------------------


def test_with_undo_commits_on_valid_result():
    rs = _load_rpc_server()
    doc = FakeDoc()
    feat = FakeFeature(shape=FakeShape(valid=True))
    result = rs._with_undo(doc, "Pad", lambda d: feat)
    assert result is feat
    assert doc.committed == ["Pad"]
    assert doc.aborted == []
    assert doc.recomputed == 1


def test_with_undo_aborts_on_invalid_geometry():
    """Post-execution failure → atomic rollback."""
    rs = _load_rpc_server()
    doc = FakeDoc()
    bad = FakeFeature(shape=FakeShape(valid=False))
    with pytest.raises(rs.ValidationError) as excinfo:
        rs._with_undo(doc, "BadPad", lambda d: bad)
    assert excinfo.value.failure_type == "invalid_geometry"
    assert excinfo.value.obj is bad
    assert doc.committed == []
    assert doc.aborted == ["BadPad"]


def test_with_undo_propagates_unrelated_exceptions_with_abort():
    rs = _load_rpc_server()
    doc = FakeDoc()

    def explode(_):
        raise RuntimeError("OCCT segfault analog")

    with pytest.raises(RuntimeError):
        rs._with_undo(doc, "Boom", explode)
    assert doc.committed == []
    assert doc.aborted == ["Boom"]


def test_with_undo_skips_validity_check_for_shapeless_result():
    """A sketch-creating mutation returns a Sketch, not a Shape — must commit."""
    rs = _load_rpc_server()
    doc = FakeDoc()
    sk = FakeFeature(shape=None)
    result = rs._with_undo(doc, "Sketch", lambda d: sk)
    assert result is sk
    assert doc.committed == ["Sketch"]


# ---------------------------------------------------------------------------
# `_with_undo` wired to the snapshot store
# ---------------------------------------------------------------------------


def test_with_undo_triggers_snapshot_when_doc_has_filename(tmp_path):
    """Saved docs get a pre-action ring snapshot AND a post-action auto-save."""
    rs = _load_rpc_server()
    live = tmp_path / "part.FCStd"
    live.write_bytes(b"pre-pad-state")

    saves: list[int] = []

    class SavedDoc(FakeDoc):
        Name = "Part"
        FileName = str(live)

        def save(self):
            # Simulate FreeCAD writing the new kernel state to disk.
            live.write_bytes(b"post-pad-state")
            saves.append(1)

    rs._SNAPSHOT_STORES.clear()
    rs._with_undo(SavedDoc(), "Pad", lambda d: FakeFeature(shape=FakeShape(valid=True)))

    # 1. Pre-action snapshot captured the BEFORE state, not the after
    snap = tmp_path / "part.snapshots" / "ring" / "part.1.FCStd"
    assert snap.read_bytes() == b"pre-pad-state"
    # 2. Live file was auto-saved to reflect post-action kernel state
    assert live.read_bytes() == b"post-pad-state"
    assert saves == [1]


def test_with_undo_does_not_snapshot_unsaved_doc(tmp_path):
    """Anonymous in-memory docs (no FileName) must not litter the working dir."""
    rs = _load_rpc_server()

    class UnsavedDoc(FakeDoc):
        Name = "Untitled"
        FileName = ""

        def save(self):  # would raise in real FreeCAD on unsaved doc
            raise AssertionError("save() must not be called on unsaved doc")

    rs._SNAPSHOT_STORES.clear()
    rs._with_undo(UnsavedDoc(), "Pad", lambda d: FakeFeature(shape=FakeShape(valid=True)))
    assert not (tmp_path / "part.snapshots").exists()


def test_with_undo_keeps_snapshot_even_when_validation_aborts(tmp_path):
    """Snapshot is taken pre-action and survives the rollback path."""
    rs = _load_rpc_server()
    live = tmp_path / "part.FCStd"
    live.write_bytes(b"good-state")

    class SavedDoc(FakeDoc):
        Name = "Part"
        FileName = str(live)

        def save(self):
            raise AssertionError("save() must not be called when validation fails")

    rs._SNAPSHOT_STORES.clear()
    bad = FakeFeature(shape=FakeShape(valid=False))
    with pytest.raises(rs.ValidationError):
        rs._with_undo(SavedDoc(), "BadPad", lambda d: bad)

    snap = tmp_path / "part.snapshots" / "ring" / "part.1.FCStd"
    assert snap.exists() and snap.read_bytes() == b"good-state"
