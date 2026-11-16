"""Printables source adapter.

Uses the public GraphQL endpoint at https://api.printables.com/graphql/ —
anonymously accessible, no auth required. Two operations matter:

  * ``searchPrints2(query, limit, offset)`` — top-level model search
  * ``getDownloadLink(id, printId, fileType, source)`` — one-shot mutation
    that returns a signed media URL for an STL/STEP file id

Search returns Print summaries; we surface those as candidates with a
non-null download_url only after the user has picked one (via
``resolve_download``). The thumbnail_url comes straight off the Print
object and uses Printables' public media CDN.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import List

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.printables.com/graphql/"
MEDIA_CDN = "https://media.printables.com/"
WEB_BASE = "https://www.printables.com/"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
TIMEOUT = 8

_SEARCH_QUERY = """
query Search($q: String!, $limit: Int) {
  searchPrints2(query: $q, limit: $limit) {
    items {
      id
      slug
      name
      image { filePath }
      user { publicUsername }
      datePublished
      likesCount
      downloadCount
      printDuration
    }
  }
}
""".strip()

_DOWNLOAD_MUTATION = """
mutation Dl($id: ID!, $printId: ID!, $fileType: DownloadFileTypeEnum!, $source: DownloadSourceEnum!) {
  getDownloadLink(id: $id, printId: $printId, fileType: $fileType, source: $source) {
    ok
    output { link }
  }
}
""".strip()


def _post(payload: dict) -> dict:
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search(query: str, limit: int = 8) -> List[dict]:
    """Search Printables for models matching *query*.

    Returns Candidate dicts with ``download_url = None``; call
    :func:`resolve_download` after the user picks to fetch the signed STL URL.
    """
    if not query or not query.strip():
        return []
    payload = {"query": _SEARCH_QUERY, "variables": {"q": query, "limit": max(1, min(limit, 24))}}
    data = _post(payload)
    items = ((data or {}).get("data") or {}).get("searchPrints2", {}).get("items") or []
    candidates: List[dict] = []
    for item in items:
        pid = str(item.get("id") or "")
        if not pid:
            continue
        slug = item.get("slug") or ""
        image_path = (item.get("image") or {}).get("filePath") or ""
        thumb = (MEDIA_CDN + image_path) if image_path else ""
        user = (item.get("user") or {}).get("publicUsername") or ""
        candidates.append({
            "id": f"printables:{pid}",
            "name": item.get("name") or f"Printables #{pid}",
            "source": "printables",
            "thumbnail_url": thumb,
            "page_url": f"{WEB_BASE}model/{pid}-{slug}" if slug else f"{WEB_BASE}model/{pid}",
            # Resolved lazily after pick — Printables' download mutation is
            # cheap but one-shot, so we don't waste it on every search result.
            "download_url": None,
            "metadata": {
                "author": user,
                "format": "stl",
                "likes": item.get("likesCount"),
                "downloads": item.get("downloadCount"),
            },
        })
    return candidates


def resolve_download(print_id: str) -> str | None:
    """Resolve the first STL download URL for a given print id.

    Fetches the print's STL list, picks the first one, calls
    ``getDownloadLink`` to mint a signed URL. Falls back to STEP if no
    STLs are listed.
    """
    if not print_id:
        return None
    detail_q = (
        "query Detail($id: ID!) { print(id: $id) { id stls { id name } } }"
    )
    detail = _post({"query": detail_q, "variables": {"id": print_id}})
    p = ((detail or {}).get("data") or {}).get("print") or {}
    stls = p.get("stls") or []
    if not stls:
        return None
    # Prefer .stl, then .step
    pref = next((s for s in stls if str(s.get("name", "")).lower().endswith(".stl")), None) \
        or next((s for s in stls if str(s.get("name", "")).lower().endswith(".step")), None) \
        or stls[0]
    stl_id = str(pref.get("id") or "")
    if not stl_id:
        return None
    name_lower = str(pref.get("name", "")).lower()
    if name_lower.endswith(".step") or name_lower.endswith(".stp"):
        file_type = "step"
    else:
        file_type = "stl"
    link = _post({
        "query": _DOWNLOAD_MUTATION,
        "variables": {
            "id": stl_id,
            "printId": str(print_id),
            "fileType": file_type,
            "source": "model_detail",
        },
    })
    payload = ((link or {}).get("data") or {}).get("getDownloadLink") or {}
    if not payload.get("ok"):
        return None
    return ((payload.get("output") or {}).get("link")) or None
