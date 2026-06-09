"""Live section-wise report data for the frontend Reports page.

Everything here reads the lean projection (fast, ~1 MB) or small side CSVs,
EXCEPT the broken-link proof engine, which makes one pass over the master
``crawl_results.csv`` link-JSON columns (memoised on the results signature).

Sections powered here:
  * redirects      — 301 / other-3xx / redirect loops
  * soft_404       — HTTP 200 but near-empty body (< SOFT_404_WORDS words)
  * sitemap        — in-sitemap vs discovered-only, sitemap URLs that error
  * linking        — internal/external link totals + per-page outliers
  * pdf            — PDF health (encrypted / no text layer / broken / OK)
  * broken_links   — every internal 404/5xx target WITH proof: which page
                     links it, the anchor text, the section (nearest heading)
                     and the zone (nav / main / footer …)

Top-internal-linked pages already have a dedicated endpoint (/pagerank) and
robots.txt is fetched live (robots_summary), so they are not recomputed here.
"""
from __future__ import annotations

import csv
import json
from urllib.parse import urljoin, urlparse

from ..conf import settings
from ..engine.url_utils import normalize
from ..storage import repository as repo

SOFT_404_WORDS = 100          # mirror audits.detectors_phase_c.soft_404_after_render
_SAMPLE_CAP = 300             # max rows returned per section sample
_REDIRECT_CODES = {"301", "302", "303", "307", "308"}


# ── helpers ────────────────────────────────────────────────────────────────
def _to_int(v, default: int = 0) -> int:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_pdf(row: dict) -> bool:
    ct = (row.get("content_type") or "").lower()
    url = (row.get("url") or "").lower()
    return "pdf" in ct or url.endswith(".pdf")


# ── lean-based sections (fast, memoised on the results signature) ───────────
def sections() -> dict:
    return repo._memoize_on_results("report_sections", _compute_sections)


def _compute_sections() -> dict:
    redirects: list[dict] = []
    redirect_counts = {"301": 0, "other_3xx": 0, "loops": 0}
    soft_404: list[dict] = []
    sitemap = {"in_sitemap": 0, "discovered_only": 0, "sitemap_errors": 0}
    sitemap_error_rows: list[dict] = []
    pdf_rows: list[dict] = []
    pdf_counts = {"total": 0, "ok": 0, "error": 0,
                  "encrypted": 0, "no_text_layer": 0, "broken": 0}
    link_total_internal = 0
    link_total_external = 0
    no_internal_links: list[dict] = []
    top_external: list[dict] = []

    for row in repo.iter_results_lean():
        url = row.get("url") or ""
        code = (row.get("status_code") or "").strip()

        # — redirects —
        loop = _truthy(row.get("redirect_loop"))
        hops = _to_int(row.get("redirect_hops"))
        if code in _REDIRECT_CODES or loop or hops > 0:
            if loop:
                redirect_counts["loops"] += 1
            elif code == "301":
                redirect_counts["301"] += 1
            else:
                redirect_counts["other_3xx"] += 1
            if len(redirects) < _SAMPLE_CAP:
                redirects.append({
                    "url": url, "status_code": code, "hops": hops,
                    "final_url": row.get("redirect_final_url") or "",
                    "chain": row.get("redirect_chain") or "",
                    "loop": loop,
                })

        # — soft 404 —
        ct = (row.get("content_type") or "").lower()
        wc = _to_int(row.get("word_count"))
        if code == "200" and ("html" in ct or ct == "") and wc < SOFT_404_WORDS \
                and not _is_pdf(row):
            if len(soft_404) < _SAMPLE_CAP:
                soft_404.append({"url": url, "word_count": wc,
                                 "title": row.get("title") or ""})

        # — sitemap —
        if _truthy(row.get("from_sitemap")):
            sitemap["in_sitemap"] += 1
            if code and code != "200":
                sitemap["sitemap_errors"] += 1
                if len(sitemap_error_rows) < _SAMPLE_CAP:
                    sitemap_error_rows.append({"url": url, "status_code": code})
        else:
            sitemap["discovered_only"] += 1

        # — linking —
        ic = _to_int(row.get("internal_links_count"))
        ec = _to_int(row.get("external_links_count"))
        link_total_internal += ic
        link_total_external += ec
        if code == "200" and ic == 0 and ("html" in ct or ct == "") \
                and not _is_pdf(row) and len(no_internal_links) < _SAMPLE_CAP:
            no_internal_links.append({"url": url, "title": row.get("title") or ""})
        top_external.append({"url": url, "external_links_count": ec,
                             "internal_links_count": ic})

        # — pdf —
        if _is_pdf(row):
            pdf_counts["total"] += 1
            reasons = []
            if code and code != "200":
                reasons.append(f"http_{code}")
                pdf_counts["broken"] += 1
            if _truthy(row.get("pdf_is_encrypted")):
                reasons.append("encrypted")
                pdf_counts["encrypted"] += 1
            # has_text_layer may be "", "true"/"false"; only flag explicit false
            htl = str(row.get("pdf_has_text_layer") or "").strip().lower()
            if htl in {"false", "0", "no"}:
                reasons.append("no_text_layer")
                pdf_counts["no_text_layer"] += 1
            has_error = bool(reasons)
            pdf_counts["error" if has_error else "ok"] += 1
            if len(pdf_rows) < _SAMPLE_CAP:
                pdf_rows.append({
                    "url": url, "status_code": code,
                    "title": row.get("pdf_title") or row.get("title") or "",
                    "pages": _to_int(row.get("pdf_page_count")),
                    "byte_size": _to_int(row.get("pdf_byte_size")),
                    "has_error": has_error, "reasons": reasons,
                })

    top_external.sort(key=lambda r: r["external_links_count"], reverse=True)

    return {
        "redirects": {"counts": redirect_counts, "rows": redirects},
        "soft_404": {"count": len(soft_404), "rows": soft_404},
        "sitemap": {"counts": sitemap, "error_rows": sitemap_error_rows},
        "linking": {
            "total_internal": link_total_internal,
            "total_external": link_total_external,
            "pages_no_internal_links": no_internal_links,
            "top_external_pages": top_external[:50],
        },
        "pdf": {"counts": pdf_counts, "rows": pdf_rows},
    }


