"""LLM-driven page clustering for a single competitor.

Counterpart to the rule-based ``content/clusters.py`` (which buckets
pages by URL-pattern classifier) and the embeddings-based
``page_clusters_view`` (which clusters chunks of one page via KMeans on
sentence-transformer vectors). This service does something different:
it asks the LLM to group a competitor's PAGES into topical clusters,
giving each cluster a meaningful name plus the supporting evidence
(which pages, where the data came from, when it was crawled).

Why LLM instead of sentence-transformers:
* The taxonomy is operator-readable ("Term Insurance Products",
  "Calculator Tools", "Customer Service") without a post-hoc TF-IDF
  labeling pass.
* Hard-to-encode signals — site-section conventions, customer-service
  URL patterns, branded product names — are easier for an LLM that's
  seen Indian insurance sites than for MiniLM trained on Wikipedia.
* The output is small (5-10 clusters × ~20 page indices each), well
  inside Groq's 8k TPM budget.

The endpoint surfaces, per cluster: the LLM-derived name, the pages in
it (URL, title, word count), and **per-page data-source metadata**
(which snapshot wrote the row, when it was crawled, sitemap vs walk vs
ad-hoc, db cache vs live refresh). The frontend renders that
provenance as a small badge under each page so the operator can see
"this cluster comes from the daily sitemap walk on 2026-05-26".
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("seo.ai.competitor_clustering")


# ── dataclasses ──────────────────────────────────────────────────────


@dataclass
class PageDataSource:
    """Where a page came from, for UI provenance badges."""

    snapshot_id: str
    snapshot_kind: str        # 'competitor' | 'adhoc' | 'bajaj'
    snapshot_engine: str      # 'scrapy_competitor' | 'legacy' | 'scrapy'
    snapshot_started_at: str  # ISO
    crawl_mode: str = ""      # 'sitemap' | 'walk' | 'urls' | '' (unknown)


@dataclass
class ClusterPage:
    url: str
    title: str
    word_count: int
    page_type: str
    source: PageDataSource


@dataclass
class PageCluster:
    cluster_id: int
    name: str
    rationale: str
    pages: list[ClusterPage] = field(default_factory=list)


@dataclass
class CompetitorPageStructure:
    domain: str
    parent_domain: str
    total_pages_sampled: int
    total_pages_in_corpus: int
    clusters: list[PageCluster]
    model_used: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cached: bool
    cached_at: str = ""
    error: str = ""


# ── disk cache ───────────────────────────────────────────────────────


def _cache_dir() -> Path:
    """Sibling of the existing _semrush_cache / _psi_cache directories."""
    from django.conf import settings as dj_settings

    seo_ai_cfg = getattr(dj_settings, "SEO_AI", None) or {}
    data_dir = Path(seo_ai_cfg.get("data_dir") or "backend/data")
    path = data_dir / "_competitor_cluster_cache"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def _cache_path(domain: str, max_pages: int) -> Path:
    safe = "".join(c if c.isalnum() else "_" for c in (domain or ""))
    return _cache_dir() / f"{safe}__{max_pages}.json"


def _cache_read(domain: str, max_pages: int, ttl_seconds: int) -> dict | None:
    p = _cache_path(domain, max_pages)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            envelope = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    written = envelope.get("written_at_unix") or 0
    if time.time() - written > ttl_seconds:
        return None
    return envelope.get("data")


def _cache_write(domain: str, max_pages: int, data: dict) -> None:
    p = _cache_path(domain, max_pages)
    try:
        with p.open("w", encoding="utf-8") as f:
            json.dump(
                {"written_at_unix": time.time(), "data": data}, f,
            )
    except OSError as exc:  # noqa: BLE001
        logger.info("competitor cluster cache write failed: %s", exc)


# ── page selection ───────────────────────────────────────────────────


def _select_pages_for_clustering(parent_domain: str, max_pages: int):
    """Pull the most informative CrawlerPageResult rows for a brand.

    Strategy: aggregate every status=200 row under the parent_domain
    (all subdomains too), rank by word_count descending, take the top
    ``max_pages``. We trust word_count as a "page has real content"
    proxy because the daily sitemap walk catches lots of low-content
    boilerplate that would just blur the clusters.
    """
    from apps.crawler.models import CrawlSnapshot, CrawlerPageResult

    qs = (
        CrawlerPageResult.objects
        .filter(
            snapshot__kind=CrawlSnapshot.Kind.COMPETITOR,
            snapshot__parent_domain=parent_domain,
            status_code="200",
        )
        .exclude(title="")
        .select_related("snapshot")
        .only(
            "url", "title", "word_count", "page_type",
            "snapshot_id", "snapshot__kind", "snapshot__engine",
            "snapshot__started_at", "snapshot__notes",
            "snapshot__config_snapshot",
        )
    )

    # De-dup by URL (keep the row from the freshest snapshot per URL).
    by_url: dict[str, Any] = {}
    for row in qs.iterator():
        existing = by_url.get(row.url)
        if existing is None:
            by_url[row.url] = row
            continue
        # Prefer the row from the more recent snapshot.
        if (row.snapshot.started_at or 0) > (existing.snapshot.started_at or 0):
            by_url[row.url] = row

    ordered = sorted(
        by_url.values(), key=lambda r: -(r.word_count or 0),
    )
    total_in_corpus = len(ordered)
    return ordered[:max_pages], total_in_corpus


def _row_to_source(row) -> PageDataSource:
    """Project the snapshot context behind a page into the data-source dataclass."""
    snap = row.snapshot
    cfg = (snap.config_snapshot or {}) if hasattr(snap, "config_snapshot") else {}
    crawl_mode = ""
    # The walk_competitor_task writes the resolved mode back into the
    # snapshot's notes / config_snapshot in newer code paths; older rows
    # have nothing — we degrade to empty string.
    if isinstance(cfg, dict):
        crawl_mode = (cfg.get("mode") or cfg.get("crawl_mode") or "")[:32]
    if not crawl_mode and snap.notes:
        # Heuristic: the seed-mode fallback log line lands in notes too.
        notes = snap.notes.lower()
        if "sitemap" in notes:
            crawl_mode = "sitemap"
        elif "walk" in notes:
            crawl_mode = "walk"
    return PageDataSource(
        snapshot_id=str(snap.id),
        snapshot_kind=snap.kind,
        snapshot_engine=snap.engine,
        snapshot_started_at=(
            snap.started_at.isoformat() if snap.started_at else ""
        ),
        crawl_mode=crawl_mode,
    )


# ── LLM-driven clustering ────────────────────────────────────────────


_SYSTEM_PROMPT = """You are organizing an Indian life-insurance website's
pages into topical clusters for SEO analysis. You will receive an array
of pages, each with {id, path, title}. Group every page into a named
topical cluster.

