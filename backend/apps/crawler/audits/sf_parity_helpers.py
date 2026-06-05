"""Helpers that turn an HTTP response + parsed HTML into the
SEO signals the Phase-A detectors need.

Functions here are pure — no I/O beyond what the caller already
fetched. The crawler engines (legacy BFS + Scrapy spider) call
these once per URL and stash the results on the result-row dict,
which then flows into the CSV writer + Postgres dual-write.

The detector layer (``audits/detectors_phase_a.py``) reads the
stamped fields back out and emits issues.

Grouped by Phase-A feature:

  * security_headers_from(response_headers)
  * redirect_chain_from(response)
  * pixel_widths_from(title, meta_description)
  * canonical_signals_from(html, response_headers, page_url)
  * image_audit_from(html, page_url)

None of these block on additional HTTP — image-size checks defer
to a separate ``image_sizecheck.py`` worker pool because HEAD-
fetching every image is expensive enough to warrant batching.
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse


# ── A.1 — Security headers ─────────────────────────────────────────


_SECURITY_HEADER_NAMES = (
    ("hsts", "Strict-Transport-Security"),
    ("csp", "Content-Security-Policy"),
    ("x_frame_options", "X-Frame-Options"),
    ("x_content_type_options", "X-Content-Type-Options"),
    ("referrer_policy", "Referrer-Policy"),
    ("permissions_policy", "Permissions-Policy"),
)


def security_headers_from(headers) -> dict:
    """Extract the 6 SF-tracked security headers from a response.

    ``headers`` accepts either a Scrapy ``Headers`` (multi-dict of
    bytes) OR a dict / requests CaseInsensitiveDict (str->str). Returns
    a flat dict with the model-field-name keys."""
    out: dict[str, str] = {}
    for field, header in _SECURITY_HEADER_NAMES:
        out[field] = _header_value(headers, header)[:512]
    return out


def _header_value(headers, name: str) -> str:
    """Read one header regardless of which type the caller passed.

    Scrapy returns bytes; requests returns str. Both support
    case-insensitive lookup."""
    if headers is None:
        return ""
    # Try .get first (works for dict + requests + Scrapy Headers)
    try:
        v = headers.get(name)
    except Exception:  # noqa: BLE001
        v = None
    if v is None:
        # Case-insensitive search fallback.
        try:
            for k, val in headers.items():
                key = k.decode() if isinstance(k, (bytes, bytearray)) else str(k)
                if key.lower() == name.lower():
                    v = val
                    break
        except Exception:  # noqa: BLE001
            v = None
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("ascii", errors="replace")
        except Exception:  # noqa: BLE001
            return ""
    return str(v)


_INSECURE_FORM_RE = re.compile(
    r"""<form[^>]*\baction\s*=\s*["']http://""", re.IGNORECASE,
)
_MIXED_CONTENT_RE = re.compile(
    r"""(?:src|href)\s*=\s*["']http://""", re.IGNORECASE,
)


def mixed_content_flags(html: str, page_url: str) -> tuple[bool, bool]:
    """Detect mixed-content + insecure-form patterns in HTML.

    Mixed content fires when an HTTPS page references an `http://`
    sub-resource. Insecure form fires when a `<form action="http://...">`
    appears on any page (regardless of page scheme — it leaks credentials
    on submit)."""
    if not html:
        return (False, False)
    page_is_https = (page_url or "").lower().startswith("https://")
    has_insecure_form = bool(_INSECURE_FORM_RE.search(html))
    has_mixed = page_is_https and bool(_MIXED_CONTENT_RE.search(html))
    return (has_mixed, has_insecure_form)


# ── A.2 — Redirect chain ──────────────────────────────────────────


def redirect_chain_from_scrapy(response) -> dict:
    """Scrapy stamps ``response.meta["redirect_urls"]`` +
    ``redirect_reasons`` on the final response. Convert that into the
    model-friendly shape."""
    if response is None:
        return {"redirect_hops": 0, "redirect_chain": [], "redirect_final_url": "", "redirect_loop": False}
    meta = getattr(response, "meta", None) or {}
    urls = list(meta.get("redirect_urls") or [])
    reasons = list(meta.get("redirect_reasons") or [])
    chain: list[dict] = []
    for i, url in enumerate(urls):
        chain.append({
            "url": str(url),
            "status": int(reasons[i]) if i < len(reasons) else 302,
            "type": "http",
        })
    seen = {c["url"] for c in chain}
    loop = bool(chain) and (len(chain) != len(seen) or response.url in seen)
    return {
        "redirect_hops": len(chain),
        "redirect_chain": chain,
        "redirect_final_url": response.url if chain else "",
        "redirect_loop": loop,
    }


