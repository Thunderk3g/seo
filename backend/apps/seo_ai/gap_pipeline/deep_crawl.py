"""Stage 5: deep crawl of the top-10 competitors plus our own domain.

For each competitor (and our own site, so the comparison stage has an
apples-to-apples baseline):

1. Discover URLs via ``SitemapXMLAdapter`` (robots.txt → sitemap.xml →
   sitemap_index.xml). Falls back to crawling the homepage only if no
   sitemap exists.
2. Sample N pages from the discovered list (default 25, capped at
   ``GAP_PIPELINE_DEEP_CRAWL_PAGES``).
3. Run ``CompetitorCrawler.fetch_pages`` on the sample — re-uses the
   existing 7-day cache so back-to-back runs cost nothing.
4. Probe a few well-known commercial signal URLs (``/pricing``,
   ``/llms.txt``, ``/pricing.md``) so the comparison stage can flag
   gaps in machine-readable + commercial coverage.
5. Aggregate to a single profile JSON per competitor (page_count,
   avg_word_count, schema coverage, page types, etc.) and persist.

Profile shape — kept stable because the comparison stage and the
frontend both read it:

    {
      "page_count": int,
      "ok_count": int,
      "avg_word_count": float,
      "median_word_count": int,
      "avg_response_ms": int,
      "schema_pct": float,
      "h1_pct": float,
      "schema_types": [str, ...],
      "page_types": {"pricing": int, "comparison": int,
                       "calculator": int, "faq": int,
                       "blog": int, "other": int},
      "has_pricing_page": bool,
      "has_llms_txt": bool,
      "has_pricing_md": bool,
      "ai_citability_score": float (0-100),
      "sample_pages": [{"url", "title", "word_count", "has_schema"}, ...]
    }
"""
from __future__ import annotations

import logging
import re
import statistics
import time
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings

from ..adapters.competitor_crawler import CompetitorCrawler, CompetitorPage
from ..adapters.sitemap_xml import SitemapXMLAdapter
from ..models import GapCompetitor, GapDeepCrawl, GapPipelineRun

logger = logging.getLogger("seo.ai.gap_pipeline.deep_crawl")


_DEFAULT_PAGES_PER_DOMAIN = 25


# Page-type heuristics. URL-token first (cheap + reliable), then HTML
# signals as a fallback so blog templates with /resources/ paths still
# get caught.
_PAGE_TYPE_PATTERNS = [
    ("pricing", re.compile(r"/(pricing|plans|premium-calculator)/?", re.I)),
    ("comparison", re.compile(r"/(compare|vs|comparison)/?", re.I)),
    ("calculator", re.compile(r"/(calculator|estimate|tool)s?/?", re.I)),
    ("faq", re.compile(r"/(faq|faqs|help|support)/?", re.I)),
    ("blog", re.compile(r"/(blog|insights|articles|resources|guide)s?/?", re.I)),
]


def _classify_page(url: str, page: CompetitorPage) -> str:
    """Return one of pricing/comparison/calculator/faq/blog/other."""
    for label, pat in _PAGE_TYPE_PATTERNS:
        if pat.search(url):
            return label
    return "other"


def _ai_citability(page: CompetitorPage) -> float:
    """Heuristic AI-citability score (0-100) for one page.

    Rewards signals that AI search engines correlate with citation:
    schema present, a clear H1, healthy word count, fast response,
    explicit author/last-modified markers. This is a quick proxy of
    the more rigorous ``ContentExtractabilityAgent`` scoring — it's
    cheap so we can run it on every crawled page.
    """
    score = 0.0
    if page.status_code != 200:
        return 0.0
    if page.h1_texts:
        score += 15
    if 300 <= page.word_count <= 4000:
        score += 25
    elif page.word_count >= 4000:
        score += 15  # too long can hurt extractability
    if page.has_schema_org:
        score += 20
    if page.response_time_ms and page.response_time_ms < 1500:
        score += 10
    if page.last_modified:
        score += 5
    if page.h2_count >= 2:
        score += 10
    if page.image_alt_pct >= 70:
        score += 5
    if page.title_length and 30 <= page.title_length <= 65:
        score += 10
    return min(score, 100.0)


def _head_probe(url: str, *, timeout: int) -> bool:
    """HEAD/GET probe for a single URL — used to test ``/llms.txt``,
    ``/pricing``, etc. Returns True on any 2xx (or 3xx that resolves
    quickly without a body).
    """
    try:
        resp = requests.head(
            url,
            timeout=timeout,
            allow_redirects=True,
            verify=False,  # mirrors COMPETITOR_SSL_VERIFY=false in dev
            headers={
                "User-Agent": settings.COMPETITOR.get("user_agent", "")
            },
        )
        if 200 <= resp.status_code < 400:
            return True
        # Some servers 405 HEAD — re-try as GET (no body fetch).
        if resp.status_code == 405:
            resp = requests.get(
                url,
                timeout=timeout,
                stream=True,
                allow_redirects=True,
                verify=False,
                headers={"User-Agent": settings.COMPETITOR.get("user_agent", "")},
            )
            ok = 200 <= resp.status_code < 400
            resp.close()
            return ok
        return False
    except requests.RequestException:
        return False


