"""Phase B — SF parity detectors for hreflang + schema.org JSON-LD.

14 detectors total:

  Hreflang (6)
    * hreflang_invalid_codes      — codes that don't match BCP-47
    * hreflang_missing_x_default  — multi-locale site without x-default
    * hreflang_missing_self_ref   — hreflang block doesn't include self
    * hreflang_orphan             — page targets another locale that
                                    doesn't return-tag back (cross-page
                                    pass — runs at audit time)
    * hreflang_404                — hreflang href returns non-200
    * hreflang_to_noindex         — hreflang href is noindexed

  Schema.org JSON-LD (8)
    * jsonld_invalid_parse        — JSON parse failure in <script>
    * jsonld_missing_required     — required prop absent for the
                                    declared @type
    * jsonld_no_structured_data   — page has neither JSON-LD, microdata,
                                    nor RDFa
    * jsonld_uses_microdata_only  — legacy microdata-only page
    * jsonld_uses_rdfa_only       — legacy RDFa-only page
    * jsonld_unknown_type         — @type that isn't a known
                                    schema.org class
    * jsonld_rich_eligible_missing_required — block declared as a rich-
                                    result type but missing required props
    * jsonld_organization_missing — site has no Organization markup
                                    anywhere (homepage warning only)

The cross-page detectors (hreflang_orphan, hreflang_404,
hreflang_to_noindex) walk the full row set and join entries by
absolute URL — they're slower but still O(N).
"""
from __future__ import annotations

from .catalog import IssueDef, Severity, _is_ok, _to_int


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    return s in ("1", "true", "yes", "t", "y")


def _row_list(v):
    if isinstance(v, list):
        return v
    if not v:
        return []
    try:
        import json as _json
        parsed = _json.loads(str(v))
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


# Known schema.org top-level types we consider "real". Anything else
# triggers the unknown-type detector. Conservative list — only the
# common ones plus Google's rich-result set.
_KNOWN_SCHEMA_TYPES = frozenset({
    "Thing", "Action", "CreativeWork", "Event", "Intangible",
    "MedicalEntity", "Organization", "Person", "Place", "Product",
    "Article", "NewsArticle", "BlogPosting", "TechArticle",
    "Recipe", "Review", "AggregateRating", "Rating",
    "FAQPage", "Question", "Answer",
    "BreadcrumbList", "ListItem", "ItemList",
    "VideoObject", "ImageObject", "AudioObject", "MediaObject",
    "WebPage", "WebSite", "AboutPage", "ContactPage", "CollectionPage",
    "SearchAction", "EntryPoint",
    "LocalBusiness", "Corporation", "EducationalOrganization",
    "JobPosting", "Course", "HowTo", "HowToStep",
    "SoftwareApplication", "MobileApplication", "WebApplication",
    "Offer", "AggregateOffer", "Service", "FinancialProduct",
    "InsuranceAgency", "BankOrCreditUnion",
    "PostalAddress", "GeoCoordinates", "OpeningHoursSpecification",
    "ContactPoint", "Brand",
    "Country", "AdministrativeArea", "City", "State",
    "QuantitativeValue", "MonetaryAmount", "PriceSpecification",
    "Duration", "Distance", "Mass", "Energy",
    "Language", "DefinedTerm", "Role", "PropertyValue",
})

_RICH_RESULT_TYPES = frozenset({
    "Article", "NewsArticle", "BlogPosting",
    "Product", "Offer", "Review", "AggregateRating",
    "Recipe", "Event", "JobPosting",
    "FAQPage", "Question", "BreadcrumbList",
    "VideoObject", "Organization", "LocalBusiness",
    "Course", "HowTo", "SoftwareApplication",
})


# ── B.1 hreflang ───────────────────────────────────────────────────


def _detect_hreflang_invalid_codes(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _row_list(r.get("hreflang_invalid_codes"))]


def _detect_hreflang_missing_x_default(rows: list[dict]) -> list[dict]:
    # Only flag pages that DO have an hreflang cluster but no x-default.
    # Single-locale pages shouldn't be penalised.
    out = []
    for r in rows:
        count = _to_int(r.get("hreflang_count"))
        if count >= 2 and not _to_bool(r.get("hreflang_has_x_default")):
            out.append(r)
    return out


