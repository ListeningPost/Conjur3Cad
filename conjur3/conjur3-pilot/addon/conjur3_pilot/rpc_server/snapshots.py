"""Hybrid checkpoint store — feature-tree snapshots beside the live document.

A feature-tree checkpoint store with serialized snapshots and atomic
restoration on validation failure. The store is invoked
from `_with_undo`: a snapshot is taken before each mutation; on success the
live document is saved over `part.FCStd`; on validation failure the kernel
state is rolled back via `abortTransaction` and the most recent ring snapshot
remains available for explicit `restore_snapshot`.

Layout for a document at `/work/part.FCStd`:

    /work/
      part.FCStd                          ← live state (always current)
      part.snapshots/
        ring/
          part.142.FCStd                  ← oldest in ring
          part.143.FCStd
          ...
          part.171.FCStd                  ← newest in ring
          manifest.json                   ← [{n, action, params, ts, sha256, size}]
        milestones/
          gear-baseline.FCStd             ← named milestones, unbounded
          pre-shell-test.FCStd
          manifest.json

Counter semantics: the action counter increments monotonically forever (N is
unique within a doc's lifetime). The on-disk ring is capped at `ring_size`
(default 30); the oldest entry is evicted when the cap is exceeded. This keeps
"snapshot N is newer than snapshot M iff N > M" trivially true, which is what
restore tooling and humans want.

Module is FreeCAD-independent — it operates on file paths only — so the
SnapshotStore can be unit-tested without the FreeCAD interpreter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any


_SAFE_LABEL = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_label(label: str) -> str:
    """Sanitize a milestone label so it's a valid filename component."""
    cleaned = _SAFE_LABEL.sub("-", label.strip())
    cleaned = cleaned.strip("-.") or "milestone"
    return cleaned[:64]


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class SnapshotStore:
    """Per-document hybrid checkpoint store (auto-ring + named milestones).

    Construct one per FreeCAD document path. Methods mutate the on-disk
    `part.snapshots/` tree but never touch the live document — the caller
    decides when to save the live doc.
    """

    def __init__(self, doc_path: str | os.PathLike, *, ring_size: int = 30) -> None:
        if ring_size < 1:
            raise ValueError("ring_size must be >= 1")
        self.doc_path = Path(doc_path)
        self.ring_size = ring_size
        base = self.doc_path.with_suffix("")
        self.snapshots_dir = base.parent / f"{base.name}.snapshots"
        self.ring_dir = self.snapshots_dir / "ring"
        self.milestones_dir = self.snapshots_dir / "milestones"

    # ------------------------------------------------------------------ paths

    def _ring_manifest_path(self) -> Path:
        return self.ring_dir / "manifest.json"

    def _milestones_manifest_path(self) -> Path:
        return self.milestones_dir / "manifest.json"

    def _ring_snapshot_path(self, n: int) -> Path:
        stem = self.doc_path.stem
        return self.ring_dir / f"{stem}.{n}{self.doc_path.suffix}"

    def _milestone_path(self, label: str) -> Path:
        return self.milestones_dir / f"{_safe_label(label)}{self.doc_path.suffix}"

    # ----------------------------------------------------------- manifest io

    def _read_manifest(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            with path.open("r") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _write_manifest(self, path: Path, entries: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp, path)

    # --------------------------------------------------------- next counter

    def _next_n(self) -> int:
        """Monotonically-increasing action counter — survives ring eviction."""
        entries = self._read_manifest(self._ring_manifest_path())
        if not entries:
            return 1
        return max(int(e.get("n", 0)) for e in entries) + 1

    # ----------------------------------------------------------- core ops

    def snapshot_action(
        self,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Copy the live doc into the ring as the next sequential snapshot.

        Returns a manifest entry, or None if the live doc doesn't exist yet
        (e.g. unsaved document — caller should `save_document` with a path
        first to enable snapshotting).
        """
        if not self.doc_path.exists():
            return None
        n = self._next_n()
        target = self._ring_snapshot_path(n)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.doc_path, target)
        entry = {
            "n": n,
            "action": action,
            "params": params or {},
            "timestamp": time.time(),
            "size": target.stat().st_size,
            "sha256": _sha256_of(target),
        }
        manifest = self._read_manifest(self._ring_manifest_path())
        manifest.append(entry)
        self._evict_to_cap(manifest)
        self._write_manifest(self._ring_manifest_path(), manifest)
        return entry

    def _evict_to_cap(self, manifest: list[dict[str, Any]]) -> None:
        """Drop oldest ring entries (and their files) until len <= ring_size."""
        while len(manifest) > self.ring_size:
            oldest = manifest.pop(0)
            try:
                self._ring_snapshot_path(int(oldest["n"])).unlink(missing_ok=True)
            except OSError:
                pass

    def snapshot_milestone(
        self,
        label: str,
        action: str = "manual",
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Save a named, never-evicted snapshot. Overwrites if `label` exists."""
        if not self.doc_path.exists():
            return None
        target = self._milestone_path(label)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.doc_path, target)
        entry = {
            "label": _safe_label(label),
            "action": action,
            "params": params or {},
            "timestamp": time.time(),
            "size": target.stat().st_size,
            "sha256": _sha256_of(target),
        }
        manifest = self._read_manifest(self._milestones_manifest_path())
        # de-dupe by label (overwrite semantics)
        manifest = [e for e in manifest if e.get("label") != entry["label"]]
        manifest.append(entry)
        self._write_manifest(self._milestones_manifest_path(), manifest)
        return entry

    def list_all(self) -> dict[str, list[dict[str, Any]]]:
        """Return {'ring': [...], 'milestones': [...]} sorted newest-first."""
        ring = sorted(
            self._read_manifest(self._ring_manifest_path()),
            key=lambda e: int(e.get("n", 0)),
            reverse=True,
        )
        milestones = sorted(
            self._read_manifest(self._milestones_manifest_path()),
            key=lambda e: float(e.get("timestamp", 0)),
            reverse=True,
        )
        return {"ring": ring, "milestones": milestones}

    def path_for(self, *, n: int | None = None, milestone: str | None = None) -> Path:
        """Resolve an existing snapshot to its file path. Raises if not found."""
        if (n is None) == (milestone is None):
            raise ValueError("specify exactly one of n= or milestone=")
        if n is not None:
            p = self._ring_snapshot_path(int(n))
            if not p.exists():
                raise FileNotFoundError(f"ring snapshot {n} not found at {p}")
            return p
        p = self._milestone_path(milestone)  # type: ignore[arg-type]
        if not p.exists():
            raise FileNotFoundError(f"milestone {milestone!r} not found at {p}")
        return p

    def delete_milestone(self, label: str) -> bool:
        """Remove a named milestone. Returns True if anything was removed."""
        path = self._milestone_path(label)
        existed = path.exists()
        path.unlink(missing_ok=True)
        manifest = self._read_manifest(self._milestones_manifest_path())
        clean = [e for e in manifest if e.get("label") != _safe_label(label)]
        if len(clean) != len(manifest):
            self._write_manifest(self._milestones_manifest_path(), clean)
            existed = True
        return existed
