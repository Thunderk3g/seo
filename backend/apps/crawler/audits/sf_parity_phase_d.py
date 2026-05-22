"""Phase D — SF parity helpers for cookies, AMP, accessibility.

Three feature groups; all extracted from the response the fetcher
already has, no extra HTTP. Detectors in ``detectors_phase_d.py``
read the stamped fields back out.

  * cookie_signals_from(headers, page_url)
        → list of {name, secure, http_only, samesite, third_party,
          tracker} plus aggregate counts + consent-banner flag.

  * amp_signals_from(html, page_url)
        → has_amp_canonical, is_amp_page, amp_canonical_url,
          amp_required_tags_missing (list), amp_invalid (bool).

  * accessibility_signals_from(html)
        → html_lang, h1_count, heading_skips, form_inputs_no_label,
          links_no_text, invalid_aria_roles, has_skip_link.

Forms-based auth lives in ``auth_helpers.py`` (a different shape —
it mutates the requests.Session before crawling).
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup


# ── D.1 — Cookies ─────────────────────────────────────────────────


# Known tracking cookies (Google Analytics, Meta Pixel, Hotjar, etc).
# Conservative set — only the ones that ARE trackers, not analytics
# the user owns. The "no consent" detector pairs these with a missing
# consent-banner detection.
_TRACKER_COOKIE_PREFIXES = (
    "_ga", "_gid", "_gat",          # Google Analytics
    "_gcl_", "__gads", "__gpi",     # Google Ads
    "_fbp", "_fbc", "fr",           # Meta / Facebook
    "_hjid", "_hjincludedinsample", # Hotjar
    "__utm", "_dc_gtm_",            # Universal Analytics / GTM
    "mp_", "amp_", "ajs_",          # Mixpanel / Amplitude / Segment
    "intercom-",                    # Intercom
    "_clck", "_clsk",               # Microsoft Clarity
    "_pin_unauth", "_pinterest_ct", # Pinterest
)

# Common consent-banner library markers in HTML.
_CONSENT_HTML_MARKERS = (
    "cookielaw.org", "onetrust", "cookieyes", "cookiebot",
    "didomi", "trustarc", "consensu.org", "iubenda",
    "klaro", "tarteaucitron", "termly", "cookie-script",
    "cc-window", "cookieconsent",
)


def _parse_set_cookie(raw: str) -> dict | None:
    """Parse a single Set-Cookie value into {name, value, attrs}."""
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    if not parts:
        return None
    name_value = parts[0]
    if "=" not in name_value:
        return None
    name = name_value.split("=", 1)[0].strip()
    attrs = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            attrs[k.strip().lower()] = v.strip()
        else:
            attrs[p.strip().lower()] = True
    return {"name": name, "attrs": attrs}


def _etld_plus_one(host: str) -> str:
    """Cheap eTLD+1 approximation — last two labels. Works for the
    common case (example.com, foo.example.com). Misses two-part TLDs
    (.co.uk) but those aren't common for the Bajaj universe."""
    host = (host or "").split(":")[0].lower().lstrip(".")
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    return ".".join(parts[-2:])


def cookie_signals_from(headers, page_url: str, html: str = "") -> dict:
    """Extract per-cookie attributes + aggregate counts for the
    detector layer. ``html`` is used only to spot a consent banner.
    """
    is_https = (page_url or "").startswith("https://")
    page_host = urlparse(page_url or "").netloc
    page_etld1 = _etld_plus_one(page_host)

    raw_values: list[str] = []
    if headers is not None:
        try:
            getlist = getattr(headers, "getlist", None)
            if callable(getlist):
                raw_values = [
                    v.decode("latin-1", "ignore") if isinstance(v, bytes) else v
                    for v in getlist("Set-Cookie")
                ]
            else:
                # requests CaseInsensitiveDict joins them with ", " — use
                # the raw cookie jar instead when possible.
                multi = headers.get("Set-Cookie") or ""
                if multi:
                    # Naive split — Set-Cookie may contain commas inside
                    # Expires=, but requests usually feeds us one per call.
                    raw_values = re.split(r",(?=[^;]+=)", multi)
        except Exception:  # noqa: BLE001
            raw_values = []

    cookies = []
    insecure = 0
    no_samesite = 0
    no_httponly_session = 0
    third_party = 0
    tracker_count = 0

    for raw in raw_values:
        parsed = _parse_set_cookie(raw)
        if not parsed:
            continue
        name = parsed["name"]
        attrs = parsed["attrs"]
        is_secure = "secure" in attrs
        is_http_only = "httponly" in attrs
        samesite = (attrs.get("samesite") or "").lower()
        domain = (attrs.get("domain") or "").lstrip(".")
        is_third_party = bool(domain) and _etld_plus_one(domain) != page_etld1
        is_tracker = any(name.lower().startswith(p) for p in _TRACKER_COOKIE_PREFIXES)
        has_expiry = "expires" in attrs or "max-age" in attrs
        is_session = not has_expiry

        if is_https and not is_secure:
            insecure += 1
        if not samesite:
            no_samesite += 1
        if is_session and not is_http_only:
            no_httponly_session += 1
        if is_third_party:
            third_party += 1
        if is_tracker:
            tracker_count += 1

        cookies.append({
            "name": name,
            "secure": is_secure,
            "http_only": is_http_only,
            "samesite": samesite,
            "third_party": is_third_party,
            "tracker": is_tracker,
        })

    has_consent_banner = False
    if html:
        lowered = html.lower()
        has_consent_banner = any(m in lowered for m in _CONSENT_HTML_MARKERS)

    return {
        "cookie_count": len(cookies),
        "cookies": cookies,
        "cookies_insecure_count": insecure,
        "cookies_no_samesite_count": no_samesite,
        "cookies_no_httponly_session_count": no_httponly_session,
        "cookies_third_party_count": third_party,
        "cookies_tracker_count": tracker_count,
        "has_consent_banner": has_consent_banner,
    }


