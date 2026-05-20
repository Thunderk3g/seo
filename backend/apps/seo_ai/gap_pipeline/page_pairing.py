"""Match an AEM page to the topically-closest competitor sample page.

Pure-string matcher — **no LLM, no embeddings, no API calls.** Used by
the content-comparison view to pair each of our authored pages (from
``SitemapAEMAdapter``) against the best candidate in every competitor's
crawled sample (``GapDeepCrawl.profile.sample_pages``).

Scoring is a weighted blend of two cheap signals:

  * **URL slug Jaccard** (60 %) — split the URL path on ``/-_.`` plus
    suffix-strip, drop noise tokens, take the Jaccard of the two
    token sets. Slug overlap is the single strongest signal that two
    pages are about the same product/topic (URL design tends to mirror
    page intent across rivals — ``/term-insurance`` everywhere).

  * **Title token cosine** (40 %) — tokenise titles into lowercase
    words, drop stopwords and ≤2-char tokens, build bag-of-words term
    frequencies, take cosine similarity. Catches the case where slugs
    diverge (``/protect-your-family`` vs ``/term-insurance``) but
    titles still rhyme (``"Term Insurance Plans — Buy ..."``).

Combined score is in ``[0.0, 1.0]``; the caller decides whether to
treat anything below e.g. 0.15 as "no good match". The function does
NOT filter — it returns *every* candidate ranked, so the UI can show
the best match plus the next two as alternatives.

The matcher is intentionally stateless and re-callable per AEM page —
the candidate list per competitor is small (≤25) so brute-force scoring
across all candidates is fine. No caching needed.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse


# Tokens with no semantic value that show up in nearly every URL —
# stripping them prevents an inflated Jaccard score from shared
# boilerplate ("html" or "en" matching across two unrelated pages).
_URL_NOISE = frozenset({
    "html", "htm", "index", "home", "default", "page",
    "en", "in", "us", "uk", "www", "content", "balic-web", "p",
    "view", "main", "amp",
})

# English stopwords + insurance-page filler that shows up on most
# competitor titles ("buy", "compare", "best", "online"). Removing them
# means the title cosine compares the *topic* terms, not the marketing
# copy that wraps every page.
_TITLE_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "of", "for", "in",
    "on", "with", "to", "from", "by", "at", "as", "is", "are", "was",
    "were", "be", "been", "being", "this", "that", "these", "those",
    "it", "its", "what", "how", "why", "when", "your", "you", "our",
    "we", "us", "my", "me",
    # filler that bloats insurance-page titles
    "buy", "online", "best", "top", "compare", "comparison", "vs",
    "plan", "plans", "policy", "policies", "india", "bajaj",
    "axismaxlife", "hdfc", "sbi", "icici", "lic", "max", "life",
})

_URL_SPLIT = re.compile(r"[/\-_.]+")
_WORD = re.compile(r"[a-z0-9]+")

_SLUG_WEIGHT = 0.6
_TITLE_WEIGHT = 0.4


@dataclass(frozen=True)
class Match:
    """One competitor candidate scored against an AEM page."""

    score: float                          # 0.0 .. 1.0, weighted blend
    slug_jaccard: float                   # raw slug Jaccard
    title_cosine: float                   # raw title cosine
    reason: str                           # human-readable explanation
    candidate: dict                       # the sample_pages[] entry itself


def slug_tokens(url: str) -> set[str]:
    """Strip a URL down to a set of meaningful path tokens.

    Drops scheme, host, query, fragment, noise words (html, en, www…)
    and trailing ``.html``. Single-char tokens are kept only when
    they're numeric (e.g., ``/2025/`` may be load-bearing).
    """
    if not url:
        return set()
    try:
        parsed = urlparse(url)
        path = parsed.path or ""
    except (ValueError, AttributeError):
        path = url
    path = path.lower().rstrip("/")
    if path.endswith(".html") or path.endswith(".htm"):
        path = path.rsplit(".", 1)[0]
    raw = [t for t in _URL_SPLIT.split(path) if t]
    out: set[str] = set()
    for tok in raw:
        if tok in _URL_NOISE:
            continue
        if len(tok) == 1 and not tok.isdigit():
            continue
        out.add(tok)
    return out


def title_tokens(title: str) -> Counter[str]:
    """Lowercase + stopword-strip a title into a bag-of-words counter."""
    if not title:
        return Counter()
    raw = _WORD.findall(title.lower())
    return Counter(
        t for t in raw if len(t) > 2 and t not in _TITLE_STOPWORDS
    )


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union) if union else 0.0


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def score_pair(
    *,
    our_url: str,
    our_title: str,
    their_url: str,
    their_title: str,
) -> Match:
    """Score one pair. Caller fills in the ``candidate`` field after."""
    a_slug = slug_tokens(our_url)
    b_slug = slug_tokens(their_url)
    a_title = title_tokens(our_title)
    b_title = title_tokens(their_title)

    slug = _jaccard(a_slug, b_slug)
    title = _cosine(a_title, b_title)
    blended = _SLUG_WEIGHT * slug + _TITLE_WEIGHT * title

    overlap = sorted(a_slug & b_slug)[:6]
    if overlap:
        reason = f"slug overlap: {', '.join(overlap)} · title cosine {title:.2f}"
    else:
        reason = f"no slug overlap · title cosine {title:.2f}"

    return Match(
        score=round(blended, 4),
        slug_jaccard=round(slug, 4),
        title_cosine=round(title, 4),
        reason=reason,
        candidate={},  # filled in by the caller; kept here for shape parity
    )


def match_aem_to_candidates(
    *,
    our_url: str,
    our_title: str,
    candidates: Iterable[dict],
) -> list[Match]:
    """Score every candidate against one AEM page; return sorted desc.

    ``candidates`` must be the dict shape used inside
    ``GapDeepCrawl.profile.sample_pages`` — each entry needs ``url`` and
    ``title`` at minimum.
    """
    out: list[Match] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        url = cand.get("url") or ""
        if not url:
            continue
        m = score_pair(
            our_url=our_url,
            our_title=our_title,
            their_url=url,
            their_title=cand.get("title") or "",
        )
        # Re-attach the candidate dict (frozen dataclass forces a copy).
        out.append(
            Match(
                score=m.score,
                slug_jaccard=m.slug_jaccard,
                title_cosine=m.title_cosine,
                reason=m.reason,
                candidate=cand,
            )
        )
    out.sort(key=lambda m: m.score, reverse=True)
    return out


def best_match_per_competitor(
    *,
    our_url: str,
    our_title: str,
    deep_crawls: Iterable[tuple[str, list[dict]]],
) -> list[tuple[str, Match | None]]:
    """For each competitor's sample pool, return the single best match.

    ``deep_crawls`` is an iterable of ``(competitor_domain, sample_pages)``
    pairs. The result preserves input order. A competitor whose pool is
    empty (or who has no usable candidate) yields ``(domain, None)`` so
    the UI can render a "no match" row instead of silently dropping it.
    """
    result: list[tuple[str, Match | None]] = []
    for domain, candidates in deep_crawls:
        ranked = match_aem_to_candidates(
            our_url=our_url,
            our_title=our_title,
            candidates=candidates,
        )
        result.append((domain, ranked[0] if ranked else None))
    return result