def redirect_chain_from_requests(response) -> dict:
    """``requests`` populates ``response.history`` with intermediate
    responses. Mirror the Scrapy shape so the writer doesn't care
    which engine produced it."""
    if response is None or not getattr(response, "history", None):
        return {"redirect_hops": 0, "redirect_chain": [], "redirect_final_url": "", "redirect_loop": False}
    history = list(response.history)
    chain: list[dict] = []
    seen_urls = []
    for h in history:
        chain.append({
            "url": str(h.url),
            "status": int(h.status_code),
            "type": _redirect_type_from_status(int(h.status_code)),
        })
        seen_urls.append(str(h.url))
    final_url = str(response.url)
    loop = final_url in seen_urls or len(seen_urls) != len(set(seen_urls))
    return {
        "redirect_hops": len(chain),
        "redirect_chain": chain,
        "redirect_final_url": final_url if chain else "",
        "redirect_loop": loop,
    }


def _redirect_type_from_status(status: int) -> str:
    if status == 301:
        return "http_permanent"
    if status == 302:
        return "http_temporary"
    if status == 307 or status == 308:
        return "http_modern"
    if status == 303:
        return "http_see_other"
    return "http"


# ── A.3 — Title + meta pixel widths ──────────────────────────────


# Google's SERP snippet font: Arial 20px desktop / 18px mobile. Pixel
# widths per character are well-documented. We approximate via Arial
# 20px metrics for the desktop column. Values measured from Google
# Search Console's pixel-width tool.
_ARIAL_20PX_WIDTHS: dict[str, int] = {
    # Punctuation + thin chars.
    " ": 5, "!": 6, "'": 4, "(": 6, ")": 6, ",": 5, "-": 7, ".": 5,
    "/": 6, ":": 5, ";": 5, "[": 6, "]": 6, "{": 7, "}": 7, "|": 5,
    # Digits.
    "0": 11, "1": 11, "2": 11, "3": 11, "4": 11, "5": 11,
    "6": 11, "7": 11, "8": 11, "9": 11,
    # Uppercase.
    "A": 13, "B": 13, "C": 14, "D": 14, "E": 13, "F": 12, "G": 15,
    "H": 14, "I": 6, "J": 10, "K": 13, "L": 11, "M": 16, "N": 14,
    "O": 15, "P": 13, "Q": 15, "R": 14, "S": 13, "T": 12, "U": 14,
    "V": 13, "W": 19, "X": 13, "Y": 13, "Z": 12,
    # Lowercase.
    "a": 11, "b": 11, "c": 10, "d": 11, "e": 11, "f": 6, "g": 11,
    "h": 11, "i": 5, "j": 5, "k": 10, "l": 5, "m": 17, "n": 11,
    "o": 11, "p": 11, "q": 11, "r": 7, "s": 10, "t": 6, "u": 11,
    "v": 10, "w": 14, "x": 10, "y": 10, "z": 10,
}
_DEFAULT_CHAR_WIDTH = 12  # for any char not in the table (CJK, devanagari, etc.)


def pixel_width(text: str) -> int:
    """Approximate Arial 20px pixel-width of a string.

    Google truncates SERP titles at ~580px desktop / ~480px mobile.
    Calling this on stripped title text gives a value comparable to
    Google's snippet-width tool. CJK + Devanagari (Hindi/Tamil) chars
    fall back to ``_DEFAULT_CHAR_WIDTH`` — accurate-enough for the
    "too long for SERP" gate; the absolute number is approximate."""
    if not text:
        return 0
    total = 0
    for ch in str(text):
        total += _ARIAL_20PX_WIDTHS.get(ch, _DEFAULT_CHAR_WIDTH)
    return total


def pixel_widths_from(title: str, meta_description: str) -> dict:
    return {
        "title_pixel_width": pixel_width(title or ""),
        "meta_description_pixel_width": pixel_width(meta_description or ""),
    }