def _build_profile(
    *, pages: list[CompetitorPage], commercial_signals: dict[str, bool]
) -> dict[str, Any]:
    """Aggregate per-page metrics into a single profile JSON."""
    ok_pages = [p for p in pages if p.status_code == 200]
    page_types: dict[str, int] = {
        "pricing": 0,
        "comparison": 0,
        "calculator": 0,
        "faq": 0,
        "blog": 0,
        "other": 0,
    }
    schema_types: set[str] = set()
    for p in ok_pages:
        page_types[_classify_page(p.url, p)] += 1
        for t in p.schema_types or []:
            if t:
                schema_types.add(str(t))

    word_counts = [p.word_count for p in ok_pages if p.word_count]
    response_times = [
        p.response_time_ms for p in ok_pages if p.response_time_ms
    ]
    citability_scores = [_ai_citability(p) for p in ok_pages]

    def _safe_mean(xs):
        return round(statistics.fmean(xs), 1) if xs else 0.0

    def _safe_median(xs):
        return int(statistics.median(xs)) if xs else 0

    schema_pct = (
        round(sum(1 for p in ok_pages if p.has_schema_org) / len(ok_pages) * 100, 1)
        if ok_pages
        else 0.0
    )
    h1_pct = (
        round(sum(1 for p in ok_pages if p.h1_texts) / len(ok_pages) * 100, 1)
        if ok_pages
        else 0.0
    )

    sample_pages = [
        {
            "url": p.url,
            "title": p.title,
            "word_count": p.word_count,
            "has_schema": p.has_schema_org,
            "page_type": _classify_page(p.url, p),
        }
        for p in ok_pages[:10]
    ]

    return {
        "page_count": len(pages),
        "ok_count": len(ok_pages),
        "avg_word_count": _safe_mean(word_counts),
        "median_word_count": _safe_median(word_counts),
        "avg_response_ms": int(_safe_mean(response_times)),
        "schema_pct": schema_pct,
        "h1_pct": h1_pct,
        "schema_types": sorted(schema_types)[:20],
        "page_types": page_types,
        "has_pricing_page": commercial_signals.get("pricing", False)
        or page_types["pricing"] > 0,
        "has_llms_txt": commercial_signals.get("llms_txt", False),
        "has_pricing_md": commercial_signals.get("pricing_md", False),
        "ai_citability_score": _safe_mean(citability_scores),
        "sample_pages": sample_pages,
    }


@dataclass
class _CrawlOutcome:
    sitemap_url_count: int
    pages_attempted: int
    pages_ok: int
    profile: dict[str, Any]
    error: str = ""


def _crawl_domain(
    *,
    domain: str,
    sitemap_adapter: SitemapXMLAdapter,
    crawler: CompetitorCrawler,
    pages_per_domain: int,
    timeout: int,
) -> _CrawlOutcome:
    """Discover → sample → fetch → profile one domain."""
    bare = re.sub(r"^https?://", "", domain).rstrip("/")
    bare = re.sub(r"^www\d?\.", "", bare).split("/")[0].lower()

    sitemap_summary = sitemap_adapter.discover(bare)
    # sitemap_summary.total_url_count is the *count* — to actually get
    # URLs we re-read the cache file and pull the first N <loc> values
    # from the visited sub-sitemaps. SitemapXMLAdapter doesn't expose
    # URLs directly (it was built only for counting), so we re-issue a
    # narrow request: pull the first page of the first sub-sitemap.
    sample_urls = _sample_urls_from_sitemap(
        sitemap_summary, bare, limit=pages_per_domain
    )
    if not sample_urls:
        # No sitemap → fall back to homepage only so we still capture
        # something (and the comparison can say "they have no sitemap").
        sample_urls = [f"https://{bare}/"]

    pages = crawler.fetch_pages(sample_urls)

    commercial_signals = {
        "pricing": _head_probe(f"https://{bare}/pricing", timeout=timeout),
        "llms_txt": _head_probe(f"https://{bare}/llms.txt", timeout=timeout),
        "pricing_md": _head_probe(f"https://{bare}/pricing.md", timeout=timeout),
    }

    profile = _build_profile(pages=pages, commercial_signals=commercial_signals)
    return _CrawlOutcome(
        sitemap_url_count=sitemap_summary.total_url_count,
        pages_attempted=len(pages),
        pages_ok=sum(1 for p in pages if p.status_code == 200),
        profile=profile,
        error=sitemap_summary.error or "",
    )


