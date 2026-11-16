"""TraceParts source adapter.

TraceParts has no public REST/GraphQL search API — but the HTML at
``https://www.traceparts.com/en/search?Keywords=...`` is server-rendered
and includes product cards with anchor + thumbnail. Anonymous browsing is
unrestricted; downloading the actual STEP file requires a free account.

This adapter surfaces page_url + thumbnail and leaves ``download_url`` as
``None``. The picker will fall back to the browser-handoff flow.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
import urllib.parse
import urllib.request
from typing import List

logger = logging.getLogger(__name__)

BASE = "https://www.traceparts.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
TIMEOUT = 8

# Matches <a href="/en/product/..."> ... </a> blocks. DOTALL because cards
# span multiple lines.
_LINK_RE = re.compile(
    r'<a[^>]*href="(?P<href>/en/product/[^"]+)"[^>]*>(?P<inner>.*?)</a>',
    re.DOTALL,
)
_IMG_RE = re.compile(
    r'<img[^>]+src="(?P<src>https://cdn-product-content\.traceparts\.com/[^"]+)"[^>]*?(?:\s+alt="(?P<alt>[^"]*)")?',
)


def _get_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def search(query: str, limit: int = 8) -> List[dict]:
    """Search TraceParts for parts matching *query*.

    Returns Candidate dicts. ``download_url`` is always None — picking
    triggers a browser handoff to the product page.
    """
    q = (query or "").strip()
    if not q:
        return []
    url = f"{BASE}/en/search?{urllib.parse.urlencode({'Keywords': q})}"
    try:
        markup = _get_html(url)
    except Exception as exc:
        logger.warning("traceparts: fetch %s failed: %s", url, exc)
        return []

    candidates: List[dict] = []
    seen: set[str] = set()
    for m in _LINK_RE.finditer(markup):
        if len(candidates) >= limit:
            break
        href = m.group("href")
        if href in seen:
            continue
        seen.add(href)
        inner = m.group("inner")
        img_match = _IMG_RE.search(inner)
        if not img_match:
            continue  # No thumbnail → skip; the picker is a visual tool
        thumb = img_match.group("src")
        alt = (img_match.group("alt") or "").strip()

        # Pull part number / product id from the query string. The HTML
        # uses &amp; entities — unescape before parsing so the keys come
        # through clean rather than as "amp;PartNumber".
        qs = urllib.parse.urlparse(html_lib.unescape(href)).query
        params = urllib.parse.parse_qs(qs)
        part_no = params.get("PartNumber", [""])[0]
        product = params.get("Product", [""])[0]
        # Slug → human name. Use alt text if available, else the slug.
        slug = urllib.parse.urlparse(href).path.rsplit("/", 1)[-1]
        slug_name = slug.replace("-", " ").title()
        display_name = alt or slug_name
        if part_no:
            display_name = f"{display_name} — {html_lib.unescape(part_no)}"

        candidates.append({
            "id": f"traceparts:{product or part_no or slug}",
            "name": display_name,
            "source": "traceparts",
            "thumbnail_url": thumb,
            "page_url": BASE + href.replace("&amp;", "&"),
            "download_url": None,  # STEP downloads require TraceParts account
            "metadata": {
                "format": "step",
                "part_number": html_lib.unescape(part_no) if part_no else None,
                "note": "free account required for STEP download",
            },
        })
    return candidates
