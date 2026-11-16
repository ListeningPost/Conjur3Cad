"""Agent-facing tools for the conjur3-models plugin.

Tools
-----
* ``search_3d_models(query, sources?, limit?)`` — pure function. Returns a
  JSON-stringified list of Candidate dicts. Useful for the agent to preview /
  filter / reason about results before deciding whether to put up the picker.

* ``pick_3d_model(question, candidates)`` — interactive. Pushes a carousel
  modal to the user's WebUI, blocks until they pick or cancel, returns the
  chosen Candidate (with ``download_url`` resolved if the source supports
  anonymous download).

Handler signature: ``handle_X(args: dict, **kw) -> str`` returning a JSON
string. The ``**kw`` carries ``session_id`` (when wired) so the picker can
target the right WebUI client.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from . import picker, sources

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Runtime gate
# ---------------------------------------------------------------------------

def check_requirements() -> bool:
    """No external requirements — pure HTTP."""
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _err(msg: str, **extra: Any) -> str:
    return _json({"success": False, "error": msg, **extra})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

SEARCH_3D_MODELS_SCHEMA: Dict[str, Any] = {
    "name": "search_3d_models",
    "description": (
        "Search 3D model libraries (Printables, TraceParts) for a query and "
        "return a list of candidates with thumbnails. Use this BEFORE "
        "scraping the open web — the curated sources are reliable and "
        "respect anti-bot defenses. After running this, you typically "
        "follow up with pick_3d_model to let the user choose visually."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for, e.g. 'Raspberry Pi 4 case' or 'M10 hex bolt'.",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string", "enum": ["printables", "traceparts"]},
                "description": (
                    "Subset of sources to query. Defaults to all of: "
                    "printables (STL, 3D-printing), traceparts (STEP, engineering CAD)."
                ),
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 12,
                "description": "Maximum results per source. Default 6.",
            },
        },
        "required": ["query"],
    },
}

PICK_3D_MODEL_SCHEMA: Dict[str, Any] = {
    "name": "pick_3d_model",
    "description": (
        "Present a carousel of 3D model candidates to the user and wait for "
        "them to pick one. The carousel appears inline in the chat and "
        "shows thumbnails — the user clicks through with arrows and picks "
        "with 'Use this model' or cancels. Returns the picked Candidate "
        "with download_url resolved if anonymous download is supported, "
        "or {success: false, cancelled: true} on cancel/timeout. "
        "After a successful pick with a download_url, you should download "
        "the file to ~/workspace/ and call import_3d_file on it. If "
        "download_url is null, surface the page_url to the user and ask "
        "them to download manually (e.g. TraceParts requires a free account)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Short prompt to display above the carousel, e.g. 'Which one do you want to import?'.",
            },
            "candidates": {
                "type": "array",
                "minItems": 1,
                "maxItems": 24,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "source": {"type": "string"},
                        "thumbnail_url": {"type": "string"},
                        "page_url": {"type": "string"},
                        "download_url": {"type": ["string", "null"]},
                        "metadata": {"type": "object"},
                    },
                    "required": ["id", "name", "source", "thumbnail_url"],
                },
                "description": "List of Candidate dicts from search_3d_models. Pass the result through verbatim.",
            },
        },
        "required": ["question", "candidates"],
    },
}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def handle_search_3d_models(args: Dict[str, Any], **_kw: Any) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return _err("query is required")
    src_list: Optional[List[str]] = args.get("sources") or None
    limit = int(args.get("limit") or 6)
    try:
        candidates = sources.search_all(query, sources=src_list, per_source_limit=limit)
    except Exception as exc:
        logger.exception("search_3d_models failed")
        return _err(f"search failed: {exc}")
    return _json({"success": True, "count": len(candidates), "candidates": candidates})


def handle_pick_3d_model(args: Dict[str, Any], **kw: Any) -> str:
    question = (args.get("question") or "").strip()
    candidates = args.get("candidates") or []
    if not question:
        return _err("question is required")
    if not isinstance(candidates, list) or not candidates:
        return _err("candidates must be a non-empty list")

    session_id = kw.get("session_id") or ""
    if not session_id:
        return _err(
            "pick_3d_model needs a session_id to target the user's WebUI; "
            "this looks like a non-WebUI execution context"
        )

    try:
        chosen = picker.open_picker_blocking(session_id, question, candidates, timeout=60)
    except picker.PickerCancelled:
        return _json({"success": False, "cancelled": True, "reason": "user cancelled"})
    except picker.PickerTimeout:
        return _json({"success": False, "cancelled": True, "reason": "timeout"})
    except Exception as exc:
        logger.exception("pick_3d_model failed")
        return _err(f"picker failed: {exc}")

    # Resolve download URL on demand for sources that support it.
    if chosen.get("download_url") is None:
        resolved = sources.resolve_download(chosen.get("id") or "")
        if resolved:
            chosen = {**chosen, "download_url": resolved}

    return _json({"success": True, "picked": chosen})
