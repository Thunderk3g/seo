"""URL canonicalization + filtering helpers."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from ..conf import settings

_SKIP_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".webm",
    ".css", ".js", ".json", ".xml",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
}

_TRACKING_PREFIXES = ("utm_", "gclid", "fbclid", "mc_cid", "mc_eid", "_ga")


def _strip_tracking(query: str) -> str:
    if not query:
        return ""
    kept = [
        (k, v) for k, v in parse_qsl(query, keep_blank_values=True)
        if not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    return urlencode(kept, doseq=True)


def normalize(url: str, base: str | None = None) -> str | None:
    """Canonicalize a URL for dedup. Returns None if it should be ignored."""
    if not url:
        return None
    url = url.strip()
    if url.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    if base:
        url = urljoin(base, url)
    try:
        p = urlparse(url)
    except ValueError:
        return None
    if p.scheme not in ("http", "https"):
        return None
    netloc = p.netloc.lower()
    if netloc.endswith(":80") and p.scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and p.scheme == "https":
        netloc = netloc[:-4]
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunparse((p.scheme.lower(), netloc, path, "", _strip_tracking(p.query), ""))


def is_allowed_domain(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return False
    if not host:
        return False
    allow = set(settings.allowed_domains)
    return host in allow or any(host.endswith("." + d) for d in allow)


def has_skip_extension(url: str) -> bool:
    path = urlparse(url).path.lower()
    _, dot, ext = path.rpartition(".")
    if not dot:
        return False
    return f".{ext}" in _SKIP_EXTENSIONS


def is_trap(url: str) -> bool:
    """Heuristic: reject URLs that look like crawler traps.

    Catches pathologically long URLs, query strings with absurd numbers of
    parameters (faceted-search explosions), and paths with the same segment
    repeated many times (mis-built relative links / calendar loops).
    """
    if len(url) > settings.max_url_length:
        return True
    try:
        p = urlparse(url)
    except ValueError:
        return True
    if p.query:
        params = parse_qsl(p.query, keep_blank_values=True)
        if len(params) > settings.max_query_params:
            return True
    segments = [s for s in p.path.split("/") if s]
    if len(segments) > settings.max_path_segments:
        return True
    if segments:
        run = 1
        for a, b in zip(segments, segments[1:]):
            run = run + 1 if a == b else 1
            if run >= 4:
                return True
    return False
