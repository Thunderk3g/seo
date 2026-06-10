"""Single-URL (and whole-site) technical SEO audit engine.

The chat assistant and the XLSX exporter both call this. Given ANY URL
(ours, a competitor's, or arbitrary), it:

  1. Looks the URL up in the crawl DB (any snapshot, newest first). If
     absent, live-crawls it on the spot via ``crawl_live`` so the
     assistant can audit a page nobody has crawled yet.
  2. Optionally runs a live Core Web Vitals test (PageSpeed Insights —
     mobile + desktop, lab + CrUX field) for that exact URL.
  3. Extracts the full structure already captured by the crawler:
     title/meta/canonical/robots, h1-h6 outline + counts, every internal
     and external link (with zone), every image with its alt text,
     JSON-LD schema, word count.
  4. Optionally spot-checks the page's links for 4xx/5xx (broken links).
  5. Scores the page against standard on-page SEO guidelines and emits a
     prioritised findings list — each with a plain-English drawback and a
     concrete recommendation.

Everything is deterministic Python — no LLM required — so it runs with
or without a provider key. The chat layer wraps the narrative; this
engine supplies the grounded facts + recommendations.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("seo.ai.services.technical_audit")


# ── SEO guideline thresholds (industry-standard) ────────────────────────
TITLE_MIN, TITLE_MAX = 30, 60
META_MIN, META_MAX = 70, 160
THIN_WORDS = 300
SLOW_MS = 1500
FEW_INTERNAL = 5
# Core Web Vitals (Google's "good" / "needs improvement" / "poor" cuts)
LCP_GOOD, LCP_POOR = 2500, 4000          # ms
CLS_GOOD, CLS_POOR = 0.10, 0.25
INP_GOOD, INP_POOR = 200, 500            # ms


def _finding(check: str, status: str, severity: str, detail: str,
             recommendation: str = "") -> dict[str, Any]:
    return {"check": check, "status": status, "severity": severity,
            "detail": detail, "recommendation": recommendation}


def _row_from_db(url: str):
    """Newest CrawlerPageResult for this exact URL (any snapshot), or None."""
    from apps.crawler.models import CrawlerPageResult
    norm = (url or "").strip()
    candidates = {norm}
    # tolerate trailing-slash + scheme variance
    if norm.endswith("/"):
        candidates.add(norm[:-1])
    else:
        candidates.add(norm + "/")
    return (CrawlerPageResult.objects
            .filter(url__in=list(candidates))
            .order_by("-snapshot__started_at")
            .first())


def _structure_from_row(row) -> dict[str, Any]:
    headings = list(row.headings_json or [])
    internal = list(row.internal_links_json or [])
    external = list(row.external_links_json or [])
    images = list(row.images_json or [])
    by_level: dict[int, list[str]] = {}
    for h in headings:
        by_level.setdefault(int(h.get("level") or 0), []).append(
            (h.get("text") or "")[:200])
    missing_alt = [i for i in images if not (i.get("alt") or "").strip()]
    return {
        "url": row.url,
        "final_url": row.final_url or row.url,
        "status_code": row.status_code,
        "response_time_ms": row.response_time_ms,
        "title": row.title or "",
        "meta_description": row.meta_description or "",
        "canonical": row.canonical or "",
        "meta_robots": row.meta_robots or "",
        "word_count": row.word_count or 0,
        "headings": headings,
        "h_counts": {f"h{n}": len(by_level.get(n, [])) for n in range(1, 7)},
        "h1_texts": by_level.get(1, []),
        "h2_outline": by_level.get(2, [])[:25],
        "internal_links": internal,
        "external_links": external,
        "images": images,
        "images_missing_alt": missing_alt,
        "schema_types": list(row.jsonld_types or []),
    }


def _check_broken_links(links: list[dict], *, cap: int = 40) -> list[dict]:
    """Bounded concurrent HEAD/GET over a page's links → 4xx/5xx list."""
    import requests
    seen: list[str] = []
    for l in links:
        href = (l.get("href") or "").strip()
        if href.startswith(("http://", "https://")) and href not in seen:
            seen.append(href)
        if len(seen) >= cap:
            break

    def _probe(u: str) -> dict | None:
        try:
            r = requests.head(u, timeout=8, allow_redirects=True, verify=False,
                              headers={"User-Agent": "Mozilla/5.0 (bajaj-seo-audit)"})
            if r.status_code == 405:  # some servers reject HEAD
                r = requests.get(u, timeout=8, allow_redirects=True, verify=False,
                                 stream=True,
                                 headers={"User-Agent": "Mozilla/5.0 (bajaj-seo-audit)"})
                r.close()
            if r.status_code >= 400:
                return {"url": u, "status": r.status_code}
        except requests.RequestException as exc:
            return {"url": u, "status": 0, "error": type(exc).__name__}
        return None

    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for res in pool.map(_probe, seen):
            if res:
                out.append(res)
    return out


