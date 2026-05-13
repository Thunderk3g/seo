"""Recursively harvest URLs from sitemap.xml / sitemap-index / .xml.gz."""
from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET

import requests

from ..conf import settings
from ..logger import get_logger

log = get_logger(__name__)
_NS = {
    "s": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "xhtml": "http://www.w3.org/1999/xhtml",
}


def _decode(r: requests.Response, url: str) -> str | None:
    raw = r.content
    if url.lower().endswith(".gz") or raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            return None
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None


def harvest(url: str, session: requests.Session, depth: int = 0,
            _seen: set[str] | None = None) -> list[str]:
    if depth > settings.sitemap_max_depth:
        return []
    seen = _seen if _seen is not None else set()
    if url in seen:
        return []
    seen.add(url)
    out: list[str] = []
    try:
        r = session.get(url, timeout=settings.request_timeout)
        if r.status_code != 200:
            return []
        text = _decode(r, url)
        if not text:
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
        tag = root.tag.split("}")[-1]
        if tag == "sitemapindex":
            for sm in root.findall("s:sitemap/s:loc", _NS):
                if sm.text:
                    out.extend(harvest(sm.text.strip(), session, depth + 1, seen))
        elif tag == "urlset":
            for u in root.findall("s:url", _NS):
                loc = u.find("s:loc", _NS)
                if loc is not None and loc.text:
                    out.append(loc.text.strip())
                # hreflang alternates (e.g. /hi/ pages)
                for alt in u.findall("xhtml:link", _NS):
                    href = alt.get("href")
                    if href:
                        out.append(href.strip())
    except Exception as exc:  # noqa: BLE001
        log.warning("sitemap %s: %s", url, exc)
    return out