# ── D.2 — AMP validation ──────────────────────────────────────────


# Required tags per https://amp.dev/documentation/guides-and-tutorials/
# learn/spec/amphtml/. Conservative subset — these MUST be present.
_AMP_REQUIRED_PATTERNS = (
    ("script_runtime",
     re.compile(r'<script[^>]+src=["\']https://cdn\.ampproject\.org/v\d+\.js["\']',
                re.IGNORECASE)),
    ("amp_attribute",
     re.compile(r'<html[^>]*\s(amp|⚡)(\s|>)', re.IGNORECASE)),
    ("charset",
     re.compile(r'<meta[^>]+charset=["\']?utf-8["\']?', re.IGNORECASE)),
    ("viewport",
     re.compile(r'<meta[^>]+name=["\']viewport["\']', re.IGNORECASE)),
    ("canonical",
     re.compile(r'<link[^>]+rel=["\']canonical["\']', re.IGNORECASE)),
    ("boilerplate",
     re.compile(r'<style[^>]+amp-boilerplate', re.IGNORECASE)),
)


def amp_signals_from(html: str, page_url: str) -> dict:
    """Detect AMP linkage + (if this IS an AMP page) validate the
    required-tag set."""
    if not html:
        return _empty_amp()
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001
        return _empty_amp()

    # Linked-from-canonical AMP version
    amp_link = ""
    for link in soup.find_all("link"):
        rels = {r.lower() for r in (link.get("rel") or [])}
        if "amphtml" in rels:
            amp_link = (link.get("href") or "").strip()
            break

    # Is THIS page itself an AMP page?
    html_tag = soup.find("html")
    is_amp = False
    if html_tag is not None:
        attrs = {k.lower() for k in (html_tag.attrs or {}).keys()}
        is_amp = "amp" in attrs or "⚡" in attrs

    missing: list[str] = []
    amp_invalid = False
    if is_amp:
        for name, pattern in _AMP_REQUIRED_PATTERNS:
            if not pattern.search(html):
                missing.append(name)
        amp_invalid = len(missing) > 0

    # If this is AMP, what's its canonical (must point back to non-AMP)?
    amp_canonical_target = ""
    if is_amp:
        for link in soup.find_all("link"):
            rels = {r.lower() for r in (link.get("rel") or [])}
            if "canonical" in rels:
                amp_canonical_target = (link.get("href") or "").strip()
                break

    return {
        "is_amp_page": is_amp,
        "has_amp_alternate": bool(amp_link),
        "amp_alternate_url": amp_link,
        "amp_canonical_target": amp_canonical_target,
        "amp_required_missing": missing,
        "amp_invalid": amp_invalid,
    }


def _empty_amp() -> dict:
    return {
        "is_amp_page": False,
        "has_amp_alternate": False,
        "amp_alternate_url": "",
        "amp_canonical_target": "",
        "amp_required_missing": [],
        "amp_invalid": False,
    }


# ── D.3 — Accessibility-lite (WCAG checks) ────────────────────────


