"""In-house content-keyword extraction.

Counterpart to the Semrush "ranking keywords" view. Reads a competitor's
crawled CrawlerPageResult rows, concatenates title + meta + headings +
body excerpts, and runs an n-gram TF-IDF to surface what the competitor
*writes about* (vs. what they *rank for*, which only Semrush can tell us).

Result shape::

    [
      {
        "keyword":   "term insurance calculator",
        "score":     0.482,
        "page_count": 17,
        "sample_pages": [{"url": "...", "title": "..."}, ...],
      },
      ...
    ]

Stopwords are sklearn's English list plus a small insurance-domain stop
list (``insurance``, ``policy``, ``plan``, etc.) so the surfaced terms
discriminate between competitors rather than restate the obvious vertical.

Pure function (no Django imports). Caller resolves which snapshot rows
to feed in.
"""
from __future__ import annotations

from typing import Iterable


# Vertical-noise terms that are present on nearly every insurance page
# and dominate any naive TF-IDF if we don't strip them. Keep tight —
# anything genuinely discriminating (e.g. ``ulip``, ``riders``, ``annuity``)
# should NOT be in this list because operators want to spot those topics.
DOMAIN_STOPWORDS: frozenset[str] = frozenset(
    {
        "insurance", "insurer", "insurers",
        "policy", "policies",
        "plan", "plans",
        "online", "india", "indian",
        "company", "companies",
        "buy", "buying", "purchase", "purchasing",
        "today", "now", "best", "top", "compare", "comparison",
        "read", "more", "click", "here", "view", "see",
        "details", "detail", "page", "pages", "site", "website",
        "year", "years", "month", "months", "day", "days",
        "rs", "inr", "lakh", "lakhs", "crore", "crores",
    },
)


def _bag_of_text(row: dict) -> str:
    """Concatenate the high-signal text fields of one CrawlerPageResult-
    shaped dict into a single string for TF-IDF tokenization. Body text
    is capped to ~1000 words so the long-tail body content doesn't drown
    out the title/headings (which are stronger signals)."""
    pieces: list[str] = []
    title = (row.get("title") or "").strip()
    if title:
        pieces.append(title)
    meta = (row.get("meta_description") or "").strip()
    if meta:
        pieces.append(meta)
    headings = row.get("headings_json") or []
    for h in headings:
        if not isinstance(h, dict):
            continue
        lvl = int(h.get("level") or 0)
        if lvl in (1, 2, 3):
            t = (h.get("text") or "").strip()
            if t:
                pieces.append(t)
    body = (row.get("body_text") or "").strip()
    if body:
        # First ~1000 whitespace-tokens (cheap word-cap; doesn't have to
        # be linguistic words for TF-IDF).
        pieces.append(" ".join(body.split()[:1000]))
    return " ".join(pieces)


def extract_content_keywords(
    rows: Iterable[dict],
    *,
    top_k: int = 50,
    ngram_range: tuple[int, int] = (1, 2),
    min_df: int = 2,
    max_df: float = 0.6,
) -> list[dict]:
    """Run TF-IDF over the supplied rows and return the top ``top_k``
    terms with their score + the URLs they appear on.

    ``rows`` is any iterable of dicts shaped like CrawlerPageResult
    (we read ``url``, ``title``, ``meta_description``, ``headings_json``,
    ``body_text``). The function is pure; the caller decides what
    snapshot (or set of snapshots, for subdomain rollups) to pass in.
    """
    # Materialize once so we can iterate twice (TF-IDF + per-keyword
    # sample-page lookup).
    materialized: list[dict] = list(rows)
    if not materialized:
        return []

    docs: list[str] = []
    url_index: list[tuple[str, str]] = []  # (url, title) parallel to docs
    for row in materialized:
        text = _bag_of_text(row)
        if not text:
            continue
        docs.append(text)
        url_index.append(
            ((row.get("url") or "").strip(), (row.get("title") or "").strip()),
        )

    if not docs:
        return []

    # min_df guards against single-page noise; cap min_df at len(docs)-1
    # so tiny crawls (e.g. 3-page competitor snapshot) still yield results.
    effective_min_df = min(min_df, max(1, len(docs) - 1))

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.feature_extraction import _stop_words as _sw_module
    except ImportError as exc:  # noqa: BLE001
        # sklearn is a transitive dep via sentence-transformers; if the
        # import path changes upstream we degrade to "no keywords" rather
        # than 500-ing the dashboard tile.
        raise RuntimeError(
            f"sklearn TfidfVectorizer unavailable: {exc}",
        ) from exc

    stop_words = set(_sw_module.ENGLISH_STOP_WORDS) | DOMAIN_STOPWORDS

    vec = TfidfVectorizer(
        ngram_range=ngram_range,
        stop_words=list(stop_words),
        lowercase=True,
        min_df=effective_min_df,
        max_df=max_df,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z]{1,}\b",
    )
    try:
        tfidf = vec.fit_transform(docs)
    except ValueError:
        # No terms survived stopword + min_df filtering. Common for very
        # small / very noisy snapshots.
        return []

    # Sum TF-IDF across documents so the score reflects "how strongly
    # this term recurs across the corpus", not just one big-body page.
    summed = tfidf.sum(axis=0).A1
    terms = vec.get_feature_names_out()

    # Document-frequency per term (how many pages it appears on) — for
    # the page_count surfacing.
    binarized = (tfidf > 0).astype(int)
    page_counts = binarized.sum(axis=0).A1

    # For sample-pages: pre-index docs by term presence. Cheap because we
    # only iterate the top_k rows of the matrix at the end, not full N×T.
    ranked = sorted(
        zip(terms, summed.tolist(), page_counts.tolist()),
        key=lambda x: -x[1],
    )[:top_k]

    # Build sample-page lookup only for the selected terms (top_k * 3
    # URLs at most). Iterate the sparse matrix column-wise via tocsc().
    csc = tfidf.tocsc()
    term_index = {t: i for i, t in enumerate(terms)}
    out: list[dict] = []
    for term, score, page_count in ranked:
        col = csc.getcol(term_index[term])
        # Indices of non-zero rows = doc indices that mention this term.
        rows_with_term = col.nonzero()[0].tolist()
        # Sort sample pages by TF-IDF strength on this term, descending.
        rows_with_term.sort(key=lambda i: -col[i, 0])
        sample_pages = []
        for ri in rows_with_term[:3]:
            url, title = url_index[ri]
            if not url:
                continue
            sample_pages.append({"url": url, "title": title})
        out.append({
            "keyword": term,
            "score": round(float(score), 4),
            "page_count": int(page_count),
            "sample_pages": sample_pages,
        })
    return out
