"""Phase 4 detector expansion (~30 new IssueDefs across 5 categories).

Reuses the catalog.IssueDef shape from Phase 1 — these are appended to
ALL_ISSUES via catalog.py. Every detector operates on the existing
crawl_results.csv schema (no new crawler instrumentation needed). The
heavier "hreflang matrix validation / security headers / Schema.org
validation" detectors planned in the roadmap need new crawler fields
first; those land in a Phase 4.5 commit alongside engine changes.

Categories added here:

  * indexability_advanced  — index/sitemap cross-checks beyond Phase 1
  * performance_deep       — beyond raw response time
  * content_quality        — beyond word-count thresholds
  * url_hygiene            — case mixing, fragments, tracking-id pollution
  * crawl_health           — meta-checks on the crawl itself

Each detector returns the subset of rows the issue applies to. The
helper predicates (_is_ok, _to_int, etc.) are imported from
catalog.py to keep the rules consistent across Phase 1 and Phase 4
detector definitions.
"""
from __future__ import annotations

import re
from collections import Counter

from .catalog import (
    Category,
    IssueDef,
    Severity,
    _is_ok,
    _to_int,
)


# ── 1. INDEXABILITY_ADVANCED ──────────────────────────────────────────


def _detect_sitemap_url_not_crawled(rows: list[dict]) -> list[dict]:
    """In sitemap but crawler never returned 200. Either the URL is
    unreachable (the sitemap declares dead pages) or the crawler hit
    a server error. Both are sitemap-quality smells."""
    return [
        r for r in rows
        if (r.get("from_sitemap") or "0") == "1"
        and (r.get("status_code") or "") not in ("200", "")
    ]


def _detect_indexed_but_broken(rows: list[dict]) -> list[dict]:
    """Google indexed the URL but our crawler now sees non-200. Index
    bloat — Google will eventually drop this but until it does the
    SERP impression is wasted on a broken page."""
    return [
        r for r in rows
        if (r.get("indexed_status") or "") == "indexed"
        and (r.get("status_code") or "") not in ("200", "")
    ]


def _detect_notindexed_with_content(rows: list[dict]) -> list[dict]:
    """Page is healthy + content-rich but Google declined to index.
    Usually a canonical/duplicate issue or a quality flag — investigate."""
    return [
        r for r in rows
        if _is_ok(r)
        and (r.get("indexed_status") or "") == "not_indexed"
        and _to_int(r.get("word_count")) > 600
    ]


def _detect_excluded_with_content(rows: list[dict]) -> list[dict]:
    """Long-form OK pages flagged 'excluded' in GSC. Either canonical
    points elsewhere intentionally or the page is being suppressed
    erroneously. Either way: confirm before assuming it's correct."""
    return [
        r for r in rows
        if _is_ok(r)
        and (r.get("indexed_status") or "") == "excluded"
        and _to_int(r.get("word_count")) > 600
    ]


def _detect_external_subdomain(rows: list[dict]) -> list[dict]:
    """URL classified as 'external' but somehow ended up in our crawl.
    Indicates either a misconfigured allowed_domains list or a redirect
    chain crossing domains. Worth visibility either way."""
    return [r for r in rows if (r.get("subdomain") or "") == "external"]


def _detect_unknown_page_type(rows: list[dict]) -> list[dict]:
    """URL the page-type classifier couldn't categorise. Usually means
    the URL pattern is new and the classifier hasn't learned it yet —
    surface so the URL classifier rules can be extended."""
    return [
        r for r in rows
        if _is_ok(r) and (r.get("page_type") or "") in ("", "unknown")
    ]


# ── 2. PERFORMANCE_DEEP ───────────────────────────────────────────────


def _detect_p99_response(rows: list[dict]) -> list[dict]:
    """Pages above the 95th percentile response time for the crawl.
    These are the highest-leverage performance fixes — small URL
    count but each contributes disproportionately to median page-load
    perception."""
    ok_with_rt = [
        (r, _to_int(r.get("response_time_ms")))
        for r in rows
        if _is_ok(r) and _to_int(r.get("response_time_ms")) > 0
    ]
    if not ok_with_rt:
        return []
    ok_with_rt.sort(key=lambda x: x[1])
    cutoff_idx = int(len(ok_with_rt) * 0.95)
    return [r for r, _ in ok_with_rt[cutoff_idx:]]