def _detect_hreflang_missing_self_ref(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if _to_int(r.get("hreflang_count")) >= 1 and not _to_bool(
            r.get("hreflang_self_reference")
        ):
            out.append(r)
    return out


def _detect_hreflang_orphan(rows: list[dict]) -> list[dict]:
    """Cross-page check: A declares ``<link hreflang=fr href=B>`` —
    does B declare a return tag pointing at A? If not, A is orphaned
    from Google's perspective."""
    # Index every page's hreflang targets by absolute href.
    by_url = {(r.get("url") or "").rstrip("/"): r for r in rows if _is_ok(r)}
    out = []
    for r in rows:
        if not _is_ok(r):
            continue
        entries = _row_list(r.get("hreflang_entries"))
        if not entries:
            continue
        self_url = (r.get("url") or "").rstrip("/")
        for e in entries:
            href = (e.get("href") or "").rstrip("/")
            if not href or href == self_url:
                continue
            target = by_url.get(href)
            if target is None:
                continue  # external locale page we didn't crawl — skip
            return_entries = _row_list(target.get("hreflang_entries"))
            return_urls = {(x.get("href") or "").rstrip("/") for x in return_entries}
            if self_url not in return_urls:
                out.append(r)
                break
    return out


def _detect_hreflang_404(rows: list[dict]) -> list[dict]:
    """Hreflang target URL came back non-200 in this crawl."""
    by_url = {(r.get("url") or "").rstrip("/"): r for r in rows}
    out = []
    for r in rows:
        if not _is_ok(r):
            continue
        for e in _row_list(r.get("hreflang_entries")):
            href = (e.get("href") or "").rstrip("/")
            target = by_url.get(href)
            if target and _to_int(target.get("status_code")) >= 400:
                out.append(r)
                break
    return out


def _detect_hreflang_to_noindex(rows: list[dict]) -> list[dict]:
    by_url = {(r.get("url") or "").rstrip("/"): r for r in rows}
    out = []
    for r in rows:
        if not _is_ok(r):
            continue
        for e in _row_list(r.get("hreflang_entries")):
            href = (e.get("href") or "").rstrip("/")
            target = by_url.get(href)
            if not target:
                continue
            robots = (target.get("meta_robots") or target.get("x_robots_tag") or "")
            if "noindex" in str(robots).lower():
                out.append(r)
                break
    return out


# ── B.2 schema.org JSON-LD ─────────────────────────────────────────


def _detect_jsonld_invalid_parse(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _to_int(r.get("jsonld_invalid_count")) > 0]


def _detect_jsonld_missing_required(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _row_list(r.get("jsonld_missing_required"))]


def _detect_no_structured_data(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not _is_ok(r):
            continue
        if (
            _to_int(r.get("jsonld_count")) == 0
            and _to_int(r.get("microdata_count")) == 0
            and _to_int(r.get("rdfa_count")) == 0
        ):
            out.append(r)
    return out


def _detect_uses_microdata_only(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not _is_ok(r):
            continue
        if (
            _to_int(r.get("microdata_count")) > 0
            and _to_int(r.get("jsonld_count")) == 0
        ):
            out.append(r)
    return out


def _detect_uses_rdfa_only(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not _is_ok(r):
            continue
        if (
            _to_int(r.get("rdfa_count")) > 0
            and _to_int(r.get("jsonld_count")) == 0
        ):
            out.append(r)
    return out


def _detect_jsonld_unknown_type(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        types = _row_list(r.get("jsonld_types"))
        if any(t and t not in _KNOWN_SCHEMA_TYPES for t in types):
            out.append(r)
    return out


def _detect_jsonld_rich_eligible_missing_required(rows: list[dict]) -> list[dict]:
    """Block declares itself as a rich-result type (Article, Product,
    FAQPage, etc.) but is missing one of the required props — so it
    won't actually surface as a rich result in Google."""
    out = []
    for r in rows:
        types = _row_list(r.get("jsonld_types"))
        missing = _row_list(r.get("jsonld_missing_required"))
        if not missing:
            continue
        rich_types_with_gaps = {
            m.get("type") for m in missing
            if isinstance(m, dict) and m.get("type") in _RICH_RESULT_TYPES
        }
        if rich_types_with_gaps:
            out.append(r)
    return out


def _detect_jsonld_organization_missing(rows: list[dict]) -> list[dict]:
    """Homepage-only check: site has no Organization markup anywhere.
    Fires once per crawl on the home URL."""
    has_org_anywhere = any(
        "Organization" in _row_list(r.get("jsonld_types"))
        or "Corporation" in _row_list(r.get("jsonld_types"))
        for r in rows
    )
    if has_org_anywhere:
        return []
    # Treat shortest-path-from-root URL as the homepage proxy.
    homepage = None
    best_len = None
    for r in rows:
        url = (r.get("url") or "").rstrip("/")
        if not url:
            continue
        path_len = url.count("/")
        if best_len is None or path_len < best_len:
            best_len = path_len
            homepage = r
    return [homepage] if homepage else []


# ──────────────────────────────────────────────────────────────────
# Catalogue
# ──────────────────────────────────────────────────────────────────


PHASE_B_ISSUES: tuple[IssueDef, ...] = (
    # ── B.1 hreflang ──
    IssueDef(
        slug="hreflang_invalid_codes",
        title="Invalid hreflang language code",
        severity="error",
        category="indexability",
        why=(
            "Google ignores hreflang annotations whose language code "
            "fails BCP-47 validation. The whole cluster's targeting "
            "breaks even if only one entry is malformed."
        ),
        how_to_fix=(
            "Use ISO 639-1 lang + optional ISO 3166-1 region, e.g. "
            "`en-US`, `hi-IN`, `x-default`. Drop region suffixes like "
            "`en-UK` (use `en-GB`)."
        ),
        detector=_detect_hreflang_invalid_codes,
    ),
    IssueDef(
        slug="hreflang_missing_x_default",
        title="Hreflang cluster without x-default",
        severity="warning",
        category="indexability",
        why=(
            "x-default tells Google which page to show users whose "
            "language doesn't match any locale. Without it Google "
            "guesses, often picking a non-English variant for "
            "fallback queries."
        ),
        how_to_fix=(
            "Add `<link rel=\"alternate\" hreflang=\"x-default\" "
            "href=\"...\">` pointing at the global / English fallback."
        ),
        detector=_detect_hreflang_missing_x_default,
    ),
    IssueDef(
        slug="hreflang_missing_self_ref",
        title="Hreflang block missing self-reference",
        severity="warning",
        category="indexability",
        why=(
            "Every page in a locale cluster must include its own URL "
            "with its own language code. Without the self-ref Google "
            "treats the cluster as inconsistent and may ignore it."
        ),
        how_to_fix=(
            "Add a `<link rel=\"alternate\" hreflang=\"{lang}\" "
            "href=\"{this-url}\">` entry."
        ),
        detector=_detect_hreflang_missing_self_ref,
    ),
    IssueDef(
        slug="hreflang_orphan",
        title="Hreflang return-tag missing on target locale",
        severity="error",
        category="indexability",
        why=(
            "Page A declares B as its French alternate, but B doesn't "
            "tag A back. Google requires bidirectional return tags "
            "and drops one-way clusters."
        ),
        how_to_fix=(
            "Audit the target page's <head>. Add the matching "
            "<link rel=alternate hreflang> pointing back at the "
            "source URL."
        ),
        detector=_detect_hreflang_orphan,
    ),
    IssueDef(
        slug="hreflang_404",
        title="Hreflang target returns 4xx/5xx",
        severity="error",
        category="indexability",
        why=(
            "A broken locale alternate breaks the cluster's signal. "
            "Google won't substitute the broken target in the SERP and "
            "may treat the rest of the cluster as untrustworthy."
        ),
        how_to_fix=(
            "Fix the target URL (restore it, 301 it to the live "
            "equivalent) or remove the hreflang entry pointing at it."
        ),
        detector=_detect_hreflang_404,
    ),
    IssueDef(
        slug="hreflang_to_noindex",
        title="Hreflang target is noindexed",
        severity="error",
        category="indexability",
        why=(
            "Noindex tells Google to drop the page; using it as a "
            "locale alternate is contradictory. The whole cluster "
            "loses authority."
        ),
        how_to_fix=(
            "Either remove the noindex from the target page or remove "
            "the hreflang entry pointing at it."
        ),
        detector=_detect_hreflang_to_noindex,
    ),

    # ── B.2 schema.org JSON-LD ──
    IssueDef(
        slug="jsonld_invalid_parse",
        title="JSON-LD block fails to parse",
        severity="error",
        category="content",
        why=(
            "A malformed JSON-LD block is silently ignored by Google. "
            "Any rich-result eligibility the markup intended is lost."
        ),
        how_to_fix=(
            "Validate the <script type=\"application/ld+json\"> "
            "payload with https://search.google.com/test/rich-results "
            "and fix the JSON syntax error."
        ),
        detector=_detect_jsonld_invalid_parse,
    ),
    IssueDef(
        slug="jsonld_missing_required",
        title="JSON-LD missing required property",
        severity="warning",
        category="content",
        why=(
            "Schema.org types have required properties; without them "
            "Google may parse the block but won't promote the page to "
            "a rich result."
        ),
        how_to_fix=(
            "See `jsonld_missing_required` column for {type, prop} "
            "list. Add the missing properties; Google's structured "
            "data guidelines list each type's requirements."
        ),
        detector=_detect_jsonld_missing_required,
    ),
    IssueDef(
        slug="no_structured_data",
        title="Page has no structured data at all",
        severity="notice",
        category="content",
        why=(
            "Structured data is what powers FAQ blocks, breadcrumbs, "
            "site-links, ratings, and AI-search citations. Pages "
            "without it forfeit rich SERP real estate."
        ),
        how_to_fix=(
            "Add JSON-LD relevant to the page type (Article for "
            "editorial pages, Product for product pages, FAQPage if "
            "the page answers questions)."
        ),
        detector=_detect_no_structured_data,
    ),
    IssueDef(
        slug="jsonld_uses_microdata_only",
        title="Page uses microdata only (no JSON-LD)",
        severity="notice",
        category="content",
        why=(
            "Microdata still works but JSON-LD is Google's preferred "
            "and most stable format. Microdata is harder to maintain "
            "and easier to break with template changes."
        ),
        how_to_fix=(
            "Migrate the microdata to JSON-LD in the page <head>. "
            "Use Google's Structured Data Markup Helper to convert."
        ),
        detector=_detect_uses_microdata_only,
    ),
    IssueDef(
        slug="jsonld_uses_rdfa_only",
        title="Page uses RDFa only (no JSON-LD)",
        severity="notice",
        category="content",
        why=(
            "RDFa is the oldest supported format and the most "
            "error-prone. JSON-LD is preferred."
        ),
        how_to_fix=(
            "Migrate to JSON-LD in the page <head>."
        ),
        detector=_detect_uses_rdfa_only,
    ),
    IssueDef(
        slug="jsonld_unknown_type",
        title="JSON-LD @type isn't a known schema.org class",
        severity="warning",
        category="content",
        why=(
            "Custom types are valid markup but Google won't use them "
            "for rich results — only recognised schema.org classes "
            "qualify."
        ),
        how_to_fix=(
            "Check https://schema.org/{type}. If it's a typo, fix the "
            "@type. If it's intentional custom markup, accept the "
            "warning — Google will simply ignore the unknown type."
        ),
        detector=_detect_jsonld_unknown_type,
    ),
    IssueDef(
        slug="jsonld_rich_eligible_missing_required",
        title="Rich-result type missing required properties",
        severity="error",
        category="content",
        why=(
            "The block declares Article / Product / FAQPage / etc. — "
            "types Google can promote to rich results — but is "
            "missing properties required for that promotion. The "
            "page won't appear as a rich result in search."
        ),
        how_to_fix=(
            "Test in https://search.google.com/test/rich-results, "
            "add the flagged properties (see `jsonld_missing_required`)."
        ),
        detector=_detect_jsonld_rich_eligible_missing_required,
    ),
    IssueDef(
        slug="jsonld_organization_missing",
        title="No Organization markup anywhere on the site",
        severity="warning",
        category="content",
        why=(
            "Organization JSON-LD on the homepage powers Google's "
            "Knowledge Panel, site-links, and entity recognition. "
            "Without it Google has to infer the brand from text alone."
        ),
        how_to_fix=(
            "Add an Organization JSON-LD block to the homepage with "
            "name, url, logo, sameAs (social profiles), and "
            "contactPoint."
        ),
        detector=_detect_jsonld_organization_missing,
    ),
)