# Valid WAI-ARIA 1.2 roles (https://www.w3.org/TR/wai-aria-1.2/).
_VALID_ARIA_ROLES = frozenset({
    "alert", "alertdialog", "application", "article", "banner",
    "button", "cell", "checkbox", "columnheader", "combobox",
    "complementary", "contentinfo", "definition", "dialog",
    "directory", "document", "feed", "figure", "form", "grid",
    "gridcell", "group", "heading", "img", "link", "list",
    "listbox", "listitem", "log", "main", "marquee", "math",
    "menu", "menubar", "menuitem", "menuitemcheckbox",
    "menuitemradio", "navigation", "none", "note", "option",
    "presentation", "progressbar", "radio", "radiogroup",
    "region", "row", "rowgroup", "rowheader", "scrollbar",
    "search", "searchbox", "separator", "slider", "spinbutton",
    "status", "switch", "tab", "table", "tablist", "tabpanel",
    "term", "textbox", "timer", "toolbar", "tooltip", "tree",
    "treegrid", "treeitem",
})


def accessibility_signals_from(html: str) -> dict:
    """Pure-Python WCAG checks doable without a headless browser.

    Skips color-contrast (needs computed styles) and focus-order
    (needs JS). What's left still covers the largest WCAG
    violation classes: missing labels, heading hierarchy, lang,
    ARIA misuse, generic link text.
    """
    empty = _empty_a11y()
    if not html:
        return empty
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001
        return empty

    out = dict(empty)

    html_tag = soup.find("html")
    out["html_lang"] = ""
    if html_tag is not None:
        out["html_lang"] = (html_tag.get("lang") or "").strip()

    # Headings: count h1, detect skipped levels (h1 → h3 with no h2).
    h_seq: list[int] = []
    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        try:
            h_seq.append(int(h.name[1]))
        except (ValueError, IndexError):
            continue
    out["h1_count"] = sum(1 for x in h_seq if x == 1)
    skips = 0
    for i in range(1, len(h_seq)):
        if h_seq[i] - h_seq[i - 1] > 1:
            skips += 1
    out["heading_skip_count"] = skips

    # Form inputs without an associated label.
    inputs_no_label = 0
    for inp in soup.find_all(["input", "textarea", "select"]):
        itype = (inp.get("type") or "").lower()
        if itype in ("hidden", "submit", "button", "reset"):
            continue
        if inp.get("aria-label") or inp.get("aria-labelledby"):
            continue
        if inp.get("title"):
            continue
        inp_id = inp.get("id")
        if inp_id and soup.find("label", attrs={"for": inp_id}):
            continue
        # Wrapped in a <label>?
        if inp.find_parent("label"):
            continue
        inputs_no_label += 1
    out["form_inputs_no_label"] = inputs_no_label

    # Links with no accessible text.
    generic_link_text = {"click here", "read more", "more", "here",
                         "link", "this link", "learn more"}
    links_no_text = 0
    links_generic_text = 0
    for a in soup.find_all("a"):
        text = (a.get_text() or "").strip()
        aria = a.get("aria-label") or a.get("aria-labelledby") or ""
        title = a.get("title") or ""
        if not (text or aria or title):
            # Permit links that wrap an <img> with alt text.
            img = a.find("img")
            if img and (img.get("alt") or "").strip():
                continue
            links_no_text += 1
            continue
        if text.lower() in generic_link_text:
            links_generic_text += 1
    out["links_no_text"] = links_no_text
    out["links_generic_text"] = links_generic_text

    # Invalid ARIA roles.
    invalid_roles: list[str] = []
    for el in soup.find_all(attrs={"role": True}):
        role = (el.get("role") or "").strip().lower()
        if not role:
            continue
        # role can be space-separated list of fallback roles.
        for r in role.split():
            if r and r not in _VALID_ARIA_ROLES:
                invalid_roles.append(r)
    out["invalid_aria_roles"] = sorted(set(invalid_roles))

    # Skip-nav link presence (anchor pointing at #main / #content with
    # text like "skip to main content").
    has_skip = False
    for a in soup.find_all("a", href=True):
        if not a["href"].startswith("#"):
            continue
        text = (a.get_text() or "").lower()
        if "skip" in text and ("content" in text or "main" in text or "navigation" in text):
            has_skip = True
            break
    out["has_skip_link"] = has_skip

    return out


def _empty_a11y() -> dict:
    return {
        "html_lang": "",
        "h1_count": 0,
        "heading_skip_count": 0,
        "form_inputs_no_label": 0,
        "links_no_text": 0,
        "links_generic_text": 0,
        "invalid_aria_roles": [],
        "has_skip_link": False,
    }