Cluster names should describe what the section is about — examples:
- "Term Insurance Products"
- "ULIP / Investment Plans"
- "Retirement & Pension Plans"
- "Tax-Saving Plans"
- "Premium / Tax Calculators"
- "Customer Service / Manage Policy"
- "Claims & Forms"
- "Blog / Knowledge Guides"
- "Investor Relations & Disclosures"
- "Corporate / Careers / About"
- "Group / Employer Insurance"
- "Home / Brand Landing"

CRITICAL RULES:
1. EVERY id from the input MUST appear in exactly ONE cluster's
   page_ids list. Do not skip any page.
2. Produce 5–10 clusters. If a single topic dominates, split it
   (e.g. "Term Insurance — Plans" vs "Term Insurance — FAQs").
3. page_ids MUST be a JSON ARRAY of separate INTEGERS — one element
   per id. Each integer is comma-separated. DO NOT concatenate ids
   into one number.

   CORRECT:   "page_ids": [3, 7, 12, 25]
   WRONG:     "page_ids": [371225]
   WRONG:     "page_ids": "3,7,12,25"

4. Return ONLY this JSON object:

{
  "clusters": [
    {"name": "<2-5 words>", "rationale": "<one short sentence>", "page_ids": [3, 7, 12]},
    {"name": "<2-5 words>", "rationale": "<one short sentence>", "page_ids": [0, 1, 4, 25]}
  ]
}

