"""Picker bridge.

Defers to ``api.model_picker`` (a WebUI-side module created by the SSE wiring
patch) for the actual pending-queue + SSE-emit + response logic. Kept here as
a thin shim so the plugin doesn't import api/* at module top-level — that
would create a load-order problem (the plugin is discovered before api/* is
imported).
"""
from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


class PickerCancelled(Exception):
    """User dismissed the picker."""


class PickerTimeout(Exception):
    """Picker expired before the user responded."""


def open_picker_blocking(session_id: str, question: str, candidates: List[dict], timeout: float = 60.0) -> dict:
    """Push a model_picker event to the given session's WebUI, block, return the picked Candidate.

    Raises :class:`PickerCancelled` if the user explicitly cancels and
    :class:`PickerTimeout` if no response arrives within *timeout* seconds.

    Translates exceptions raised by ``api.model_picker`` (which has its own
    canonical ``PickerCancelled`` / ``PickerTimeout`` classes) into the
    plugin-local ones, so ``tools.py`` only ever needs to catch the
    plugin-local exceptions.
    """
    try:
        from api import model_picker as _impl
    except Exception as exc:  # pragma: no cover — defensive
        raise RuntimeError(
            "api.model_picker is not available — make sure the WebUI patch is installed"
        ) from exc
    try:
        return _impl.open_picker_blocking(session_id, question, candidates, timeout=timeout)
    except _impl.PickerCancelled as exc:
        raise PickerCancelled() from exc
    except _impl.PickerTimeout as exc:
        raise PickerTimeout() from exc
