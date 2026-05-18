"""HTML parser — extracts title, word count, and link list.

Heuristic console-error detection (regex-scanning the HTML for "Uncaught
TypeError" strings and broken <img>/<script> src attributes) was removed
per user request. Those signals were unreliable — a JS string literal
inside a script tag would trip them, and an empty src on a hidden img
isn't a real production bug. Real browser-console capture requires a
headless browser (Playwright) — that's a separate feature.

``detect_console_errors`` remains as an empty stub so existing call sites
in engine.py keep working without changes; it always returns ``[]``.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .url_utils import normalize

_WS = re.compile(r"\s+")


def detect_console_errors(html: str, soup: BeautifulSoup) -> list[str]:
    """Stub. Returns an empty list — heuristic detection was removed."""
    return []


# (tag, attribute) pairs that carry navigable in-site URLs.
_LINK_SOURCES: tuple[tuple[str, str], ...] = (
    ("a", "href"),
    ("area", "href"),
    ("iframe", "src"),
    ("frame", "src"),
)
# rel values on <link> tags worth following (canonical / hreflang / pagination).
_FOLLOW_LINK_RELS = {"canonical", "alternate", "next", "prev", "prerender"}
# data-* attributes commonly used to stash a navigation target.
_DATA_URL_ATTRS = ("data-href", "data-url", "data-link", "data-target-url", "data-redirect-url")

# Non-URL values that components routinely store in `data-*` attributes as
# config flags. Treating them as URLs (e.g. ``data-link="false"`` on the
# floating-feedback widget) caused spurious /false 404 entries across the
# whole site. Filter them out before normalize() ever sees them.
_NON_URL_DATA_VALUES = {
    "", "true", "false", "null", "undefined", "none", "0", "1",
    "yes", "no",
}


def _looks_like_url(value: str) -> bool:
    """Quick sanity check that a string value could plausibly be a URL.

    Used to filter out booleans / nulls / numeric config flags that
    AEM-style components stash in ``data-*`` attributes alongside legitimate
    navigation targets.
    """
    if not value:
        return False
    v = value.strip()
    if not v:
        return False
    if v.lower() in _NON_URL_DATA_VALUES:
        return False
    # Real URLs start with a scheme, "//", "/", "?", "#", or look relative
    # ("./foo", "../foo", "foo/bar"). Reject anything that is a single
    # bareword (no slash, no dot, no colon) — those are almost always
    # config flags, not paths.
    if v.startswith(("http://", "https://", "//", "/", "?", "#",
                     "./", "../")):
        return True
    return "/" in v or "." in v or ":" in v


def _collect_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Pull every plausibly-navigable URL out of the DOM, normalized & deduped."""
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: str | None) -> None:
        if not raw:
            return
        norm = normalize(raw, base_url)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)

    for tag_name, attr in _LINK_SOURCES:
        for el in soup.find_all(tag_name):
            add(el.get(attr))
    for el in soup.find_all("link"):
        rels = {r.lower() for r in (el.get("rel") or [])}
        if rels & _FOLLOW_LINK_RELS:
            add(el.get("href"))
    for attr in _DATA_URL_ATTRS:
        for el in soup.find_all(attrs={attr: True}):
            value = el.get(attr)
            if isinstance(value, str) and _looks_like_url(value):
                add(value)
    return out


def parse_page(html: str, base_url: str) -> dict:
    """Return dict with title, word_count, links, console_errors."""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    links = _collect_links(soup, base_url)

    console_errors = detect_console_errors(html, soup)

    for el in soup(["script", "style", "noscript"]):
        el.decompose()
    text = _WS.sub(" ", soup.get_text(separator=" ", strip=True)).strip()
    word_count = len(text.split()) if text else 0

    return {
        "title": title,
        "word_count": word_count,
        "links": links,
        "console_errors": console_errors,
    }
