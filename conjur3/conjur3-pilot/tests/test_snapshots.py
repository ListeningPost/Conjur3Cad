"""Unit tests for the SnapshotStore."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# The snapshots module is FreeCAD-independent — no stubbing needed. The addon
# isn't a real Python package (FreeCAD adds it to sys.path at runtime), so we
# point at the rpc_server directory and import the module directly.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "addon" / "conjur3_pilot" / "rpc_server"),
)

from snapshots import SnapshotStore, _safe_label  # noqa: E402


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    """A pretend FCStd document file. SnapshotStore copies it byte-for-byte."""
    p = tmp_path / "part.FCStd"
    p.write_bytes(b"version-0")
    return p


def _set_doc(p: Path, content: bytes) -> None:
    p.write_bytes(content)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def test_layout_paths_match_user_spec(tmp_path: Path) -> None:
    """`part.FCStd` lives in the parent; snapshots/ring/part.N.FCStd nest."""
    store = SnapshotStore(tmp_path / "part.FCStd")
    assert store.snapshots_dir == tmp_path / "part.snapshots"
    assert store.ring_dir == tmp_path / "part.snapshots" / "ring"
    assert store.milestones_dir == tmp_path / "part.snapshots" / "milestones"
    # Ring snapshot N is named part.N.FCStd
    assert store._ring_snapshot_path(1).name == "part.1.FCStd"
    assert store._ring_snapshot_path(143).name == "part.143.FCStd"


# ---------------------------------------------------------------------------
# Action snapshots — the ring buffer
# ---------------------------------------------------------------------------


def test_first_snapshot_is_n_equals_one(doc: Path) -> None:
    store = SnapshotStore(doc)
    entry = store.snapshot_action("create_body", {"name": "Body"})
    assert entry is not None
    assert entry["n"] == 1
    assert (doc.parent / "part.snapshots" / "ring" / "part.1.FCStd").exists()


def test_counter_increments_monotonically(doc: Path) -> None:
    store = SnapshotStore(doc)
    for i in range(1, 6):
        e = store.snapshot_action(f"op_{i}", {})
        assert e["n"] == i
    listed = store.list_all()["ring"]
    assert [e["n"] for e in listed] == [5, 4, 3, 2, 1]  # newest-first


def test_unsaved_doc_skips_snapshot(tmp_path: Path) -> None:
    """If the live doc file does not exist, snapshot returns None silently."""
    store = SnapshotStore(tmp_path / "never-saved.FCStd")
    assert store.snapshot_action("pad", {}) is None


def test_snapshot_captures_byte_content_at_action_time(doc: Path) -> None:
    """The snapshot is a frozen copy of the live doc as it was *before* the action."""
    store = SnapshotStore(doc)
    _set_doc(doc, b"state-before-pad")
    store.snapshot_action("pad", {"length": 10})
    _set_doc(doc, b"state-after-pad")  # the live doc evolved
    snap = store.path_for(n=1).read_bytes()
    assert snap == b"state-before-pad"


# ---------------------------------------------------------------------------
# Ring eviction
# ---------------------------------------------------------------------------


def test_ring_evicts_oldest_when_over_capacity(doc: Path) -> None:
    store = SnapshotStore(doc, ring_size=3)
    for i in range(1, 6):  # 5 actions
        _set_doc(doc, f"v{i}".encode())
        store.snapshot_action(f"op_{i}", {})
    listed = store.list_all()["ring"]
    # Only the last 3 survive; counter values still monotonic
    assert [e["n"] for e in listed] == [5, 4, 3]
    # Evicted snapshots are removed from disk
    assert not (doc.parent / "part.snapshots" / "ring" / "part.1.FCStd").exists()
    assert not (doc.parent / "part.snapshots" / "ring" / "part.2.FCStd").exists()
    assert (doc.parent / "part.snapshots" / "ring" / "part.5.FCStd").exists()


def test_counter_continues_past_eviction(doc: Path) -> None:
    """After ring fills and evicts, N keeps incrementing — no reuse."""
    store = SnapshotStore(doc, ring_size=2)
    for _ in range(5):
        store.snapshot_action("op", {})
    listed = store.list_all()["ring"]
    assert [e["n"] for e in listed] == [5, 4]


def test_ring_size_must_be_positive(doc: Path) -> None:
    with pytest.raises(ValueError):
        SnapshotStore(doc, ring_size=0)


# ---------------------------------------------------------------------------
# Named milestones
# ---------------------------------------------------------------------------


def test_milestone_is_unbounded_and_overwrites_by_label(doc: Path) -> None:
    store = SnapshotStore(doc, ring_size=1)
    for i in range(1, 11):
        _set_doc(doc, f"v{i}".encode())
        store.snapshot_milestone(f"checkpoint-{i}")
    listed = store.list_all()["milestones"]
    assert len(listed) == 10  # ring_size doesn't apply

    # Overwrite semantics — same label updates the entry, doesn't duplicate
    _set_doc(doc, b"updated")
    store.snapshot_milestone("checkpoint-5")
    listed = store.list_all()["milestones"]
    labels = [e["label"] for e in listed]
    assert labels.count("checkpoint-5") == 1
    assert store.path_for(milestone="checkpoint-5").read_bytes() == b"updated"


def test_milestone_label_is_sanitized(doc: Path) -> None:
    store = SnapshotStore(doc)
    store.snapshot_milestone("my gear / v1.0!!")
    p = store.path_for(milestone="my gear / v1.0!!")
    assert p.exists()
    assert "/" not in p.name and " " not in p.name


def test_safe_label_collapses_unsafe_chars() -> None:
    assert _safe_label("foo bar") == "foo-bar"
    assert _safe_label("../etc/passwd") == "etc-passwd"
    assert _safe_label("---") == "milestone"
    assert _safe_label("x" * 200).startswith("x")
    assert len(_safe_label("x" * 200)) <= 64


def test_delete_milestone(doc: Path) -> None:
    store = SnapshotStore(doc)
    store.snapshot_milestone("keepme")
    store.snapshot_milestone("dropme")
    assert store.delete_milestone("dropme") is True
    assert store.delete_milestone("dropme") is False  # already gone
    listed = [e["label"] for e in store.list_all()["milestones"]]
    assert listed == ["keepme"]


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_path_for_resolves_ring_and_milestone(doc: Path) -> None:
    store = SnapshotStore(doc)
    store.snapshot_action("first", {})
    store.snapshot_milestone("baseline")
    assert store.path_for(n=1).name == "part.1.FCStd"
    assert store.path_for(milestone="baseline").name == "baseline.FCStd"


def test_path_for_raises_on_missing(doc: Path) -> None:
    store = SnapshotStore(doc)
    with pytest.raises(FileNotFoundError):
        store.path_for(n=99)
    with pytest.raises(FileNotFoundError):
        store.path_for(milestone="nope")


def test_path_for_requires_exactly_one_arg(doc: Path) -> None:
    store = SnapshotStore(doc)
    with pytest.raises(ValueError):
        store.path_for()
    with pytest.raises(ValueError):
        store.path_for(n=1, milestone="foo")


# ---------------------------------------------------------------------------
# Manifest format
# ---------------------------------------------------------------------------


def test_manifest_records_action_params_and_hash(doc: Path) -> None:
    store = SnapshotStore(doc)
    store.snapshot_action("pad_sketch", {"length": 12.5, "midplane": True})
    manifest = json.loads(
        (doc.parent / "part.snapshots" / "ring" / "manifest.json").read_text()
    )
    assert len(manifest) == 1
    e = manifest[0]
    assert e["action"] == "pad_sketch"
    assert e["params"] == {"length": 12.5, "midplane": True}
    assert e["sha256"] and len(e["sha256"]) == 64
    assert e["size"] > 0
    assert e["timestamp"] > 0


def test_manifest_survives_corruption(doc: Path) -> None:
    """A corrupt manifest.json should not crash subsequent snapshots."""
    store = SnapshotStore(doc)
    store.snapshot_action("a", {})
    (doc.parent / "part.snapshots" / "ring" / "manifest.json").write_text("not json {")
    # Should still work (manifest treated as empty, next N restarts at 1)
    e = store.snapshot_action("b", {})
    assert e is not None
    assert e["n"] == 1
