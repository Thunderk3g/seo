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
    """Return dict with title, word_count, links, console_errors,
    meta_description, plus the Phase 2A.5 structural mirror
    (headings, internal_links, external_links, images) so the
    in-house Inspector can be apples-to-apples with the competitor
    crawler's payload.
    """
    import re as _re
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    meta_desc_tag = soup.find(
        "meta", attrs={"name": _re.compile(r"^description$", _re.I)},
    )
    meta_description = ""
    if meta_desc_tag and meta_desc_tag.get("content"):
        meta_description = str(meta_desc_tag["content"]).strip()

    links = _collect_links(soup, base_url)

    console_errors = detect_console_errors(html, soup)

    # Phase 2A.5 — capture structural mirror BEFORE decomposing
    # script/style nodes (which strips text but leaves headings/anchors/
    # imgs untouched anyway; we still keep the order).
    structured = _extract_structured(soup, base_url)

    for el in soup(["script", "style", "noscript"]):
        el.decompose()
    text = _WS.sub(" ", soup.get_text(separator=" ", strip=True)).strip()
    word_count = len(text.split()) if text else 0

    # NOTE: ``text`` (the full visible body) is intentionally NOT returned
    # this round — we only derive word_count from it. Persisting body_text
    # + content classification is deferred (see CRAWLER_STORE_CONTENT in
    # apps/crawler/conf.py). To re-enable, add ``"body_text": text`` here
    # and have the fetcher stamp it onto the result row.
    return {
        "title": title,
        "meta_description": meta_description,
        "word_count": word_count,
        "links": links,
        "console_errors": console_errors,
        # Caps raised so link-heavy pages (homepage ~557 internal links) are no
        # longer truncated — these bound a pathological page, not normal ones.
        "headings": structured["headings"][:500],
        "internal_links": structured["internal_links"][:5000],
        "external_links": structured["external_links"][:2000],
        "images": structured["images"][:2000],
    }


# ── Structural mirror (reused on competitor side too) ─────────────
# Same shapes the competitor crawler emits, so the Inspector UI is
# template-agnostic between in-house and competitor data.

_LINK_KIND_PATTERNS_INHOUSE: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("calculator",      re.compile(r"/(calculator|estimate|tool)s?/?", re.I)),
    ("product_term",    re.compile(r"/term[-_]?insurance", re.I)),
    ("product_ulip",    re.compile(r"/ulip", re.I)),
    ("product_savings", re.compile(r"/(savings|endowment)", re.I)),
    ("product_retire",  re.compile(r"/(retirement|pension)", re.I)),
    ("product_child",   re.compile(r"/child[-_]?(insurance|plan)", re.I)),
    ("product_group",   re.compile(r"/group[-_]?(insurance|plan)", re.I)),
    ("product_health",  re.compile(r"/(health|wellness|diabetes)", re.I)),
    ("nri",             re.compile(r"/nri", re.I)),
    ("fund",            re.compile(r"/funds?/", re.I)),
    ("blog",            re.compile(r"/(blog|insights|articles|guide|resources)s?/?", re.I)),
    ("faq",             re.compile(r"/(faq|faqs|help|support)/?", re.I)),
    ("claim",           re.compile(r"/claim", re.I)),
    ("contact",         re.compile(r"/contact", re.I)),
    ("legal",           re.compile(r"/(privacy|terms|disclaimer|policy)", re.I)),
)


def _classify_link_kind(href: str) -> str:
    for label, pat in _LINK_KIND_PATTERNS_INHOUSE:
        if pat.search(href):
            return label
    return "other"


def _extract_structured(soup: "BeautifulSoup", base_url: str) -> dict:
    """Walk descendants() in document order capturing headings, anchors
    and images with their nearest preceding heading as 'section' AND
    landmark zone (header/nav/hero/main/aside/footer) for LayoutAgent.

    Mirrors the competitor-side extractor in
    ``apps.seo_ai.adapters.competitor_crawler`` so both sides emit
    identical JSON shape.
    """
    # Lazy import keeps the in-house parser independent of the
    # competitor adapter at module-load time.
    from apps.seo_ai.adapters.competitor_crawler import _classify_zone
    from urllib.parse import urljoin, urlparse

    page_host = (urlparse(base_url).hostname or "").lower().lstrip("www.")

    headings: list[dict] = []
    internal_links: list[dict] = []
    external_links: list[dict] = []
    images: list[dict] = []
    current_section = ""

    for el in soup.descendants:
        name = getattr(el, "name", None)
        if not name:
            continue

        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = el.get_text(" ", strip=True)
            if not text:
                continue
            level = int(name[1])
            headings.append({
                "level": level,
                "text": text[:300],
                "idx": len(headings),
                "zone": _classify_zone(el),
            })
            current_section = text[:200]
            continue

        if name == "a":
            href = (el.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            anchor = el.get_text(" ", strip=True)[:200]
            absolute = urljoin(base_url, href)
            target_host = (urlparse(absolute).hostname or "").lower().lstrip("www.")
            entry = {
                "anchor": anchor,
                "href": absolute[:1024],
                "section": current_section,
                "zone": _classify_zone(el),
                "kind": _classify_link_kind(absolute),
                "rel": " ".join(el.get("rel") or []) or "",
            }
            if not target_host or target_host == page_host or target_host.endswith("." + page_host):
                internal_links.append(entry)
            else:
                external_links.append(entry)
            continue

        if name == "img":
            src = (el.get("src") or "").strip()
            if not src:
                continue
            images.append({
                "src": urljoin(base_url, src)[:1024],
                "alt": (el.get("alt") or "").strip()[:300],
                "width": (el.get("width") or "").strip()[:8],
                "height": (el.get("height") or "").strip()[:8],
                "section": current_section,
                "zone": _classify_zone(el),
                "loading": (el.get("loading") or "").strip()[:16],
            })

    return {
        "headings": headings,
        "internal_links": internal_links,
        "external_links": external_links,
        "images": images,
    }