No prose, no markdown fences around the JSON.
""".strip()


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _call_llm_to_cluster(pages: list, provider=None) -> tuple[dict, dict]:
    """Send the page list to the LLM and parse the clusters JSON.

    Returns ``(clusters_dict, telemetry)`` where telemetry has
    ``{model, tokens_in, tokens_out, cost_usd}``.
    """
    from ..llm import get_provider
    provider = provider or get_provider()

    items = []
    for idx, row in enumerate(pages):
        items.append({
            "id": idx,
            "path": urlparse(row.url).path or row.url,
            "title": _truncate(row.title or "", 140),
        })

    user_payload = {
        "domain_pages": items,
        "page_count": len(items),
    }
    user_content = (
        "Cluster the following competitor pages by topic. Every page "
        "id must end up in exactly one cluster.\n\n<facts>\n```json\n"
        + json.dumps(user_payload, default=str)
        + "\n```\n</facts>"
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    resp = provider.complete(
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    text = (resp.content or "").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    parsed = json.loads(text)
    telemetry = {
        "model": getattr(provider, "model", "") or "",
        "tokens_in": resp.tokens_in,
        "tokens_out": resp.tokens_out,
        "cost_usd": resp.cost_usd,
    }
    return parsed, telemetry


# ── public entry point ──────────────────────────────────────────────


def build_competitor_page_structure(
    *,
    domain: str,
    max_pages: int = 60,
    cache_ttl_seconds: int = 24 * 3600,
    force_refresh: bool = False,
) -> CompetitorPageStructure:
    """Cluster a competitor's pages with the LLM and return the result.

    ``domain`` is the operator's input — we normalise it to the
    registrable apex via ``apps.crawler.util.host.apex`` so a passed
    subdomain like 'auth.hdfclife.com' still finds the parent brand.
    Cached on disk for ``cache_ttl_seconds`` (24 h default); the cache
    key is ``(parent_domain, max_pages)``.
    """
    from apps.crawler.util.host import apex

    parent = apex(domain) or domain.lower()

    if not force_refresh:
        cached = _cache_read(parent, max_pages, cache_ttl_seconds)
        if cached is not None:
            cached["cached"] = True
            cached["domain"] = domain
            return _from_dict(cached)

    pages, total_in_corpus = _select_pages_for_clustering(parent, max_pages)
    if not pages:
        return CompetitorPageStructure(
            domain=domain,
            parent_domain=parent,
            total_pages_sampled=0,
            total_pages_in_corpus=0,
            clusters=[],
            model_used="",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            cached=False,
            error=(
                "no competitor pages found for this brand — run the "
                "competitor walk first"
            ),
        )

    try:
        parsed, telemetry = _call_llm_to_cluster(pages)
    except Exception as exc:  # noqa: BLE001 — surface all failures
        logger.exception("competitor cluster LLM call failed for %s", parent)
        return CompetitorPageStructure(
            domain=domain,
            parent_domain=parent,
            total_pages_sampled=len(pages),
            total_pages_in_corpus=total_in_corpus,
            clusters=[],
            model_used="",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            cached=False,
            error=f"LLM call failed: {exc}",
        )

    clusters_raw = parsed.get("clusters") or []
    clusters: list[PageCluster] = []
    seen_ids: set[int] = set()
    n_pages = len(pages)
    for i, c in enumerate(clusters_raw):
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or f"Cluster {i+1}")[:80]
        rationale = str(c.get("rationale") or "")[:240]
        raw_ids = c.get("page_ids") or []
        ids: list[int] = []
        for raw_id in raw_ids:
            try:
                idx = int(raw_id)
            except (TypeError, ValueError):
                # Strings of the form "3,7,12" or "3 7 12" — split.
                if isinstance(raw_id, str):
                    for token in raw_id.replace(",", " ").split():
                        try:
                            t = int(token)
                            if 0 <= t < n_pages and t not in seen_ids:
                                ids.append(t)
                                seen_ids.add(t)
                        except (TypeError, ValueError):
                            continue
                continue
            if 0 <= idx < n_pages:
                if idx not in seen_ids:
                    ids.append(idx)
                    seen_ids.add(idx)
                continue
            # Out-of-range integer — the model probably concatenated
            # ids ("371225" instead of "[3, 7, 12, 25]"). Try greedy
            # split on 1- and 2-digit prefixes against the unassigned
            # id set. This is a documented gpt-oss-class behavior we
            # also work around in critic.py.
            digits = str(idx)
            cursor = 0
            while cursor < len(digits):
                matched = False
                for take in (2, 1):
                    if cursor + take > len(digits):
                        continue
                    candidate = int(digits[cursor : cursor + take])
                    if (
                        0 <= candidate < n_pages
                        and candidate not in seen_ids
                    ):
                        ids.append(candidate)
                        seen_ids.add(candidate)
                        cursor += take
                        matched = True
                        break
                if not matched:
                    cursor += 1  # skip stray digit
        if not ids:
            continue
        cluster_pages: list[ClusterPage] = []
        for idx in ids:
            row = pages[idx]
            cluster_pages.append(ClusterPage(
                url=row.url,
                title=row.title or "",
                word_count=int(row.word_count or 0),
                page_type=row.page_type or "",
                source=_row_to_source(row),
            ))
        clusters.append(PageCluster(
            cluster_id=i,
            name=name,
            rationale=rationale,
            pages=cluster_pages,
        ))

    # Catch-all: any page IDs the model dropped or mis-tagged go into a
    # "Misc / Uncategorised" bucket so we never lose pages silently.
    unassigned = [
        idx for idx in range(len(pages)) if idx not in seen_ids
    ]
    if unassigned:
        clusters.append(PageCluster(
            cluster_id=len(clusters),
            name="Misc / Uncategorised",
            rationale=(
                "Pages the LLM didn't cluster — included so the corpus "
                "isn't truncated."
            ),
            pages=[
                ClusterPage(
                    url=pages[idx].url,
                    title=pages[idx].title or "",
                    word_count=int(pages[idx].word_count or 0),
                    page_type=pages[idx].page_type or "",
                    source=_row_to_source(pages[idx]),
                )
                for idx in unassigned
            ],
        ))

    result = CompetitorPageStructure(
        domain=domain,
        parent_domain=parent,
        total_pages_sampled=len(pages),
        total_pages_in_corpus=total_in_corpus,
        clusters=clusters,
        model_used=telemetry["model"],
        tokens_in=telemetry["tokens_in"],
        tokens_out=telemetry["tokens_out"],
        cost_usd=telemetry["cost_usd"],
        cached=False,
    )

    payload = _to_dict(result)
    _cache_write(parent, max_pages, payload)
    return result


def _to_dict(r: CompetitorPageStructure) -> dict:
    return {
        "domain": r.domain,
        "parent_domain": r.parent_domain,
        "total_pages_sampled": r.total_pages_sampled,
        "total_pages_in_corpus": r.total_pages_in_corpus,
        "clusters": [
            {
                "cluster_id": c.cluster_id,
                "name": c.name,
                "rationale": c.rationale,
                "pages": [
                    {
                        "url": p.url,
                        "title": p.title,
                        "word_count": p.word_count,
                        "page_type": p.page_type,
                        "source": asdict(p.source),
                    }
                    for p in c.pages
                ],
            }
            for c in r.clusters
        ],
        "model_used": r.model_used,
        "tokens_in": r.tokens_in,
        "tokens_out": r.tokens_out,
        "cost_usd": r.cost_usd,
        "cached": r.cached,
        "cached_at": r.cached_at,
        "error": r.error,
    }


def _from_dict(d: dict) -> CompetitorPageStructure:
    clusters: list[PageCluster] = []
    for c in d.get("clusters") or []:
        pages = [
            ClusterPage(
                url=p.get("url", ""),
                title=p.get("title", ""),
                word_count=int(p.get("word_count") or 0),
                page_type=p.get("page_type", ""),
                source=PageDataSource(**(p.get("source") or {})),
            )
            for p in (c.get("pages") or [])
        ]
        clusters.append(PageCluster(
            cluster_id=int(c.get("cluster_id") or 0),
            name=str(c.get("name") or ""),
            rationale=str(c.get("rationale") or ""),
            pages=pages,
        ))
    return CompetitorPageStructure(
        domain=str(d.get("domain") or ""),
        parent_domain=str(d.get("parent_domain") or ""),
        total_pages_sampled=int(d.get("total_pages_sampled") or 0),
        total_pages_in_corpus=int(d.get("total_pages_in_corpus") or 0),
        clusters=clusters,
        model_used=str(d.get("model_used") or ""),
        tokens_in=int(d.get("tokens_in") or 0),
        tokens_out=int(d.get("tokens_out") or 0),
        cost_usd=float(d.get("cost_usd") or 0.0),
        cached=bool(d.get("cached")),
        cached_at=str(d.get("cached_at") or ""),
        error=str(d.get("error") or ""),
    )
