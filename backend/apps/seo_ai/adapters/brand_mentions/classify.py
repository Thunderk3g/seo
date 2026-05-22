"""Brand-variant + source-tier classifiers.

Pure-Python, no API calls — runs synchronously inside the adapter
write path. Two responsibilities:

1. **Brand variant** — given a snippet + title, decide whether the
   mention uses the new brand ("Bajaj Life Insurance"), the legacy
   one ("Bajaj Allianz Life"), or the parent group name ("Bajaj
   Allianz") with no Life-specific qualifier. Drives the rebrand
   stickiness chart.

2. **Source tier** — given a domain, look up which authority tier
   it falls into (news-tier-1, forum, review, aggregator, regulatory,
   blog, other). Drives the source-tier donut + filter.

Both are settings-driven via ``BRAND_MENTIONS`` so the operator can
extend without code changes (add new tier domains via env or a
follow-up settings edit).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from django.conf import settings

from ...models import BrandVariant, MentionSourceTier


# ── brand variant ─────────────────────────────────────────────────────

# Pre-compiled per-process at first use so repeated classification calls
# don't pay re-compile cost. Order matters — longer variants must be
# checked first so "Bajaj Allianz Life" doesn't get short-circuited by
# the parent "Bajaj Allianz" pattern.
_BRAND_PATTERNS_CACHE: list[tuple[re.Pattern[str], str]] | None = None


def _load_brand_patterns() -> list[tuple[re.Pattern[str], str]]:
    global _BRAND_PATTERNS_CACHE
    if _BRAND_PATTERNS_CACHE is not None:
        return _BRAND_PATTERNS_CACHE
    cfg = getattr(settings, "BRAND_MENTIONS", None) or {}
    pats: list[tuple[re.Pattern[str], str]] = []
    # Longer (more specific) patterns first — first-match-wins.
    for tok in cfg.get("brand_tokens_old", []):
        pats.append((re.compile(r"\b" + re.escape(tok) + r"\b", re.I), BrandVariant.OLD))
    for tok in cfg.get("brand_tokens_new", []):
        pats.append((re.compile(r"\b" + re.escape(tok) + r"\b", re.I), BrandVariant.NEW))
    for tok in cfg.get("brand_tokens_parent", []):
        pats.append((re.compile(r"\b" + re.escape(tok) + r"\b", re.I), BrandVariant.PARENT))
    _BRAND_PATTERNS_CACHE = pats
    return pats


def classify_brand_variant(*texts: str) -> str:
    """Return the BrandVariant code matching the first brand token
    found in ``texts``. Inputs are concatenated lazily so passing
    ``(title, snippet)`` checks both. Returns ``BrandVariant.AMBIGUOUS``
    when no match (caller should usually filter these out)."""
    haystack = " ".join(t for t in texts if t)
    matched: list[str] = []
    for pat, variant in _load_brand_patterns():
        if pat.search(haystack):
            matched.append(variant)
    if not matched:
        return BrandVariant.AMBIGUOUS
    # Prefer the longest specific variant first (since patterns are
    # ordered old-then-new-then-parent, take the first hit).
    return matched[0]


def all_brand_tokens() -> list[str]:
    """Flat list of every configured brand token, longest first.

    Used by adapters that need to build query strings ("Bajaj Life
    Insurance" OR "Bajaj Allianz Life"...) — passing each token
    independently to the data source.
    """
    cfg = getattr(settings, "BRAND_MENTIONS", None) or {}
    tokens: list[str] = []
    tokens.extend(cfg.get("brand_tokens_old") or [])
    tokens.extend(cfg.get("brand_tokens_new") or [])
    tokens.extend(cfg.get("brand_tokens_parent") or [])
    # De-dupe preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ── source tier ───────────────────────────────────────────────────────


def domain_of(url: str) -> str:
    """Best-effort: extract a lowercased, www-stripped host from a URL.
    Returns empty string for malformed URLs (caller treats as 'other')."""
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def classify_source_tier(url_or_domain: str) -> str:
    """Match the URL's host against the settings.BRAND_MENTIONS tier
    domain lists.

    Owned properties (Bajaj family sites, our own social pages,
    our own app-store listings) are tagged as ``OWNED`` rather than
    excluded — operators need to see the FULL set of pages Google
    surfaces for the brand query, including our own. The dashboard
    can filter ``OWNED`` out client-side.

    For non-owned URLs the function falls through to the news /
    forum / review / aggregator / regulatory / blog tiers based on
    the env-driven mapping. Anything unmatched is ``OTHER``.
    """
    if not url_or_domain:
        return MentionSourceTier.OTHER
    if "://" in url_or_domain:
        host = domain_of(url_or_domain)
        url = url_or_domain
    else:
        host = url_or_domain.lower().lstrip("www.")
        url = ""
    if not host:
        return MentionSourceTier.OTHER

    # Own-property check first — overrides every other tier.
    if is_own_property(url, host):
        return MentionSourceTier.OWNED

    cfg = getattr(settings, "BRAND_MENTIONS", None) or {}
    tiers = cfg.get("tier_domains") or {}
    # Order matters — earlier tiers win on ambiguous matches.
    tier_order = [
        ("news_tier_1", MentionSourceTier.NEWS_TIER_1),
        ("news_tier_2", MentionSourceTier.NEWS_TIER_2),
        ("regulatory", MentionSourceTier.REGULATORY),
        ("review", MentionSourceTier.REVIEW),
        ("forum", MentionSourceTier.FORUM),
        ("aggregator", MentionSourceTier.AGGREGATOR),
        ("blog", MentionSourceTier.BLOG),
    ]
    for key, code in tier_order:
        for needle in tiers.get(key, []):
            if needle and needle.lower() in host:
                return code
    return MentionSourceTier.OTHER


# ── snippet extraction ────────────────────────────────────────────────


# ── own-property filter — keep third-party only ──────────────────────


_EXCLUDED_DOMAINS_CACHE: tuple[str, ...] | None = None
_EXCLUDED_PATTERNS_CACHE: list[re.Pattern[str]] | None = None


def _load_exclusions() -> tuple[tuple[str, ...], list[re.Pattern[str]]]:
    global _EXCLUDED_DOMAINS_CACHE, _EXCLUDED_PATTERNS_CACHE
    if _EXCLUDED_DOMAINS_CACHE is not None and _EXCLUDED_PATTERNS_CACHE is not None:
        return _EXCLUDED_DOMAINS_CACHE, _EXCLUDED_PATTERNS_CACHE
    cfg = getattr(settings, "BRAND_MENTIONS", None) or {}
    domains = tuple(
        d.strip().lower() for d in (cfg.get("excluded_domains") or [])
        if d and d.strip()
    )
    patterns = [
        re.compile(p, re.IGNORECASE)
        for p in (cfg.get("excluded_url_patterns") or [])
        if p
    ]
    _EXCLUDED_DOMAINS_CACHE = domains
    _EXCLUDED_PATTERNS_CACHE = patterns
    return domains, patterns


def is_own_property(url: str, source_domain: str = "") -> bool:
    """True if the URL points at a Bajaj-family property (our own
    corporate sites, sibling brand sites, or our own listings on
    third-party platforms like the Play Store / App Store).

    Two checks: domain substring match against ``excluded_domains``
    + URL regex match against ``excluded_url_patterns``. First hit
    wins — neither is exhaustive, both are loaded from settings so
    operators can extend without code changes.
    """
    if not url and not source_domain:
        return False
    excluded_domains, excluded_patterns = _load_exclusions()
    # Domain substring check first — cheap.
    host = source_domain.lower() if source_domain else domain_of(url)
    if host:
        for needle in excluded_domains:
            if needle and needle in host:
                return True
    # URL regex check second — for app-store-style listings of our
    # own app on third-party platforms.
    if url:
        for pat in excluded_patterns:
            if pat.search(url):
                return True
    return False


def extract_snippet(text: str, *, around_match: str | None = None, length: int = 500) -> str:
    """Slim a long body of text down to a UI-friendly snippet. If
    ``around_match`` is provided and found, centre the window on the
    match; otherwise take the first ``length`` chars. Collapses
    whitespace so the snippet renders cleanly in a table cell.
    """
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) <= length:
        return t
    if around_match:
        idx = t.lower().find(around_match.lower())
        if idx >= 0:
            half = length // 2
            start = max(0, idx - half)
            end = min(len(t), start + length)
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(t) else ""
            return prefix + t[start:end] + suffix
    return t[:length] + "…"