def _detect_status_set_no_rt(rows: list[dict]) -> list[dict]:
    """Page has a status_code but response_time_ms is 0 — data-quality
    smell, usually a fetcher bug. Surface so we can investigate."""
    return [
        r for r in rows
        if (r.get("status_code") or "") not in ("", "0")
        and _to_int(r.get("response_time_ms")) == 0
    ]


def _detect_branch_slow(rows: list[dict]) -> list[dict]:
    """Branch locator pages over 5s — these are the highest-intent
    'find a Bajaj branch near me' pages; slow loads kill local SEO."""
    return [
        r for r in rows
        if (r.get("subdomain") or "") == "branch"
        and _is_ok(r)
        and _to_int(r.get("response_time_ms")) > 5000
    ]


# ── 3. CONTENT_QUALITY ────────────────────────────────────────────────


_URL_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _title_matches_url_slug(row: dict) -> bool:
    title = (row.get("title") or "").strip().lower()
    if not title:
        return False
    # Last path segment from URL minus .html, minus query.
    url = (row.get("url") or "").lower()
    seg = url.split("?", 1)[0].rstrip("/").split("/")[-1]
    seg = seg.rsplit(".", 1)[0]  # drop .html
    if not seg:
        return False
    title_norm = _URL_SLUG_RE.sub("-", title).strip("-")
    seg_norm = _URL_SLUG_RE.sub("-", seg).strip("-")
    return title_norm == seg_norm


def _detect_title_equals_url_slug(rows: list[dict]) -> list[dict]:
    """Title is identical to the URL slug — template default the
    author forgot to override. Common on auto-generated pages."""
    return [r for r in rows if _is_ok(r) and _title_matches_url_slug(r)]


def _detect_extreme_title_length(rows: list[dict]) -> list[dict]:
    """Title longer than 100 chars — beyond just 'too long' (70).
    These trigger heavy SERP truncation and indicate template bugs
    concatenating brand + category + page name + tagline."""
    return [
        r for r in rows
        if _is_ok(r) and len((r.get("title") or "").strip()) > 100
    ]


def _detect_product_page_thin(rows: list[dict]) -> list[dict]:
    """Product pages with < 500 words. Product pages must rank — they
    need depth + FAQs + structured data. Thin product pages lose
    every term-insurance / ULIP / savings-plan SERP."""
    return [
        r for r in rows
        if _is_ok(r)
        and (r.get("page_type") or "") == "product"
        and 0 < _to_int(r.get("word_count")) < 500
    ]


def _detect_calculator_no_calculator_in_title(rows: list[dict]) -> list[dict]:
    """Calculator-type pages without 'calculator' in the title miss
    the literal SERP intent. Users search for 'X calculator'; a page
    titled differently buries the match."""
    return [
        r for r in rows
        if _is_ok(r)
        and (r.get("page_type") or "") == "calculators"
        and "calculator" not in (r.get("title") or "").lower()
    ]


# ── 4. URL_HYGIENE ────────────────────────────────────────────────────


_TRACKING_PARAMS = re.compile(
    r"[?&](utm_[a-z]+|fbclid|gclid|mc_[a-z]+|igshid|msclkid|"
    r"_ga|_gl|wbraid|gbraid)="
    , re.IGNORECASE,
)


def _detect_uppercase_in_url(rows: list[dict]) -> list[dict]:
    """URL path contains uppercase letters. Causes duplicate-content
    risk (Google treats /Foo and /foo as separate URLs in some
    rendering paths) and looks unprofessional."""
    return [
        r for r in rows
        if any(c.isupper() for c in (r.get("url") or "").split("?", 1)[0].split("//", 1)[-1])
    ]


def _detect_legacy_index_php(rows: list[dict]) -> list[dict]:
    """Legacy WordPress pattern — `/path/index.php`. Should be
    rewritten to `/path/` for hygiene and to consolidate signals."""
    return [
        r for r in rows
        if "/index.php" in (r.get("url") or "").lower()
    ]


