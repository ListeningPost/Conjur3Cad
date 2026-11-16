"""Model-picker pending-queue + SSE bridge.

Mirrors api/clarify.py — same pending-queue / threading / SSE-subscriber
structure, but the response payload is a picked Candidate dict (or
"cancelled" / "timeout") instead of a free-form clarification string.

The plugin ``conjur3-models`` calls :func:`open_picker_blocking` from its
``pick_3d_model`` tool handler. We submit the pending entry and block on
its event; ``/api/model_picker/respond`` fires the event with the result.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT_SECONDS = 60


class PickerCancelled(Exception):
    """User dismissed the picker."""


class PickerTimeout(Exception):
    """Picker expired before the user responded."""


_lock = threading.Lock()
_pending: dict[str, dict] = {}
_queues: dict[str, list] = {}
_notify_cbs: dict[str, Callable[[dict], None]] = {}
_sse_subscribers: dict[str, list[queue.Queue]] = {}


class _Entry:
    __slots__ = ("event", "data", "result")

    def __init__(self, data: dict):
        self.event = threading.Event()
        self.data = data
        self.result: Optional[dict] = None  # {"picked": Candidate} | {"cancelled": True}


# ---------------------------------------------------------------------------
# Per-session notify callback (streaming.py registers this)
# ---------------------------------------------------------------------------

def register_gateway_notify(session_key: str, cb: Callable[[dict], None]) -> None:
    with _lock:
        _notify_cbs[session_key] = cb


def unregister_gateway_notify(session_key: str) -> None:
    with _lock:
        _notify_cbs.pop(session_key, None)
        entries = _clear_queue_locked(session_key)
    for entry in entries:
        entry.event.set()


def _clear_queue_locked(session_key: str) -> list:
    entries = _queues.pop(session_key, [])
    _pending.pop(session_key, None)
    return entries


def clear_pending(session_key: str) -> int:
    with _lock:
        entries = _clear_queue_locked(session_key)
    for entry in entries:
        entry.event.set()
    return len(entries)


# ---------------------------------------------------------------------------
# SSE subscriber registry
# ---------------------------------------------------------------------------

def sse_subscribe(session_id: str) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=16)
    with _lock:
        _sse_subscribers.setdefault(session_id, []).append(q)
    return q


def sse_unsubscribe(session_id: str, q: queue.Queue) -> None:
    with _lock:
        subs = _sse_subscribers.get(session_id)
        if subs:
            try:
                subs.remove(q)
            except ValueError:
                pass
            if not subs:
                _sse_subscribers.pop(session_id, None)


def _sse_notify(session_id: str, head: Optional[dict], total: int) -> None:
    payload = {"pending": dict(head) if head else None, "pending_count": total}
    for q in _sse_subscribers.get(session_id, ()):
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass


# ---------------------------------------------------------------------------
# Submit / resolve
# ---------------------------------------------------------------------------

def _with_timeout_metadata(data: dict) -> dict:
    item = dict(data or {})
    requested_at = float(item.get("requested_at") or time.time())
    timeout_seconds = int(item.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    expires_at = float(item.get("expires_at") or (requested_at + timeout_seconds))
    item["requested_at"] = requested_at
    item["timeout_seconds"] = timeout_seconds
    item["expires_at"] = expires_at
    return item


def submit_pending(session_key: str, data: dict) -> _Entry:
    data = _with_timeout_metadata(data)
    with _lock:
        gw_queue = _queues.setdefault(session_key, [])
        entry = _Entry(data)
        gw_queue.append(entry)
        _pending[session_key] = gw_queue[0].data
        cb = _notify_cbs.get(session_key)
        _sse_notify(session_key, dict(gw_queue[0].data), len(gw_queue))
    if cb:
        try:
            cb(data)
        except Exception:  # pragma: no cover — defensive
            logger.exception("model_picker notify_cb raised")
    return entry


def get_pending(session_key: str) -> Optional[dict]:
    with _lock:
        q = _queues.get(session_key) or []
        if q:
            return dict(q[0].data)
        p = _pending.get(session_key)
        return dict(p) if p else None


def has_pending(session_key: str) -> bool:
    with _lock:
        return bool(_queues.get(session_key))


def resolve_pick(session_key: str, result: dict) -> int:
    """Resolve the oldest pending picker for *session_key*.

    *result* is the dict that ``open_picker_blocking`` will return —
    either ``{"picked": <candidate>}`` or ``{"cancelled": True, ...}``.
    """
    with _lock:
        q = _queues.get(session_key)
        if not q:
            _pending.pop(session_key, None)
            return 0
        entry = q.pop(0)
        if q:
            _pending[session_key] = q[0].data
            _sse_notify(session_key, dict(q[0].data), len(q))
        else:
            _clear_queue_locked(session_key)
            _sse_notify(session_key, None, 0)
    entry.result = result
    entry.event.set()
    return 1


# ---------------------------------------------------------------------------
# Plugin-facing blocking API
# ---------------------------------------------------------------------------

def open_picker_blocking(
    session_id: str,
    question: str,
    candidates: List[dict],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Push a picker event, block until response, return the picked Candidate.

    Returns the chosen Candidate dict. Raises:
      * ``PickerCancelled``  — user dismissed the picker
      * ``PickerTimeout``    — no response within *timeout* seconds
    """
    data = {
        "question": str(question or ""),
        "candidates": list(candidates or []),
        "session_id": session_id,
        "kind": "model_picker",
        "requested_at": time.time(),
        "timeout_seconds": int(timeout),
    }
    entry = submit_pending(session_id, data)
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            clear_pending(session_id)
            raise PickerTimeout()
        if entry.event.wait(timeout=min(1.0, remaining)):
            res = entry.result or {}
            if res.get("cancelled"):
                raise PickerCancelled()
            picked = res.get("picked")
            if not picked:
                raise PickerCancelled()
            return picked
