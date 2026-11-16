"""3D model source adapters.

Each adapter exports a ``search(query, limit) -> List[Candidate]`` function
and optionally a ``resolve_download(candidate_id) -> str | None`` to convert
an ``id`` returned by search into a concrete download URL.

A Candidate is a plain dict:

    {
      "id": "<source>:<id>",        # globally unique, source-prefixed
      "name": str,
      "source": str,                # short source label, e.g. "printables"
      "thumbnail_url": str,
      "page_url": str,
      "download_url": str | None,   # None => download requires browser handoff
      "metadata": dict,
    }
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, List

from . import printables as _printables
from . import traceparts as _traceparts

logger = logging.getLogger(__name__)

# name → search-callable mapping
SOURCES: Dict[str, Callable[[str, int], List[dict]]] = {
    "printables": _printables.search,
    "traceparts": _traceparts.search,
}

# name → resolve-download-callable mapping (only sources that support
# anonymous post-pick download resolution need to register this)
RESOLVERS: Dict[str, Callable[[str], str]] = {
    "printables": _printables.resolve_download,
}


def search_all(query: str, sources: List[str] | None = None, per_source_limit: int = 8) -> List[dict]:
    """Run search across the requested sources, interleaving results.

    Returns at most ``per_source_limit * len(sources)`` candidates. Each
    adapter is best-effort — if one fails the others still contribute.
    """
    sources = sources or list(SOURCES.keys())
    results: List[dict] = []
    for name in sources:
        fn = SOURCES.get(name)
        if not fn:
            logger.warning("conjur3-models: unknown source %r, skipping", name)
            continue
        try:
            results.extend(fn(query, per_source_limit))
        except Exception as exc:
            logger.warning("conjur3-models: %s search failed: %s", name, exc)
    return results


def resolve_download(candidate_id: str) -> str | None:
    """Resolve a candidate's download URL on demand.

    For sources that can produce a fresh signed URL only when the user has
    actually picked a candidate (Printables uses a one-shot mutation),
    this is called after pick. Returns ``None`` if the source doesn't
    support anonymous download.
    """
    if not candidate_id or ":" not in candidate_id:
        return None
    source, _, inner = candidate_id.partition(":")
    fn = RESOLVERS.get(source)
    if not fn:
        return None
    try:
        return fn(inner)
    except Exception as exc:
        logger.warning("conjur3-models: %s download resolution failed: %s", source, exc)
        return None