def _cwv(url: str) -> dict[str, Any]:
    """Live CWV — mobile + desktop (lab + CrUX field). 7-day cached."""
    from ..adapters.cwv_psi import AdapterDisabledError, PSIAdapter
    try:
        psi = PSIAdapter()
    except AdapterDisabledError as exc:
        return {"available": False, "reason": str(exc)}
    out: dict[str, Any] = {"available": False}
    for strat in ("mobile", "desktop"):
        try:
            rec = psi.fetch(url, strategy=strat)
        except Exception as exc:  # noqa: BLE001
            out[strat] = {"error": f"{type(exc).__name__}: {exc}"[:160]}
            continue
        if rec is None or rec.error:
            out[strat] = {"error": (rec.error if rec else "no record")[:160]}
            continue
        out["available"] = True
        field = None
        if rec.has_field_data:
            field = {"lcp_ms": rec.field_lcp_ms, "inp_ms": rec.field_inp_ms,
                     "cls": rec.field_cls}
        out[strat] = {
            "performance_score": rec.performance_score,
            "lab": {"lcp_ms": rec.lab_lcp_ms, "cls": rec.lab_cls,
                    "fcp_ms": rec.lab_fcp_ms, "ttfb_ms": rec.lab_ttfb_ms},
            "field": field,
        }
    return out


def _cwv_findings(cwv: dict) -> list[dict]:
    out: list[dict] = []
    if not cwv.get("available"):
        return out
    m = cwv.get("mobile") or {}
    lab = m.get("lab") or {}
    field = m.get("field") or {}
    lcp = field.get("lcp_ms") or lab.get("lcp_ms")
    if lcp:
        if lcp > LCP_POOR:
            out.append(_finding("cwv_lcp", "fail", "critical",
                f"Mobile LCP is {lcp} ms (poor — Google's bar is < {LCP_GOOD} ms).",
                "Optimise the largest hero image/text block: preload it, serve "
                "modern formats (WebP/AVIF), and cut render-blocking CSS/JS."))
        elif lcp > LCP_GOOD:
            out.append(_finding("cwv_lcp", "warn", "warning",
                f"Mobile LCP is {lcp} ms (needs improvement — target < {LCP_GOOD} ms).",
                "Trim render-blocking resources and prioritise the hero element."))
    cls = field.get("cls") if field.get("cls") is not None else lab.get("cls")
    if cls is not None and cls > CLS_POOR:
        out.append(_finding("cwv_cls", "fail", "warning",
            f"Mobile CLS is {cls} (poor — target < {CLS_GOOD}).",
            "Reserve explicit width/height on images and ad/embed slots to stop "
            "layout shift."))
    inp = field.get("inp_ms")
    if inp and inp > INP_POOR:
        out.append(_finding("cwv_inp", "fail", "warning",
            f"Field INP is {inp} ms (poor — target < {INP_GOOD} ms).",
            "Break up long JavaScript tasks and defer non-critical handlers."))
    return out


