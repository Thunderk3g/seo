"""Stage 4: aggregate top-10 competitors across LLM + SERP signals.

Scoring (per non-our-domain):

  +1.0     per LLM citation (cited_domains across all GapLLMResult rows)
  +position points 11-pos  per SERP organic appearance (top-10):
                            pos 1=10, pos 2=9, ..., pos 10=1
  +3.0     per featured-snippet ownership
  +2.0     per AI-Overview citation in any SERP

Sort descending, take top 10. Persist as GapCompetitor with a
score_breakdown JSON so the UI can show how each rival was ranked.

We also drop:
  * Our own domain (focus brand).
  * Junk infrastructure hosts (e.g. ``google.com``, ``youtube.com``,
    ``wikipedia.org`` show up in nearly every SERP and don't compete
    on commercial terms — they're discounted to reduce noise).
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from ..models import (
    GapCompetitor,
    GapLLMResult,
    GapPipelineRun,
    GapSerpResult,
)

logger = logging.getLogger("seo.ai.gap_pipeline.competitor_aggregation")


# Domains that show up in every SERP / LLM answer but don't actually
# compete for organic SEO traffic in our vertical. Discounted, not
# fully removed — a small score lets them surface if they truly
# dominate, but they shouldn't beat real rivals.
_INFRASTRUCTURE_HOSTS = {
    "google.com",
    "youtube.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "instagram.com",
    "wikipedia.org",
    "reddit.com",
    "quora.com",
    "medium.com",
    "github.com",
}
_INFRA_DISCOUNT = 0.2


def _bare(domain: str) -> str:
    bare = re.sub(r"^www\d?\.", "", (domain or "").lower())
    return bare.split("/")[0]


def _is_us(host: str, focus: str) -> bool:
    if not host or not focus:
        return False
    return (
        host == focus
        or host.endswith("." + focus)
        or focus.endswith("." + host)
        or focus in host
        or host in focus
    )


def _normalise_host(host: str) -> str:
    """Collapse hosts to their public-suffix-trimmed root for scoring.
    We don't pull a full TLD list — a cheap heuristic is enough to
    treat ``en.wikipedia.org`` and ``wikipedia.org`` as the same rival.
    """
    if not host:
        return ""
    parts = host.lower().split(".")
    if len(parts) <= 2:
        return host.lower()
    # Strip a leading subdomain that's clearly a locale/section
    # marker. Conservative — only the obvious ones.
    if parts[0] in ("en", "in", "uk", "us", "www", "m", "mobile", "blog", "support", "help"):
        return ".".join(parts[1:])
    return ".".join(parts)


def execute(*, run: GapPipelineRun, domain: str, top_n: int = 10) -> dict[str, Any]:
    """Compute the top-N competitor leaderboard from the run's LLM and
    SERP rows. Idempotent: deletes prior competitor rows for the same
    run before persisting (lets stage be re-run from the orchestrator
    after edits).
    """
    focus = _bare(domain)

    # ── score accumulators ───────────────────────────────────────────
    score: dict[str, float] = defaultdict(float)
    llm_cites: dict[str, int] = defaultdict(int)
    serp_hits: dict[str, int] = defaultdict(int)
    serp_top3: dict[str, int] = defaultdict(int)
    featured: dict[str, int] = defaultdict(int)
    ai_ov: dict[str, int] = defaultdict(int)
    queries_for: dict[str, set[str]] = defaultdict(set)

    # ── LLM citation pass ────────────────────────────────────────────
    for r in GapLLMResult.objects.filter(run=run).only(
        "cited_domains", "query_id"
    ).iterator():
        for host in r.cited_domains or []:
            n_host = _normalise_host(host)
            if not n_host or _is_us(n_host, focus):
                continue
            llm_cites[n_host] += 1
            score[n_host] += 1.0
            queries_for[n_host].add(str(r.query_id))

    # ── SERP pass ────────────────────────────────────────────────────
    for r in GapSerpResult.objects.filter(run=run).only(
        "organic", "featured_snippet", "ai_overview", "query_id"
    ).iterator():
        for row in (r.organic or [])[:10]:
            host = _normalise_host(row.get("domain") or "")
            if not host or _is_us(host, focus):
                continue
            pos = int(row.get("position") or 11)
            if pos < 1 or pos > 10:
                continue
            serp_hits[host] += 1
            if pos <= 3:
                serp_top3[host] += 1
            score[host] += float(11 - pos)
            queries_for[host].add(str(r.query_id))

        fs = r.featured_snippet or {}
        fs_host = _normalise_host(fs.get("domain") or "")
        if fs_host and not _is_us(fs_host, focus):
            featured[fs_host] += 1
            score[fs_host] += 3.0
            queries_for[fs_host].add(str(r.query_id))

        ai = r.ai_overview or {}
        for c in (ai.get("citations") or [])[:5]:
            c_host = _normalise_host((c or {}).get("domain") or "")
            if not c_host or _is_us(c_host, focus):
                continue
            ai_ov[c_host] += 1
            score[c_host] += 2.0
            queries_for[c_host].add(str(r.query_id))

    # ── infra discount + sort ────────────────────────────────────────
    final: list[tuple[str, float]] = []
    for host, raw_score in score.items():
        s = raw_score
        if host in _INFRASTRUCTURE_HOSTS:
            s *= _INFRA_DISCOUNT
        final.append((host, s))
    final.sort(key=lambda x: x[1], reverse=True)
    top = final[: max(1, int(top_n))]

    # ── persist ──────────────────────────────────────────────────────
    GapCompetitor.objects.filter(run=run).delete()
    for rank, (host, s) in enumerate(top, start=1):
        GapCompetitor.objects.create(
            run=run,
            domain=host,
            rank=rank,
            score=round(s, 3),
            llm_citation_count=llm_cites.get(host, 0),
            serp_appearance_count=serp_hits.get(host, 0),
            serp_top3_count=serp_top3.get(host, 0),
            featured_snippet_count=featured.get(host, 0),
            ai_overview_citation_count=ai_ov.get(host, 0),
            queries_appeared_for=list(queries_for.get(host, set()))[:50],
            score_breakdown={
                "llm_citations": llm_cites.get(host, 0),
                "serp_appearances": serp_hits.get(host, 0),
                "serp_top3": serp_top3.get(host, 0),
                "featured_snippets": featured.get(host, 0),
                "ai_overview_citations": ai_ov.get(host, 0),
                "infra_discount_applied": host in _INFRASTRUCTURE_HOSTS,
            },
        )

    run.competitor_count = len(top)
    run.save(update_fields=["competitor_count"])

    return {
        "status": "ok" if top else "empty",
        "competitor_count": len(top),
        "top_domain": top[0][0] if top else "",
        "considered_domains": len(final),
    }