# ── A.4 — Canonical signals ──────────────────────────────────────


_CANONICAL_HTML_RE = re.compile(
    r"""<link[^>]*\brel\s*=\s*["']canonical["'][^>]*\bhref\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE | re.DOTALL,
)
_CANONICAL_HTML_RE_REVERSED = re.compile(
    r"""<link[^>]*\bhref\s*=\s*["']([^"']+)["'][^>]*\brel\s*=\s*["']canonical["']""",
    re.IGNORECASE | re.DOTALL,
)


def canonical_signals_from(html: str, headers, page_url: str) -> dict:
    """Extract HTML + HTTP canonical, detect mismatch + multiples.

    The HTTP ``Link: <url>; rel="canonical"`` header has higher
    authority than the HTML tag in Google's view — surface both."""
    html_matches: list[str] = []
    if html:
        for m in _CANONICAL_HTML_RE.findall(html):
            html_matches.append(_absolute(m, page_url))
        for m in _CANONICAL_HTML_RE_REVERSED.findall(html):
            html_matches.append(_absolute(m, page_url))
    # De-dupe preserving order
    seen: set[str] = set()
    html_matches = [u for u in html_matches if not (u in seen or seen.add(u))]
    canonical_html = html_matches[0] if html_matches else ""
    multiple_canonicals = len(html_matches) > 1

    canonical_http = ""
    link_header = _header_value(headers, "Link")
    if link_header:
        # Parse `<url>; rel="canonical", <url2>; rel="next", ...`
        for entry in link_header.split(","):
            entry = entry.strip()
            if "rel=\"canonical\"" in entry or "rel='canonical'" in entry or "rel=canonical" in entry:
                m = re.search(r"<([^>]+)>", entry)
                if m:
                    canonical_http = _absolute(m.group(1), page_url)
                    break

    mismatch = bool(
        canonical_html
        and canonical_http
        and canonical_html != canonical_http
    )
    return {
        "canonical_html": canonical_html[:2048],
        "canonical_http": canonical_http[:2048],
        "canonical_mismatch": mismatch,
        "multiple_canonicals": multiple_canonicals,
    }


def _absolute(maybe_relative: str, base: str) -> str:
    if not maybe_relative:
        return ""
    try:
        return urljoin(base or "", maybe_relative.strip())
    except (ValueError, TypeError):
        return maybe_relative


# ── A.6 — Indexability verdict (meta robots + X-Robots-Tag) ──────────
#
# Google decides "can this URL be indexed?" from three on-page signals
# we can read for free off the response we already have:
#   1. <meta name="robots"|"googlebot" content="...noindex...">
#   2. the X-Robots-Tag HTTP header (same directives, header form)
#   3. a canonical that points AWAY to a different URL (Google folds the
#      page into the canonical target — it won't index this URL itself)
# plus the HTTP status (non-200 is never indexable). robots.txt *crawl*
# blocking is NOT visible here — the engine stamps that separately when
# it skips a disallowed URL.
#
# We collapse these into one ``indexability_status`` whose values line
# up 1:1 with the GSC "Why pages aren't indexed" buckets so the
# crawler↔GSC reconciliation can join on them:
#   indexable | noindex | canonicalized | non_200
_META_ROBOTS_RE = re.compile(
    r"""<meta\b[^>]*\bname\s*=\s*["']?(?:robots|googlebot)["']?[^>]*"""
    r"""\bcontent\s*=\s*["']([^"']*)["']""",
    re.IGNORECASE | re.DOTALL,
)
_META_ROBOTS_RE_REVERSED = re.compile(
    r"""<meta\b[^>]*\bcontent\s*=\s*["']([^"']*)["'][^>]*"""
    r"""\bname\s*=\s*["']?(?:robots|googlebot)["']?""",
    re.IGNORECASE | re.DOTALL,
)


def _norm_url(u: str) -> str:
    """Loose URL equality for canonical-vs-self: drop fragment, trailing
    slash, and scheme/host case. Good enough to tell 'self-canonical'
    from 'points elsewhere' without false mismatches."""
    if not u:
        return ""
    try:
        p = urlparse(u.strip())
        host = (p.netloc or "").lower()
        path = (p.path or "/").rstrip("/") or "/"
        return f"{host}{path}"
    except (ValueError, TypeError):
        return u.strip().lower()


def indexability_signals_from(
    html: str,
    headers,
    page_url: str,
    status_code: int,
    canonical_target: str = "",
) -> dict:
    """Return the on-page indexability verdict for one URL.

    ``canonical_target`` is the already-resolved canonical (pass
    canonical_http or canonical_html from ``canonical_signals_from`` —
    HTTP header wins). Empty means no canonical declared.
    """
    directives: list[str] = []
    if html:
        for m in _META_ROBOTS_RE.findall(html):
            directives.append(m.strip().lower())
        for m in _META_ROBOTS_RE_REVERSED.findall(html):
            directives.append(m.strip().lower())
    # De-dupe preserving order for a readable meta_robots column.
    seen: set[str] = set()
    directives = [d for d in directives if d and not (d in seen or seen.add(d))]
    meta_robots = ", ".join(directives)[:256]

    x_robots = (_header_value(headers, "X-Robots-Tag") or "")[:256]

    blob = " ".join(directives) + " " + x_robots.lower()
    has_noindex = ("noindex" in blob) or ("none" in blob)

    canonicalized = bool(
        canonical_target
        and _norm_url(canonical_target) != _norm_url(page_url)
    )

    status = int(status_code or 0)
    if status and status != 200:
        verdict, indexable, reason = "non_200", False, f"http_{status}"
    elif has_noindex:
        verdict, indexable, reason = "noindex", False, "meta_or_xrobots_noindex"
    elif canonicalized:
        verdict, indexable, reason = "canonicalized", False, "non_self_canonical"
    else:
        verdict, indexable, reason = "indexable", True, ""

    return {
        "meta_robots": meta_robots,
        "x_robots_tag": x_robots,
        "is_indexable": indexable,
        "indexability_status": verdict,
        "indexability_reason": reason,
    }


# ── A.5 — Image audit ────────────────────────────────────────────


_IMG_RE = re.compile(
    r"<img\b([^>]*)>",
    re.IGNORECASE | re.DOTALL,
)
_ATTR_RE = re.compile(
    r"""\b([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
)


def image_audit_from(html: str, page_url: str) -> dict:
    """Walk every `<img>` tag in the HTML and aggregate alt/loading
    signals. Per-image detail (src, alt, lazy) is stored in
    ``image_audit_extra`` for drill-in; row-level columns are
    aggregate counts.

    File-size checks live in ``image_sizecheck.py`` (separate HEAD-
    fetch worker pool) because they're 10× more expensive than the
    HTML pass — running them inline would add 5-15s per page."""
    if not html:
        return {
            "image_count": 0, "image_missing_alt": 0, "image_empty_alt": 0,
            "image_oversized_count": 0, "image_broken_count": 0,
            "image_audit_extra": {},
        }
    images: list[dict] = []
    missing_alt = 0
    empty_alt = 0
    for tag_match in _IMG_RE.finditer(html):
        attrs_blob = tag_match.group(1) or ""
        attrs: dict[str, str] = {}
        for m in _ATTR_RE.finditer(attrs_blob):
            key = m.group(1).lower()
            val = m.group(2) or m.group(3) or m.group(4) or ""
            attrs[key] = val
        src = attrs.get("src", "")
        if not src:
            continue  # data-src lazy-load handled below
        alt = attrs.get("alt")
        if alt is None:
            missing_alt += 1
        elif not alt.strip():
            empty_alt += 1
        images.append({
            "src": _absolute(src, page_url)[:1024],
            "alt": (alt or "")[:256],
            "alt_missing": alt is None,
            "alt_empty": (alt is not None and not alt.strip()),
            "width": attrs.get("width", ""),
            "height": attrs.get("height", ""),
            "srcset": attrs.get("srcset", "")[:512],
            "loading": attrs.get("loading", ""),
            "lazy": (attrs.get("loading", "").lower() == "lazy"),
        })
    return {
        "image_count": len(images),
        "image_missing_alt": missing_alt,
        "image_empty_alt": empty_alt,
        # Size + broken checks happen in the second-pass HEAD worker.
        "image_oversized_count": 0,
        "image_broken_count": 0,
        # Cap detail to first 50 images per page so JSONB stays small.
        "image_audit_extra": {"images": images[:50]},
    }
