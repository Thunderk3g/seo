"""HTML parser — extracts title, word count, link list, console-error hints."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .url_utils import normalize

_CONSOLE_PATTERNS = [
    (r"Uncaught\s+TypeError", "Uncaught TypeError detected in page source"),
    (r"Uncaught\s+ReferenceError", "Uncaught ReferenceError detected in page source"),
    (r"Uncaught\s+SyntaxError", "Uncaught SyntaxError detected in page source"),
    (r"Cannot\s+read\s+propert(?:y|ies)\s+of\s+null", "Null reference error pattern"),
    (r"Cannot\s+read\s+propert(?:y|ies)\s+of\s+undefined", "Undefined reference error pattern"),
    (r"is\s+not\s+a\s+function", "'not a function' error pattern"),
    (r"is\s+not\s+defined", "'not defined' error pattern"),
]

_WS = re.compile(r"\s+")


def detect_console_errors(html: str, soup: BeautifulSoup) -> list[str]:
    errors: list[str] = []
    for pat, msg in _CONSOLE_PATTERNS:
        if re.search(pat, html, re.IGNORECASE):
            errors.append(msg)
    for tag in soup.find_all(["img", "script", "link"], src=True):
        src = (tag.get("src") or "").strip()
        if not src or src == "#":
            errors.append(f"Empty/broken src attribute on <{tag.name}> tag")
    return errors


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
            add(el.get(attr))
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