def _structure_findings(s: dict) -> list[dict]:
    out: list[dict] = []

    # Title
    title = s["title"].strip()
    if not title:
        out.append(_finding("title", "fail", "critical", "Page has no <title>.",
            "Add a unique, descriptive title (30-60 chars) with the primary keyword."))
    elif len(title) > TITLE_MAX:
        out.append(_finding("title", "warn", "notice",
            f"Title is {len(title)} chars (> {TITLE_MAX}) — Google truncates it in SERPs.",
            f"Tighten to under {TITLE_MAX} characters, keyword first."))
    elif len(title) < TITLE_MIN:
        out.append(_finding("title", "warn", "notice",
            f"Title is only {len(title)} chars — under-using SERP real estate.",
            f"Expand toward {TITLE_MIN}-{TITLE_MAX} chars with a benefit + keyword."))

    # Meta description
    md = s["meta_description"].strip()
    if not md:
        out.append(_finding("meta_description", "fail", "warning",
            "No meta description — Google will autogenerate the snippet.",
            f"Write a {META_MIN}-{META_MAX} char description with a call to action."))
    elif len(md) > META_MAX:
        out.append(_finding("meta_description", "warn", "notice",
            f"Meta description is {len(md)} chars (> {META_MAX}) — it will be cut off.",
            f"Trim to under {META_MAX} characters."))

    # H1
    h1 = s["h_counts"]["h1"]
    if h1 == 0:
        out.append(_finding("h1", "fail", "critical", "Page has no H1 heading.",
            "Add exactly one H1 stating the page's main topic."))
    elif h1 > 1:
        out.append(_finding("h1", "warn", "warning",
            f"Page has {h1} H1 headings — should have exactly one.",
            "Demote the extra H1s to H2 so the page has a single clear topic."))

    # Heading depth
    if s["h_counts"]["h2"] == 0 and s["word_count"] > THIN_WORDS:
        out.append(_finding("headings", "warn", "notice",
            "Long page with no H2 subheadings — poor structure for readers and AI.",
            "Break the body into H2/H3 sections so the content is scannable."))

    # Images / alt
    total_img = len(s["images"])
    missing = len(s["images_missing_alt"])
    if total_img and missing:
        pct = round(100.0 * missing / total_img, 1)
        sev = "warning" if pct >= 25 else "notice"
        out.append(_finding("image_alt", "fail" if pct >= 25 else "warn", sev,
            f"{missing} of {total_img} images ({pct}%) have no alt text.",
            "Add descriptive alt text to every meaningful image (decorative "
            "images may use empty alt). Helps accessibility + image SEO."))

    # Canonical
    if not s["canonical"].strip():
        out.append(_finding("canonical", "warn", "notice", "No canonical URL declared.",
            "Add a self-referencing <link rel=canonical> to avoid duplicate-content dilution."))

    # noindex
    if "noindex" in s["meta_robots"].lower():
        out.append(_finding("meta_robots", "fail", "critical",
            f"Page is set to noindex (meta robots: {s['meta_robots']}).",
            "Remove noindex if this page should rank."))

    # Thin content
    if s["word_count"] < THIN_WORDS:
        out.append(_finding("thin_content", "warn", "warning",
            f"Only {s['word_count']} words — thin for a rankable page.",
            f"Expand toward {THIN_WORDS}+ words of genuinely useful content."))

    # Schema
    if not s["schema_types"]:
        out.append(_finding("schema", "warn", "notice",
            "No JSON-LD structured data found.",
            "Add relevant schema.org markup (Product, FAQPage, BreadcrumbList) "
            "for rich results and AI entity extraction."))

    # Internal links
    if len(s["internal_links"]) < FEW_INTERNAL:
        out.append(_finding("internal_links", "warn", "notice",
            f"Only {len(s['internal_links'])} internal links — weak link equity flow.",
            "Add contextual internal links to related products/guides."))

    # Response time
    rt = int(s.get("response_time_ms") or 0)
    if rt > SLOW_MS:
        out.append(_finding("response_time", "warn", "warning",
            f"Server response was {rt} ms (> {SLOW_MS} ms).",
            "Improve TTFB: caching, CDN, lighter server-side rendering."))

    # HTTPS
    if not (s.get("final_url") or "").lower().startswith("https://"):
        out.append(_finding("https", "fail", "critical", "Page not served over HTTPS.",
            "Serve all pages over HTTPS and redirect HTTP → HTTPS."))

    return out


def _score(findings: list[dict]) -> int:
    """0-100 technical score; criticals cost more than notices."""
    penalty = 0
    for f in findings:
        if f["status"] == "pass":
            continue
        penalty += {"critical": 15, "warning": 7, "notice": 3}.get(f["severity"], 3)
    return max(0, 100 - penalty)


