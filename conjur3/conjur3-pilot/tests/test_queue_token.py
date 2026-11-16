"""Smoke-test for the per-call response token pattern used in `_run_on_gui`.

Reproduces the original bug that motivated the fix: caller A submits a slow
task and times out; task A eventually completes; caller B — which submits a
*different* task — used to read A's late result instead of its own.  With the
per-call response queue + abandoned-token set, B must see B's result only.

This reimplements the production pattern locally so the test doesn't require
FreeCAD to be importable.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid


def _start_gui_thread(request_q: queue.Queue, abandoned: set, lock: threading.Lock):
    """Drain the request queue and run tasks, honoring the abandoned-token set."""
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                item = request_q.get(timeout=0.05)
            except queue.Empty:
                continue
            token, resp_q, task, delay = item
            time.sleep(delay)
            try:
                res = task()
            except Exception as e:  # pragma: no cover - defensive
                res = f"err {e}"
            with lock:
                if token in abandoned:
                    abandoned.discard(token)
                    continue
            try:
                resp_q.put_nowait(res)
            except queue.Full:
                pass

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return stop, t


def _submit(request_q, abandoned, lock, task, delay, timeout):
    token = uuid.uuid4().hex
    resp_q: queue.Queue = queue.Queue(maxsize=1)
    request_q.put((token, resp_q, task, delay))
    try:
        return resp_q.get(timeout=timeout)
    except queue.Empty:
        with lock:
            abandoned.add(token)
        return "TIMEOUT"


def test_late_result_after_timeout_does_not_leak_into_next_call():
    request_q: queue.Queue = queue.Queue()
    abandoned: set = set()
    lock = threading.Lock()
    stop, _t = _start_gui_thread(request_q, abandoned, lock)
    try:
        # Caller A: slow task (0.5 s), short timeout (0.1 s) → times out.
        result_a = _submit(request_q, abandoned, lock,
                           lambda: "A_RESULT", delay=0.5, timeout=0.1)
        assert result_a == "TIMEOUT", f"A should have timed out, got {result_a!r}"

        # Let A's late result flow through the GUI thread and be discarded.
        time.sleep(0.7)

        # Caller B: fast task, enough timeout — must see B's own result,
        # not A's (the original leaky-queue bug).
        result_b = _submit(request_q, abandoned, lock,
                           lambda: "B_RESULT", delay=0.0, timeout=1.0)
        assert result_b == "B_RESULT", (
            f"B must see its own result — got {result_b!r}. "
            "Regression of the stale-response bug from the cabinet build session."
        )
    finally:
        stop.set()


def test_successful_call_returns_its_own_result():
    """Sanity check: the happy path still works."""
    request_q: queue.Queue = queue.Queue()
    abandoned: set = set()
    lock = threading.Lock()
    stop, _t = _start_gui_thread(request_q, abandoned, lock)
    try:
        r = _submit(request_q, abandoned, lock, lambda: 42, delay=0.0, timeout=1.0)
        assert r == 42
    finally:
        stop.set()


def test_two_concurrent_callers_do_not_swap_results():
    """Two callers submit different tasks; each must see its own."""
    request_q: queue.Queue = queue.Queue()
    abandoned: set = set()
    lock = threading.Lock()
    stop, _t = _start_gui_thread(request_q, abandoned, lock)
    try:
        results: dict = {}

        def caller(name, payload, delay):
            results[name] = _submit(request_q, abandoned, lock,
                                    lambda p=payload: p, delay=delay, timeout=2.0)

        ta = threading.Thread(target=caller, args=("A", "A_VAL", 0.10), daemon=True)
        tb = threading.Thread(target=caller, args=("B", "B_VAL", 0.05), daemon=True)
        ta.start(); tb.start()
        ta.join(2.0); tb.join(2.0)

        assert results.get("A") == "A_VAL", results
        assert results.get("B") == "B_VAL", results
    finally:
        stop.set()