def _sample_urls_from_sitemap(
    summary, domain: str, *, limit: int
) -> list[str]:
    """Pull up to ``limit`` <loc> URLs from the first sub-sitemap.

    SitemapXMLAdapter was built only to *count* URLs (it doesn't keep
    them in memory or expose them on the summary). For sampling we
    fetch the first visited sub-sitemap directly and extract the first
    N <loc> values. If parsing fails or no sitemap was discovered, we
    return an empty list and the caller falls back to homepage-only.
    """
    import xml.etree.ElementTree as ET

    sitemap_urls = list(summary.sitemap_urls or [])
    if not sitemap_urls:
        return []
    user_agent = settings.COMPETITOR.get("user_agent", "")
    out: list[str] = []
    for sm_url in sitemap_urls[:3]:  # try first 3 sub-sitemaps if needed
        try:
            resp = requests.get(
                sm_url,
                timeout=15,
                verify=False,
                headers={
                    "User-Agent": user_agent,
                    "Accept": "application/xml, text/xml, */*",
                },
            )
            if resp.status_code != 200:
                continue
            body = resp.content
            # Tolerant parse — sitemap_xml.py also handles gz, but for
            # sampling we only attempt the plain XML path. Loss case:
            # gzipped sitemaps with no plain fallback (rare for the
            # vendors we'd crawl in insurance/finance) yield no sample.
            try:
                root = ET.fromstring(body)
            except ET.ParseError:
                continue
            ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            for url_el in root.iter(f"{ns}url"):
                loc = url_el.find(f"{ns}loc")
                if loc is not None and loc.text:
                    out.append(loc.text.strip())
                    if len(out) >= limit:
                        return out
            if out:
                return out
        except requests.RequestException as exc:
            logger.info(
                "deep_crawl: sitemap fetch %s failed: %s", sm_url, exc
            )
            continue
    return out


def execute(*, run: GapPipelineRun, domain: str) -> dict[str, Any]:
    """Run stage 5. Crawls top-10 competitors + our own domain."""
    competitors = list(
        GapCompetitor.objects.filter(run=run).order_by("rank")
    )
    pages_per_domain = int(
        getattr(settings, "SEO_AI", {}).get("gap_pipeline_pages_per_domain", _DEFAULT_PAGES_PER_DOMAIN)
        or _DEFAULT_PAGES_PER_DOMAIN
    )
    pages_per_domain = max(5, min(pages_per_domain, 50))

    crawler = CompetitorCrawler()
    sitemap_adapter = SitemapXMLAdapter()
    timeout = int(settings.COMPETITOR.get("timeout_sec", 15))

    GapDeepCrawl.objects.filter(run=run).delete()
    total_pages = 0

    # Crawl us first so the UI can render our profile in the same
    # panel even if the competitor loop times out partway through.
    try:
        ours = _crawl_domain(
            domain=domain,
            sitemap_adapter=sitemap_adapter,
            crawler=crawler,
            pages_per_domain=pages_per_domain,
            timeout=timeout,
        )
        GapDeepCrawl.objects.create(
            run=run,
            competitor=None,
            domain=re.sub(r"^www\d?\.", "", domain.lower()),
            is_us=True,
            sitemap_url_count=ours.sitemap_url_count,
            pages_attempted=ours.pages_attempted,
            pages_ok=ours.pages_ok,
            profile=ours.profile,
            error=ours.error,
        )
        total_pages += ours.pages_attempted
    except Exception as exc:  # noqa: BLE001 - stage must not crash run
        logger.warning("deep_crawl: our-side crawl failed: %s", exc)
        GapDeepCrawl.objects.create(
            run=run,
            competitor=None,
            domain=domain,
            is_us=True,
            error=f"{type(exc).__name__}: {exc}"[:1000],
        )

    for comp in competitors:
        try:
            outcome = _crawl_domain(
                domain=comp.domain,
                sitemap_adapter=sitemap_adapter,
                crawler=crawler,
                pages_per_domain=pages_per_domain,
                timeout=timeout,
            )
            GapDeepCrawl.objects.create(
                run=run,
                competitor=comp,
                domain=comp.domain,
                is_us=False,
                sitemap_url_count=outcome.sitemap_url_count,
                pages_attempted=outcome.pages_attempted,
                pages_ok=outcome.pages_ok,
                profile=outcome.profile,
                error=outcome.error,
            )
            total_pages += outcome.pages_attempted
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "deep_crawl: %s crawl failed: %s", comp.domain, exc
            )
            GapDeepCrawl.objects.create(
                run=run,
                competitor=comp,
                domain=comp.domain,
                is_us=False,
                error=f"{type(exc).__name__}: {exc}"[:1000],
            )

    run.deep_crawl_pages = total_pages
    run.save(update_fields=["deep_crawl_pages"])

    return {
        "status": "ok",
        "domains_crawled": len(competitors) + 1,
        "pages_crawled": total_pages,
        "pages_per_domain": pages_per_domain,
    }