def _detect_url_with_fragment(rows: list[dict]) -> list[dict]:
    """URL has a `#fragment`. Google ignores fragments for indexing,
    so any internal link with a fragment is wasted link equity."""
    return [r for r in rows if "#" in (r.get("url") or "")]


def _detect_tracking_param_in_url(rows: list[dict]) -> list[dict]:
    """URL contains tracking parameters that should canonicalise.
    Pollution from links shared from analytics / email tools."""
    return [
        r for r in rows
        if _TRACKING_PARAMS.search(r.get("url") or "")
    ]


def _detect_trailing_slash_inconsistency(rows: list[dict]) -> list[dict]:
    """Pages where both /foo and /foo/ exist as 200 responses (same
    content under two URLs). Picks the second-seen variant for each
    pair so reports surface the dupes without doubling the list."""
    seen_paths: dict[str, str] = {}
    out: list[dict] = []
    for r in rows:
        if not _is_ok(r):
            continue
        url = (r.get("url") or "")
        if not url:
            continue
        # Normalize to identity-without-trailing-slash
        normalized = url.rstrip("/")
        if normalized in seen_paths and seen_paths[normalized] != url:
            out.append(r)
        else:
            seen_paths[normalized] = url
    return out


# ── 5. CRAWL_HEALTH ───────────────────────────────────────────────────


def _detect_status_200_with_error_type(rows: list[dict]) -> list[dict]:
    """Status code is 200 but error_type is set — soft-error condition
    the fetcher logged but the HTTP layer didn't reflect. Indicates a
    fetcher bug worth investigating."""
    return [
        r for r in rows
        if (r.get("status_code") or "") == "200"
        and (r.get("error_type") or "").strip()
    ]


def _detect_non_200_no_error_type(rows: list[dict]) -> list[dict]:
    """Status code is non-200 but error_type is blank — the audit
    can't classify what went wrong. Surface so we can extend the
    fetcher's error taxonomy."""
    return [
        r for r in rows
        if (r.get("status_code") or "") not in ("", "0", "200")
        and not (r.get("error_type") or "").strip()
    ]


def _detect_orphan_in_results_not_sitemap(rows: list[dict]) -> list[dict]:
    """Successful pages on www that aren't in the sitemap. Different
    from Phase 1's similarly-named check — that one counted ALL OK www
    pages missing from sitemap. This narrows to high-value pages
    (>1000 words) since those are the ones the operator most wants
    indexed via sitemap inclusion."""
    return [
        r for r in rows
        if _is_ok(r)
        and (r.get("subdomain") or "") == "www"
        and (r.get("from_sitemap") or "0") != "1"
        and _to_int(r.get("word_count")) >= 1000
    ]


def _detect_dup_title_within_subdomain(rows: list[dict]) -> list[dict]:
    """Duplicate titles SCOPED to a single subdomain. Tighter signal
    than Phase 1's site-wide duplicate-title detector — same title
    across www+branch is often legitimate (locator + product page);
    same title within `www` is almost always a template bug."""
    sub_to_titles: dict[str, Counter] = {}
    for r in rows:
        if not _is_ok(r):
            continue
        sub = (r.get("subdomain") or "")
        t = (r.get("title") or "").strip().lower()
        if not t or not sub:
            continue
        sub_to_titles.setdefault(sub, Counter())[t] += 1
    dup_pairs: set[tuple[str, str]] = set()
    for sub, counter in sub_to_titles.items():
        for t, n in counter.items():
            if n > 1:
                dup_pairs.add((sub, t))
    return [
        r for r in rows
        if _is_ok(r)
        and ((r.get("subdomain") or ""), (r.get("title") or "").strip().lower()) in dup_pairs
    ]


# ── catalog entries ────────────────────────────────────────────────────
#
# Appended to ALL_ISSUES in catalog.py via the helper at the bottom of
# this module. Order matches the categorical groupings above so the
# Issues UI renders them logically grouped.

