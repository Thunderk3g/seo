"""Phase B — SF parity helpers for hreflang + schema.org JSON-LD.

Two feature groups, both extracted from the HTML body the fetcher
already has in hand (no extra HTTP round-trips):

  * hreflang_signals_from(html, headers, page_url)
        → counts, entries, x-default flag, invalid BCP-47 codes,
          self-reference flag. Cross-page return-tag validation runs
          later in the audit phase, once the whole crawl is loaded.

  * jsonld_signals_from(html)
        → JSON-LD blocks, types found, parse-failure count, required
          props missing per schema.org type, microdata + RDFa counts,
          and the subset of types eligible for a Google rich result.

The detectors in ``detectors_phase_b.py`` read the stamped fields
back out and emit issues. Cross-page hreflang return-tag validation
lives in a separate runner-time pass (``hreflang_matrix.py``).
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


# ── B.1 — Hreflang ─────────────────────────────────────────────────


# BCP-47: language[-script][-region]. We accept lowercase lang +
# optional uppercase region (`en`, `en-US`, `zh-Hant`, `x-default`).
# Anything outside this shape is reported as invalid.
_BCP47_RE = re.compile(
    r"^(?:x-default|[A-Za-z]{2,3}(?:-[A-Za-z]{4})?(?:-[A-Za-z]{2}|-\d{3})?)$"
)
# Common valid ISO 639-1 language codes — we don't enforce the full
# IANA registry (too large to ship); the regex above catches the 99%
# case (right shape) and this set rejects two-letter sequences that
# look correct but aren't real languages (e.g. "xx", "zz").
_KNOWN_LANG_PREFIXES = {
    "aa","ab","ae","af","ak","am","an","ar","as","av","ay","az","ba","be","bg",
    "bh","bi","bm","bn","bo","br","bs","ca","ce","ch","co","cr","cs","cu","cv",
    "cy","da","de","dv","dz","ee","el","en","eo","es","et","eu","fa","ff","fi",
    "fj","fo","fr","fy","ga","gd","gl","gn","gu","gv","ha","he","hi","ho","hr",
    "ht","hu","hy","hz","ia","id","ie","ig","ii","ik","io","is","it","iu","ja",
    "jv","ka","kg","ki","kj","kk","kl","km","kn","ko","kr","ks","ku","kv","kw",
    "ky","la","lb","lg","li","ln","lo","lt","lu","lv","mg","mh","mi","mk","ml",
    "mn","mr","ms","mt","my","na","nb","nd","ne","ng","nl","nn","no","nr","nv",
    "ny","oc","oj","om","or","os","pa","pi","pl","ps","pt","qu","rm","rn","ro",
    "ru","rw","sa","sc","sd","se","sg","si","sk","sl","sm","sn","so","sq","sr",
    "ss","st","su","sv","sw","ta","te","tg","th","ti","tk","tl","tn","to","tr",
    "ts","tt","tw","ty","ug","uk","ur","uz","ve","vi","vo","wa","wo","xh","yi",
    "yo","za","zh","zu",
}


def _valid_bcp47(code: str) -> bool:
    code = (code or "").strip()
    if not code:
        return False
    if code.lower() == "x-default":
        return True
    if not _BCP47_RE.match(code):
        return False
    prefix = code.split("-")[0].lower()
    return prefix in _KNOWN_LANG_PREFIXES


def hreflang_signals_from(html: str, headers, page_url: str) -> dict:
    """Extract hreflang entries from <link> tags AND Link HTTP header.

    Returns a dict keyed by model-field name. ``hreflang_entries`` is
    a list of ``{"lang": "...", "href": "..."}`` dicts, with hrefs
    resolved against ``page_url`` so the cross-page matrix can match
    them by absolute URL.
    """
    entries: list[dict] = []
    invalid: list[str] = []
    seen: set[tuple[str, str]] = set()

    try:
        soup = BeautifulSoup(html or "", "html.parser")
    except Exception:  # noqa: BLE001
        soup = None

    if soup is not None:
        for link in soup.find_all("link"):
            rels = {r.lower() for r in (link.get("rel") or [])}
            if "alternate" not in rels:
                continue
            lang = (link.get("hreflang") or "").strip()
            href_raw = (link.get("href") or "").strip()
            if not lang or not href_raw:
                continue
            href = urljoin(page_url, href_raw)
            key = (lang.lower(), href)
            if key in seen:
                continue
            seen.add(key)
            if not _valid_bcp47(lang):
                invalid.append(lang)
            entries.append({"lang": lang, "href": href})

    # HTTP Link: <...>; rel="alternate"; hreflang="..."
    link_header = ""
    if headers is not None:
        try:
            link_header = headers.get("Link") or headers.get("link") or ""
            if isinstance(link_header, bytes):
                link_header = link_header.decode("latin-1", "ignore")
        except Exception:  # noqa: BLE001
            link_header = ""
    if link_header:
        for part in link_header.split(","):
            m_url = re.search(r"<([^>]+)>", part)
            m_rel = re.search(r'rel\s*=\s*"?([^";\s]+)"?', part)
            m_lang = re.search(r'hreflang\s*=\s*"?([^";\s]+)"?', part)
            if not (m_url and m_rel and m_lang):
                continue
            if "alternate" not in m_rel.group(1).lower():
                continue
            href = urljoin(page_url, m_url.group(1).strip())
            lang = m_lang.group(1).strip()
            key = (lang.lower(), href)
            if key in seen:
                continue
            seen.add(key)
            if not _valid_bcp47(lang):
                invalid.append(lang)
            entries.append({"lang": lang, "href": href})

    has_x_default = any(e["lang"].lower() == "x-default" for e in entries)
    self_ref = any(e["href"].rstrip("/") == page_url.rstrip("/") for e in entries)

    return {
        "hreflang_count": len(entries),
        "hreflang_entries": entries,
        "hreflang_has_x_default": has_x_default,
        "hreflang_invalid_codes": invalid,
        "hreflang_self_reference": self_ref,
    }


# ── B.2 — Schema.org JSON-LD ──────────────────────────────────────


# Required properties per schema.org type for Google rich-result
# eligibility. Source: https://developers.google.com/search/docs/
# appearance/structured-data. Kept conservative — required props only,
# not recommended ones, so we never false-flag a valid block.
_REQUIRED_PROPS: dict[str, tuple[str, ...]] = {
    "Article": ("headline", "author"),
    "NewsArticle": ("headline", "author"),
    "BlogPosting": ("headline", "author"),
    "Product": ("name",),
    "Offer": ("price", "priceCurrency"),
    "Review": ("reviewRating", "author"),
    "AggregateRating": ("ratingValue", "reviewCount"),
    "Recipe": ("name", "image", "recipeIngredient", "recipeInstructions"),
    "Event": ("name", "startDate", "location"),
    "JobPosting": ("title", "description", "datePosted", "hiringOrganization"),
    "FAQPage": ("mainEntity",),
    "Question": ("name", "acceptedAnswer"),
    "BreadcrumbList": ("itemListElement",),
    "VideoObject": ("name", "description", "thumbnailUrl", "uploadDate"),
    "Organization": ("name", "url"),
    "LocalBusiness": ("name", "address", "telephone"),
    "Course": ("name", "description", "provider"),
    "HowTo": ("name", "step"),
    "SoftwareApplication": ("name", "operatingSystem", "applicationCategory"),
}

# Types Google currently surfaces as rich results.
_RICH_RESULT_TYPES = frozenset(_REQUIRED_PROPS.keys())


def _walk_types(node: Any, out: list[str]) -> None:
    """Recursively collect every @type string from a JSON-LD tree."""
    if isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, list):
            out.extend([x for x in t if isinstance(x, str)])
        for v in node.values():
            _walk_types(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_types(item, out)


def _required_props_missing(node: Any, out: list[dict]) -> None:
    """Walk JSON-LD; for every typed object, flag missing required
    props. Appends ``{"type": str, "prop": str}`` per gap."""
    if isinstance(node, dict):
        t = node.get("@type")
        types: list[str] = []
        if isinstance(t, str):
            types.append(t)
        elif isinstance(t, list):
            types.extend([x for x in t if isinstance(x, str)])
        for type_name in types:
            for prop in _REQUIRED_PROPS.get(type_name, ()):
                if prop not in node:
                    out.append({"type": type_name, "prop": prop})
        for v in node.values():
            _required_props_missing(v, out)
    elif isinstance(node, list):
        for item in node:
            _required_props_missing(item, out)


def jsonld_signals_from(html: str) -> dict:
    """Parse every JSON-LD block from the page; report types,
    invalid-parse count, missing required props, and rich-result
    eligibility.

    Microdata + RDFa counts are reported (so detectors can flag
    'page uses legacy markup, migrate to JSON-LD') but not parsed
    in depth — Google has favored JSON-LD for years.
    """
    try:
        soup = BeautifulSoup(html or "", "html.parser")
    except Exception:  # noqa: BLE001
        return _empty_jsonld()

    blocks: list[Any] = []
    invalid = 0
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            invalid += 1
            continue
        try:
            blocks.append(json.loads(raw))
        except (ValueError, TypeError):
            invalid += 1

    all_types: list[str] = []
    missing: list[dict] = []
    for block in blocks:
        _walk_types(block, all_types)
        _required_props_missing(block, missing)

    types_unique = sorted({t for t in all_types})
    rich_eligible = sorted({t for t in types_unique if t in _RICH_RESULT_TYPES})

    microdata_count = len(soup.find_all(attrs={"itemscope": True}))
    rdfa_count = len(soup.find_all(attrs={"typeof": True}))

    return {
        "jsonld_count": len(blocks),
        "jsonld_types": types_unique,
        "jsonld_blocks": blocks,
        "jsonld_invalid_count": invalid,
        "jsonld_missing_required": missing,
        "jsonld_rich_result_eligible": rich_eligible,
        "microdata_count": microdata_count,
        "rdfa_count": rdfa_count,
    }


def _empty_jsonld() -> dict:
    return {
        "jsonld_count": 0,
        "jsonld_types": [],
        "jsonld_blocks": [],
        "jsonld_invalid_count": 0,
        "jsonld_missing_required": [],
        "jsonld_rich_result_eligible": [],
        "microdata_count": 0,
        "rdfa_count": 0,
    }