# ── broken-link proof engine (one master pass, memoised) ────────────────────
def broken_links() -> dict:
    return repo._memoize_on_results("report_broken_links", _compute_broken_links)


def _broken_target_map() -> dict[str, str]:
    """``{normalized_url: status_code}`` for internal 404/HTTP-error targets,
    read from the small per-error CSVs (no master scan)."""
    out: dict[str, str] = {}
    for key in ("errors_404", "errors_http"):
        meta = repo.CATALOG.get(key)
        if not meta:
            continue
        p = repo._path(meta["file"])
        if not p.exists():
            continue
        with open(p, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = (row.get("url") or "").strip()
                if not url:
                    continue
                n = normalize(url)
                if n:
                    out[n] = (row.get("status_code") or "404").strip() or "404"
    return out


def _compute_broken_links() -> dict:
    broken = _broken_target_map()
    if not broken:
        return {"total_targets": 0, "total_links": 0, "targets": [],
                "note": "No internal 404 / HTTP-error targets in this crawl."}

    # One pass over the master: find every on-page link whose href resolves to
    # a broken target, capturing the proof (source page + anchor + section).
    proofs: dict[str, list[dict]] = {}
    master = repo._path(repo.CATALOG["results"]["file"])
    if master.exists():
        with open(master, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                page = row.get("url") or ""
                for col in ("internal_links_json", "external_links_json"):
                    raw = row.get(col) or ""
                    if not raw or raw in ("[]", "null"):
                        continue
                    try:
                        links = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(links, list):
                        continue
                    for ln in links:
                        if not isinstance(ln, dict):
                            continue
                        href = normalize(ln.get("href") or "")
                        if not href or href not in broken:
                            continue
                        proofs.setdefault(href, []).append({
                            "page": page,
                            "anchor": (ln.get("anchor") or "").strip(),
                            "section": (ln.get("section") or "").strip(),
                            "zone": (ln.get("zone") or "").strip(),
                            "kind": (ln.get("kind") or "").strip(),
                        })

    total_links = sum(len(v) for v in proofs.values())
    targets = [
        {"url": u, "status": broken.get(u, "404"),
         "source_count": len(srcs), "sources": srcs[:50]}
        for u, srcs in proofs.items()
    ]
    # Most-linked broken targets first — those hurt the most.
    targets.sort(key=lambda t: t["source_count"], reverse=True)

    # Broken targets with NO discovered on-page link (came via sitemap/redirect)
    orphan_broken = [
        {"url": u, "status": s} for u, s in broken.items() if u not in proofs
    ]

    return {
        "total_targets": len(broken),
        "linked_targets": len(proofs),
        "total_links": total_links,
        "targets": targets,
        "orphan_broken": orphan_broken[:_SAMPLE_CAP],
    }


# ── external links (grouped by domain → URL → source pages) ─────────────────
_EXT_MAX_DOMAINS = 200
_EXT_MAX_URLS_PER_DOMAIN = 100
_EXT_MAX_SOURCES_PER_URL = 30


def external_links() -> dict:
    return repo._memoize_on_results("report_external_links", _compute_external_links)


def _compute_external_links() -> dict:
    # One master pass over external_links_json, aggregated destination → who
    # links to it, so the UI can render a clickable domain ▸ url ▸ pages tree.
    by_url: dict[str, dict] = {}
    master = repo._path(repo.CATALOG["results"]["file"])
    total_links = 0
    if master.exists():
        with open(master, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                page = row.get("url") or ""
                raw = row.get("external_links_json") or ""
                if not raw or raw in ("[]", "null"):
                    continue
                try:
                    links = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if not isinstance(links, list):
                    continue
                for ln in links:
                    if not isinstance(ln, dict):
                        continue
                    href = (ln.get("href") or "").strip()
                    if not href.startswith(("http://", "https://")):
                        continue
                    total_links += 1
                    d = by_url.setdefault(href, {
                        "url": href, "domain": (urlparse(href).netloc or "").lower(),
                        "count": 0, "anchors": set(), "sources": [],
                    })
                    d["count"] += 1
                    a = (ln.get("anchor") or "").strip()
                    if a:
                        d["anchors"].add(a[:120])
                    if len(d["sources"]) < _EXT_MAX_SOURCES_PER_URL:
                        d["sources"].append({
                            "page": page, "anchor": a,
                            "zone": (ln.get("zone") or "").strip(),
                            "rel": (ln.get("rel") or "").strip(),
                        })

    # Group URLs under their domain.
    domains: dict[str, dict] = {}
    for u in by_url.values():
        dom = domains.setdefault(u["domain"], {"domain": u["domain"], "link_count": 0, "urls": []})
        dom["link_count"] += u["count"]
        dom["urls"].append({
            "url": u["url"], "count": u["count"],
            "anchors": sorted(u["anchors"])[:5], "sources": u["sources"],
        })

    dom_list = sorted(domains.values(), key=lambda d: d["link_count"], reverse=True)
    for d in dom_list:
        d["url_count"] = len(d["urls"])
        d["urls"].sort(key=lambda x: x["count"], reverse=True)
        d["urls"] = d["urls"][:_EXT_MAX_URLS_PER_DOMAIN]

    return {
        "total_links": total_links,
        "total_unique_urls": len(by_url),
        "total_domains": len(domains),
        "domains": dom_list[:_EXT_MAX_DOMAINS],
    }


# ── robots.txt (live fetch + parse) ─────────────────────────────────────────
def robots_summary() -> dict:
    """Fetch the seed host's robots.txt and parse it into display sections:
    declared sitemaps, disallow / allow rules, crawl-delay, raw text."""
    import requests  # local import — keep module import light

    url = urljoin(settings.seed_url, "/robots.txt")
    try:
        resp = requests.get(
            url, timeout=15,
            headers={"User-Agent": settings.user_agent},
        )
    except requests.RequestException as exc:
        return {"present": False, "url": url, "error": str(exc)}

    if resp.status_code != 200:
        return {"present": False, "url": url, "status_code": resp.status_code}

    text = resp.text or ""
    sitemaps: list[str] = []
    disallow: list[str] = []
    allow: list[str] = []
    crawl_delay = None
    agents: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if key == "sitemap":
            sitemaps.append(val)
        elif key == "disallow" and val:
            disallow.append(val)
        elif key == "allow" and val:
            allow.append(val)
        elif key == "user-agent":
            agents.append(val)
        elif key == "crawl-delay":
            crawl_delay = val

    return {
        "present": True,
        "url": url,
        "status_code": 200,
        "sitemaps": sitemaps,
        "disallow": disallow[:_SAMPLE_CAP],
        "allow": allow[:_SAMPLE_CAP],
        "disallow_count": len(disallow),
        "allow_count": len(allow),
        "user_agents": agents,
        "crawl_delay": crawl_delay,
        "raw": text[:20000],
    }