PHASE_4_ISSUES: tuple[IssueDef, ...] = (
    # INDEXABILITY_ADVANCED
    IssueDef(
        slug="sitemap_url_not_crawled",
        title="Sitemap URL did not return 200",
        severity="error",
        category="indexability",
        why=(
            "URLs you declare in sitemap.xml should be canonical, "
            "live destinations. When the crawler hits one and gets a "
            "non-200, the sitemap is misleading both us and Google."
        ),
        how_to_fix=(
            "Either restore the URL, replace the sitemap entry with "
            "the live equivalent, or remove the entry. Audit sitemap "
            "freshness as part of the publish workflow."
        ),
        detector=_detect_sitemap_url_not_crawled,
    ),
    IssueDef(
        slug="indexed_but_broken",
        title="Page indexed by Google but now broken",
        severity="error",
        category="indexability",
        why=(
            "Google has the URL in its index and serves SERP "
            "impressions to it — but our crawler now sees non-200. "
            "Every impression to a broken page is a wasted ranking "
            "opportunity and a poor user experience."
        ),
        how_to_fix=(
            "Restore the page or 301-redirect to the closest live "
            "equivalent so the existing ranking + link equity migrates."
        ),
        detector=_detect_indexed_but_broken,
    ),
    IssueDef(
        slug="notindexed_with_content",
        title="Content-rich page not indexed by Google",
        severity="warning",
        category="indexability",
        why=(
            "Pages with substantial content (600+ words) that Google "
            "actively declines to index usually have a duplicate or "
            "quality issue. Worth investigating since the content is "
            "ready to rank."
        ),
        how_to_fix=(
            "Run URL Inspection in Search Console. If duplicate, set "
            "canonical. If low quality, expand with unique value. If "
            "intentionally suppressed, set noindex to stop the crawl-"
            "budget waste."
        ),
        detector=_detect_notindexed_with_content,
    ),
    IssueDef(
        slug="excluded_with_content",
        title="Content-rich page excluded by Google",
        severity="warning",
        category="indexability",
        why=(
            "Excluded long-form pages usually canonicalise to another "
            "URL. Verify the canonical target is intentional — if not, "
            "the page is bleeding ranking signals into the wrong URL."
        ),
        how_to_fix=(
            "Verify rel=canonical points where you expect. If wrong, "
            "fix the canonical or remove it so the page indexes "
            "independently."
        ),
        detector=_detect_excluded_with_content,
    ),
    IssueDef(
        slug="external_subdomain_in_crawl",
        title="External-classified URL inside crawl results",
        severity="notice",
        category="indexability",
        why=(
            "URL was classified 'external' but still ended up in the "
            "results — usually a redirect chain crossing domains or an "
            "allowed_domains misconfiguration."
        ),
        how_to_fix=(
            "Verify allowed_domains in the crawler config. Audit "
            "redirect chains via the response-codes report."
        ),
        detector=_detect_external_subdomain,
    ),
    IssueDef(
        slug="unknown_page_type",
        title="URL pattern not recognised by classifier",
        severity="notice",
        category="indexability",
        why=(
            "The page-type classifier returned 'unknown' or empty. "
            "Means the audit can't apply page-type-specific checks "
            "to this URL (e.g., product-page thin-content warnings)."
        ),
        how_to_fix=(
            "Add a URL pattern to apps/crawler/storage/url_classifier.py "
            "for the new template, or rename the URL to match an "
            "existing pattern."
        ),
        detector=_detect_unknown_page_type,
    ),

    # PERFORMANCE_DEEP
    IssueDef(
        slug="response_p95_outlier",
        title="Above 95th-percentile response time",
        severity="warning",
        category="performance",
        why=(
            "Page response is in the worst 5% for this crawl. Fixing "
            "these gives disproportionate page-load improvement to "
            "real users because they slow the whole site's perceived "
            "responsiveness baseline."
        ),
        how_to_fix=(
            "Profile the request path. Common causes: uncached DB "
            "queries, blocking third-party fetches, missing CDN cache "
            "headers. Pin the page to your CDN edge if static."
        ),
        detector=_detect_p99_response,
    ),
    IssueDef(
        slug="status_set_no_response_time",
        title="Status set but response time = 0",
        severity="notice",
        category="performance",
        why=(
            "Data-quality smell: the fetcher recorded an HTTP status "
            "without timing data. Usually means the page came from a "
            "non-HTTP code path or the timing instrumentation broke."
        ),
        how_to_fix=(
            "Investigate the fetcher path that produced the row. "
            "Likely needs a small bug fix in engine/fetcher.py."
        ),
        detector=_detect_status_set_no_rt,
    ),
    IssueDef(
        slug="branch_locator_slow",
        title="Branch locator page over 5 seconds",
        severity="error",
        category="performance",
        why=(
            "Branch locator pages serve high-intent local-SEO queries "
            "('insurance branch near me'). Five-second loads kill "
            "local-pack ranking and lose users to faster competitors."
        ),
        how_to_fix=(
            "Cache aggressively at the edge. Pre-render branch tiles "
            "server-side. If the page is JS-heavy, render LocalBusiness "
            "schema in initial HTML for indexing."
        ),
        detector=_detect_branch_slow,
    ),

    # CONTENT_QUALITY
    IssueDef(
        slug="title_equals_url_slug",
        title="Title is just the URL slug",
        severity="warning",
        category="titles",
        why=(
            "Template default — the author never overrode the title. "
            "Google penalises this in SERP CTR because the snippet "
            "reads as auto-generated."
        ),
        how_to_fix=(
            "Write a unique 50-60 char title that includes the primary "
            "keyword + a benefit qualifier."
        ),
        detector=_detect_title_equals_url_slug,
    ),
    IssueDef(
        slug="title_over_100_chars",
        title="Title over 100 characters",
        severity="warning",
        category="titles",
        why=(
            "Way beyond SERP truncation (50-60 chars). Almost certainly "
            "a template bug concatenating brand + category + page name + "
            "tagline. The truncated form in SERP loses the entire tail."
        ),
        how_to_fix=(
            "Audit the title-tag template. Drop the brand from titles "
            "where the page itself signals brand strongly (homepage, "
            "product index)."
        ),
        detector=_detect_extreme_title_length,
    ),
    IssueDef(
        slug="product_page_thin",
        title="Product page with less than 500 words",
        severity="error",
        category="content",
        why=(
            "Product pages need depth + FAQs + structured data to rank "
            "for high-intent purchase queries. Thin product pages lose "
            "to competitors' content-rich equivalents."
        ),
        how_to_fix=(
            "Expand to 1,500-3,000 words. Add: definition section, "
            "key benefits, eligibility, premium calculation worked "
            "example, FAQ block with 8-12 Q&A, customer testimonials, "
            "regulatory disclosures."
        ),
        detector=_detect_product_page_thin,
    ),
    IssueDef(
        slug="calculator_missing_keyword",
        title="Calculator page missing 'calculator' in title",
        severity="notice",
        category="titles",
        why=(
            "Users search literally for 'X calculator' — a calculator-"
            "type page without the keyword in the title misses the "
            "direct SERP match."
        ),
        how_to_fix=(
            "Include the word 'calculator' near the start of the title. "
            "Pattern: '<Product> Calculator | Calculate <Outcome> Online'."
        ),
        detector=_detect_calculator_no_calculator_in_title,
    ),

    # URL_HYGIENE
    IssueDef(
        slug="uppercase_in_url",
        title="URL contains uppercase characters",
        severity="warning",
        category="urls",
        why=(
            "Mixed-case URLs risk being treated as duplicates by some "
            "rendering paths. Look unprofessional and break copy-paste "
            "workflows."
        ),
        how_to_fix=(
            "Force lowercase in the URL rewrite layer (Nginx, CDN, "
            "or AEM dispatcher). Add 301s for the uppercase variants."
        ),
        detector=_detect_uppercase_in_url,
    ),
    IssueDef(
        slug="legacy_index_php",
        title="Legacy /index.php in URL",
        severity="warning",
        category="urls",
        why=(
            "WordPress-style /index.php URLs split ranking signals "
            "with the clean equivalent. Should be 301'd to the "
            "directory form."
        ),
        how_to_fix=(
            "Configure Nginx/CDN to rewrite /path/index.php → /path/ "
            "with a permanent redirect. Update any internal links to "
            "use the clean form directly."
        ),
        detector=_detect_legacy_index_php,
    ),
    IssueDef(
        slug="url_fragment",
        title="URL contains # fragment",
        severity="notice",
        category="urls",
        why=(
            "Google ignores fragments for indexing. Internal links "
            "carrying fragments waste link equity that could go to the "
            "canonical (fragment-free) URL."
        ),
        how_to_fix=(
            "Strip the fragment from internal links. Use it only for "
            "anchors in the visible UI, not in <a href> destinations "
            "discovered by the crawler."
        ),
        detector=_detect_url_with_fragment,
    ),
    IssueDef(
        slug="tracking_param_in_url",
        title="URL contains tracking parameters",
        severity="notice",
        category="urls",
        why=(
            "utm_*, fbclid, gclid, mc_*, etc. are tracking parameters "
            "that should not be exposed as crawlable URLs. They create "
            "duplicate-content variants of the canonical page."
        ),
        how_to_fix=(
            "Add rel=canonical pointing at the parameter-free URL. "
            "Configure the CMS to strip these on internal links."
        ),
        detector=_detect_tracking_param_in_url,
    ),
    IssueDef(
        slug="trailing_slash_inconsistent",
        title="Both /foo and /foo/ return 200",
        severity="warning",
        category="urls",
        why=(
            "Two URL variants of the same page split link equity and "
            "trigger duplicate-content suppression."
        ),
        how_to_fix=(
            "Pick one convention (with or without trailing slash) and "
            "301 the other variant. Bajaj's existing pages favour "
            "no-trailing-slash on www; match that."
        ),
        detector=_detect_trailing_slash_inconsistency,
    ),

    # CRAWL_HEALTH
    IssueDef(
        slug="200_with_error_type",
        title="HTTP 200 but error_type recorded",
        severity="notice",
        category="crawlability",
        why=(
            "Soft error: the fetcher logged a problem (bad encoding, "
            "partial body, etc.) but the HTTP layer returned 200. "
            "Audit can't reliably score the page without resolving."
        ),
        how_to_fix=(
            "Inspect engine/fetcher.py for the path that produces this "
            "row. Either resolve the underlying error or treat the row "
            "as a real failure."
        ),
        detector=_detect_status_200_with_error_type,
    ),
    IssueDef(
        slug="non_200_no_error_type",
        title="Non-200 status without error_type",
        severity="notice",
        category="crawlability",
        why=(
            "Failure without a classification. The audit can't bucket "
            "these into a known error category. Hides crawl health "
            "issues from triage."
        ),
        how_to_fix=(
            "Extend the fetcher's error_type taxonomy to cover this "
            "case so future failures get classified."
        ),
        detector=_detect_non_200_no_error_type,
    ),
    IssueDef(
        slug="high_value_missing_sitemap",
        title="High-value page missing from sitemap (1000+ words)",
        severity="warning",
        category="indexability",
        why=(
            "Long-form OK www pages that aren't in sitemap.xml. "
            "Sitemap inclusion accelerates Google's discovery + "
            "re-crawl frequency — these pages are exactly the ones we "
            "want Google to find fast."
        ),
        how_to_fix=(
            "Add to the appropriate sitemap. If AEM-published, ensure "
            "the publish hook fires the sitemap rebuild + GSC ping."
        ),
        detector=_detect_orphan_in_results_not_sitemap,
    ),
    IssueDef(
        slug="dup_title_within_subdomain",
        title="Duplicate titles within a single subdomain",
        severity="error",
        category="content",
        why=(
            "Same title appearing on multiple URLs within the SAME "
            "subdomain is almost always a template bug. Splits ranking "
            "signals across the duplicate set."
        ),
        how_to_fix=(
            "Audit the title-tag template. Inject distinguishing tokens "
            "(location, product variant, content topic) into the "
            "template so each rendered page gets a distinct title."
        ),
        detector=_detect_dup_title_within_subdomain,
    ),
)
