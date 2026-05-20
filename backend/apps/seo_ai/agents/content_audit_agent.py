"""ContentAuditAgent — LLM-graded comparison of our AEM page vs the
topically-closest competitor page.

Standalone agent (does NOT subclass :class:`Agent` from base.py because
the grading orchestrator's SEORun-message logging would be noise here —
each audit verdict gets its own row in :class:`GapAuditFinding` which
serves as the audit trail).

Flow:

  1. Resolve ``our_url`` to an :class:`AEMPage` via SitemapAEMAdapter.
  2. Pull the latest gap-pipeline run's competitor sample_pages
     (or accept ``their_url`` override if the caller already paired
     manually — used by the chat tool when the user says "compare
     against this specific page").
  3. Find the best competitor match via
     :func:`page_pairing.match_aem_to_candidates`. Persist as
     :class:`GapPagePair`.
  4. Build the audit payload: both pages' title / meta / body /
     schema / wordcount.
  5. Load the versioned rubric prompt (``v1.md``), prepend as system
     message, call the LLM with ``response_format=json_object``.
  6. Parse the JSON verdict, validate shape, clamp scores, derive
     ``winner`` from scores (defensive — LLM sometimes contradicts
     itself between scores and the winner field).
  7. Persist :class:`GapAuditFinding`.
  8. Return :class:`AuditVerdict`.

Failure modes (all logged, never raised to the chat tool):

  * No AEM page for our_url → "AEMPageNotFound"
  * No competitor pool (no gap-pipeline run yet) → "NoCompetitorPool"
  * LLM call fails / returns non-JSON → "LLMInvalidResponse"
  * Schema validation fails → still persist with ``error`` set

The agent ships with a Groq default; ``AUDIT_LLM_PROVIDER`` env var
overrides when premium-LLM billing lands.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from django.utils import timezone as dj_tz

from ..adapters import SitemapAEMAdapter
from ..gap_pipeline.page_pairing import (
    Match,
    match_aem_to_candidates,
)
from ..llm import get_provider
from ..models import (
    GapAuditFinding,
    GapDeepCrawl,
    GapPagePair,
    GapPipelineRun,
)

logger = logging.getLogger("seo.ai.agents.content_audit")


_RUBRIC_VERSION = "v1"
_RUBRIC_PATH = (
    Path(__file__).resolve().parent / "content_audit_prompts" / f"{_RUBRIC_VERSION}.md"
)
# How much body text we ship to the LLM per page. Trim to keep prompt
# size sane — 8 KB each side ≈ 1.5k tokens, fits comfortably in any
# modern context budget even with the rubric overhead.
_MAX_BODY_CHARS_PER_PAGE = 8_000


@dataclass
class AuditVerdict:
    """Structured return for the chat tool layer."""

    ok: bool
    error: str = ""
    finding_id: str = ""
    pair_id: str = ""
    our_url: str = ""
    their_url: str = ""
    competitor_domain: str = ""
    winner: str = ""                       # "us" | "them" | "tie"
    our_score: int = 0
    their_score: int = 0
    verdict_summary: str = ""
    our_strengths: list[str] = field(default_factory=list)
    our_gaps: list[str] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    match_score: float = 0.0
    match_reason: str = ""
    rubric_version: str = _RUBRIC_VERSION
    llm_provider: str = ""
    llm_model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    elapsed_seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Match the chat tool's expected ``{"ok": true, ...}`` shape.
        return d


class ContentAuditAgent:
    """Pair → audit → persist. Stateless per call."""

    def __init__(
        self,
        *,
        provider=None,
        rubric_path: Path | None = None,
        triggered_by: str = "chat",
    ) -> None:
        self.provider = provider or get_provider()
        self.rubric_path = rubric_path or _RUBRIC_PATH
        self.triggered_by = triggered_by
        self._rubric_text: str | None = None

    # ── public API ───────────────────────────────────────────────────

    def audit(
        self,
        *,
        our_url: str,
        their_url: str | None = None,
        run_id: str | None = None,
    ) -> AuditVerdict:
        """Audit one AEM URL.

        ``their_url`` (optional) lets the caller override the auto-match
        — useful when the chat user has named a specific competitor page
        to compare against.
        ``run_id`` (optional) pins to a specific gap-pipeline run;
        default is the most recent run for our domain.
        """
        t0 = time.time()

        # 1. Resolve our AEM page.
        our_page = self._load_aem_page(our_url)
        if our_page is None:
            return AuditVerdict(
                ok=False,
                error=f"AEMPageNotFound: no AEM page with public_url={our_url}",
                our_url=our_url,
                elapsed_seconds=round(time.time() - t0, 3),
            )

        # 2. Pick the gap-pipeline run.
        run = self._resolve_run(run_id)
        if run is None:
            return AuditVerdict(
                ok=False,
                error=(
                    "NoCompetitorPool: no gap-pipeline run found. "
                    "Start one from the Competitors page first."
                ),
                our_url=our_url,
                elapsed_seconds=round(time.time() - t0, 3),
            )

        # 3. Find the matched competitor page.
        match, competitor_domain = self._pick_match(
            run=run,
            our_url=our_url,
            our_title=our_page.title,
            their_url_override=their_url,
        )
        if match is None:
            return AuditVerdict(
                ok=False,
                error=(
                    "NoMatchFound: no competitor page paired to this "
                    "URL in the latest run. Try a different our_url or "
                    "trigger a fresh gap-pipeline run."
                ),
                our_url=our_url,
                elapsed_seconds=round(time.time() - t0, 3),
            )

        # 4. Persist the pair (idempotent enough — append is fine, the
        # latest row per (run, our_url, their_url) wins downstream).
        pair = GapPagePair.objects.create(
            run=run,
            our_url=our_page.public_url,
            our_title=(our_page.title or "")[:512],
            their_url=(match.candidate.get("url") or "")[:2048],
            their_title=(match.candidate.get("title") or "")[:512],
            competitor_domain=competitor_domain,
            similarity_score=match.score,
            slug_jaccard=match.slug_jaccard,
            title_cosine=match.title_cosine,
            match_reason=match.reason[:512],
        )

        # 5. Build payload + 6. call LLM + 7. parse.
        try:
            verdict_payload, usage = self._call_llm(our_page, match.candidate)
        except Exception as exc:  # noqa: BLE001 - chat-tool surface
            logger.exception("content_audit LLM call failed: %s", exc)
            finding = GapAuditFinding.objects.create(
                pair=pair,
                our_url=pair.our_url,
                their_url=pair.their_url,
                winner="tie",
                error=f"LLMCallFailed: {type(exc).__name__}: {exc}"[:1000],
                rubric_version=_RUBRIC_VERSION,
                llm_provider=getattr(self.provider, "name", "unknown"),
                llm_model=getattr(self.provider, "model", ""),
                triggered_by=self.triggered_by,
            )
            return AuditVerdict(
                ok=False,
                error=finding.error,
                finding_id=str(finding.id),
                pair_id=str(pair.id),
                our_url=pair.our_url,
                their_url=pair.their_url,
                competitor_domain=competitor_domain,
                match_score=match.score,
                match_reason=match.reason,
                llm_provider=getattr(self.provider, "name", "unknown"),
                llm_model=getattr(self.provider, "model", ""),
                elapsed_seconds=round(time.time() - t0, 3),
            )

        normalized = self._normalize_verdict(verdict_payload)

        # 8. Persist the finding.
        finding = GapAuditFinding.objects.create(
            pair=pair,
            our_url=pair.our_url,
            their_url=pair.their_url,
            winner=normalized["winner"],
            our_score=normalized["our_score"],
            their_score=normalized["their_score"],
            our_strengths=normalized["our_strengths"],
            our_gaps=normalized["our_gaps"],
            recommendations=normalized["recommendations"],
            verdict_summary=normalized["verdict_summary"],
            rubric_version=_RUBRIC_VERSION,
            llm_provider=getattr(self.provider, "name", "unknown"),
            llm_model=getattr(self.provider, "model", ""),
            tokens_in=usage["tokens_in"],
            tokens_out=usage["tokens_out"],
            cost_usd=usage["cost_usd"],
            triggered_by=self.triggered_by,
        )

        return AuditVerdict(
            ok=True,
            finding_id=str(finding.id),
            pair_id=str(pair.id),
            our_url=pair.our_url,
            their_url=pair.their_url,
            competitor_domain=competitor_domain,
            winner=normalized["winner"],
            our_score=normalized["our_score"],
            their_score=normalized["their_score"],
            verdict_summary=normalized["verdict_summary"],
            our_strengths=normalized["our_strengths"],
            our_gaps=normalized["our_gaps"],
            recommendations=normalized["recommendations"],
            match_score=match.score,
            match_reason=match.reason,
            llm_provider=getattr(self.provider, "name", "unknown"),
            llm_model=getattr(self.provider, "model", ""),
            tokens_in=usage["tokens_in"],
            tokens_out=usage["tokens_out"],
            cost_usd=usage["cost_usd"],
            elapsed_seconds=round(time.time() - t0, 3),
        )

    # ── internals ────────────────────────────────────────────────────

    def _load_aem_page(self, public_url: str):
        adapter = SitemapAEMAdapter()
        for p in adapter.iter_pages():
            if p.public_url == public_url:
                return p
        return None

    def _resolve_run(self, run_id: str | None) -> GapPipelineRun | None:
        if run_id:
            try:
                return GapPipelineRun.objects.get(pk=run_id)
            except (GapPipelineRun.DoesNotExist, ValueError):
                return None
        return GapPipelineRun.objects.order_by("-started_at").first()

    def _pick_match(
        self,
        *,
        run: GapPipelineRun,
        our_url: str,
        our_title: str,
        their_url_override: str | None,
    ) -> tuple[Match | None, str]:
        """Walk every competitor's sample_pages, pick the global best.

        If ``their_url_override`` is set, find that exact URL and short-
        circuit the matcher (the operator already knows what to compare).
        """
        crawls = list(
            GapDeepCrawl.objects.filter(run=run, is_us=False).order_by("domain")
        )

        if their_url_override:
            for c in crawls:
                for cand in (c.profile or {}).get("sample_pages") or []:
                    if (cand.get("url") or "").strip() == their_url_override.strip():
                        # Fabricate a Match shell so the rest of the
                        # flow works uniformly.
                        return (
                            Match(
                                score=1.0,
                                slug_jaccard=1.0,
                                title_cosine=1.0,
                                reason="manual override (operator picked this URL)",
                                candidate=cand,
                            ),
                            c.domain,
                        )
            return None, ""

        best: tuple[float, Match | None, str] = (-1.0, None, "")
        for c in crawls:
            ranked = match_aem_to_candidates(
                our_url=our_url,
                our_title=our_title,
                candidates=(c.profile or {}).get("sample_pages") or [],
            )
            if ranked and ranked[0].score > best[0]:
                best = (ranked[0].score, ranked[0], c.domain)
        return best[1], best[2]

    def _build_payload(self, our_page, their: dict) -> dict[str, Any]:
        return {
            "our_page": {
                "url": our_page.public_url,
                "aem_path": our_page.aem_path,
                "title": our_page.title,
                "meta_description": our_page.description,
                "template_name": our_page.template_name,
                "last_modified": (
                    our_page.last_modified.isoformat()
                    if our_page.last_modified
                    else ""
                ),
                "component_count": our_page.component_count,
                "component_types": our_page.component_types[:30],
                "word_count": our_page.word_count,
                "body_text": (our_page.content or "")[:_MAX_BODY_CHARS_PER_PAGE],
            },
            "their_page": {
                "url": their.get("url", ""),
                "title": their.get("title", ""),
                "meta_description": (their.get("meta_description") or "")[:512],
                "h1_texts": (their.get("h1_texts") or [])[:5],
                "schema_types": their.get("schema_types") or [],
                "page_type": their.get("page_type", ""),
                "word_count": their.get("word_count", 0),
                "last_modified": their.get("last_modified", ""),
                "response_time_ms": their.get("response_time_ms", 0),
                "body_text": (their.get("body_text") or "")[:_MAX_BODY_CHARS_PER_PAGE],
                "pagespeed_score": their.get("pagespeed_score"),
                "lcp_ms": their.get("lcp_ms"),
                "cls": their.get("cls"),
                "inp_ms": their.get("inp_ms"),
            },
        }

    def _rubric(self) -> str:
        if self._rubric_text is None:
            self._rubric_text = self.rubric_path.read_text(encoding="utf-8")
        return self._rubric_text

    def _call_llm(
        self, our_page, their: dict
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = self._build_payload(our_page, their)
        user_msg = (
            "Audit the two pages below using the rubric in the system "
            "prompt. Reply with ONLY the JSON object specified.\n\n"
            "<pages>\n```json\n"
            + json.dumps(payload, default=str, indent=2)
            + "\n```\n</pages>"
        )
        messages = [
            {"role": "system", "content": self._rubric()},
            {"role": "user", "content": user_msg},
        ]
        resp = self.provider.complete(
            messages=messages,
            response_format={"type": "json_object"},
        )
        try:
            parsed = json.loads(resp.content or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLMInvalidJSON: {exc}: {(resp.content or '')[:200]}") from exc

        return parsed, {
            "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out,
            "cost_usd": resp.cost_usd,
        }

    def _normalize_verdict(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Clamp + coerce the LLM's reply to the GapAuditFinding shape.

        Forgiving: if the LLM omits a field we default it; if it returns
        scores outside 0-100 we clamp; if its declared ``winner``
        disagrees with the scores by >5 we trust the scores.
        """
        def _clamp(v: Any, lo: int, hi: int) -> int:
            try:
                n = int(round(float(v)))
            except (TypeError, ValueError):
                return 0
            return max(lo, min(hi, n))

        our_score = _clamp(raw.get("our_score"), 0, 100)
        their_score = _clamp(raw.get("their_score"), 0, 100)

        # Defensive winner derivation — believe the numbers.
        diff = our_score - their_score
        if diff > 5:
            winner = "us"
        elif diff < -5:
            winner = "them"
        else:
            winner = "tie"
        # Honour the LLM's choice only when it agrees with the numbers.
        declared = (raw.get("winner") or "").strip().lower()
        if declared in {"us", "them", "tie"} and (
            (declared == "us" and diff > 0)
            or (declared == "them" and diff < 0)
            or (declared == "tie" and abs(diff) <= 5)
        ):
            winner = declared

        def _str_list(x: Any, cap: int = 10) -> list[str]:
            if not isinstance(x, list):
                return []
            return [str(item)[:600] for item in x[:cap] if item]

        recs = raw.get("recommendations") or []
        if not isinstance(recs, list):
            recs = []
        clean_recs: list[dict[str, Any]] = []
        for r in recs[:8]:
            if not isinstance(r, dict):
                continue
            prio = (r.get("priority") or "medium").strip().lower()
            if prio not in {"high", "medium", "low"}:
                prio = "medium"
            clean_recs.append({
                "priority": prio,
                "title": str(r.get("title") or "")[:120],
                "change": str(r.get("change") or "")[:1200],
            })

        return {
            "winner": winner,
            "our_score": our_score,
            "their_score": their_score,
            "verdict_summary": str(raw.get("verdict_summary") or "")[:2000],
            "our_strengths": _str_list(raw.get("our_strengths")),
            "our_gaps": _str_list(raw.get("our_gaps")),
            "recommendations": clean_recs,
        }