def audit_url(url: str, *, check_broken_links: bool = False,
              include_cwv: bool = True) -> dict[str, Any]:
    """Full technical audit of one URL. DB-first, live-crawl on miss."""
    raw = (url or "").strip()
    if not raw:
        return {"ok": False, "error": "url required"}
    if "://" not in raw:
        raw = "https://" + raw

    source = "db"
    row = _row_from_db(raw)
    if row is None:
        # Not in the DB → live-crawl it now.
        from apps.crawler.views import CrawlLiveError, crawl_live
        try:
            _snap, row = crawl_live(raw)
            source = "live_crawl"
        except CrawlLiveError as exc:
            return {"ok": False, "error": f"crawl failed: {exc}"[:300],
                    "status_code": exc.status_code}

    s = _structure_from_row(row)
    findings = _structure_findings(s)

    cwv = {}
    if include_cwv:
        cwv = _cwv(s["final_url"] or s["url"])
        findings = _cwv_findings(cwv) + findings

    broken = []
    if check_broken_links:
        broken = _check_broken_links(
            list(s["internal_links"]) + list(s["external_links"]))
        if broken:
            findings.insert(0, _finding("broken_links", "fail", "critical",
                f"{len(broken)} broken link(s) (4xx/5xx) found on the page.",
                "Fix or remove the dead links — they waste crawl budget and hurt UX."))

    parsed = urlparse(s["final_url"] or s["url"])
    return {
        "ok": True,
        "url": s["url"],
        "host": parsed.netloc,
        "source": source,             # "db" or "live_crawl"
        "score": _score(findings),
        "summary": {
            "title": s["title"][:160],
            "title_length": len(s["title"]),
            "meta_description_length": len(s["meta_description"]),
            "word_count": s["word_count"],
            "h1": s["h_counts"]["h1"], "h2": s["h_counts"]["h2"],
            "h3": s["h_counts"]["h3"],
            "internal_links": len(s["internal_links"]),
            "external_links": len(s["external_links"]),
            "images_total": len(s["images"]),
            "images_missing_alt": len(s["images_missing_alt"]),
            "schema_types": s["schema_types"][:10],
            "canonical": s["canonical"][:200],
            "status_code": s["status_code"],
            "response_time_ms": s["response_time_ms"],
        },
        "cwv": cwv,
        "h2_outline": s["h2_outline"],
        "images_missing_alt_samples": [
            (i.get("src") or "")[:160] for i in s["images_missing_alt"][:15]
        ],
        "broken_links": broken[:25],
        "findings": findings,
        "counts": {
            "critical": sum(1 for f in findings if f["severity"] == "critical"),
            "warning": sum(1 for f in findings if f["severity"] == "warning"),
            "notice": sum(1 for f in findings if f["severity"] == "notice"),
        },
    }


def compare_urls(our_url: str, competitor_urls: list[str], *,
                 include_cwv: bool = True) -> dict[str, Any]:
    """Side-by-side technical audit: our page vs up to 5 competitor pages."""
    rivals = [u.strip() for u in (competitor_urls or []) if u and u.strip()][:5]
    if not (our_url or "").strip():
        return {"ok": False, "error": "our_url required"}
    if not rivals:
        return {"ok": False, "error": "competitor_urls required"}
    ours = audit_url(our_url, include_cwv=include_cwv)
    theirs = [audit_url(u, include_cwv=include_cwv) for u in rivals]

    def _slim(a: dict) -> dict:
        if not a.get("ok"):
            return {"url": a.get("url"), "error": a.get("error")}
        m = a["cwv"].get("mobile", {}) if a.get("cwv", {}).get("available") else {}
        lab = (m or {}).get("lab", {})
        field = (m or {}).get("field") or {}
        return {
            "url": a["url"], "host": a["host"], "score": a["score"],
            **a["summary"],
            "lcp_ms": field.get("lcp_ms") or lab.get("lcp_ms"),
            "criticals": a["counts"]["critical"],
        }

    return {
        "ok": True,
        "ours": _slim(ours),
        "competitors": [_slim(t) for t in theirs],
        "note": ("Technical comparison: score is our 0-100 on-page health; "
                 "lcp_ms is mobile (CrUX field if available, else lab). Each "
                 "page was pulled from the DB or live-crawled if missing."),
    }
