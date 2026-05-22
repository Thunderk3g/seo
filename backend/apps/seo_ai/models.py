"""Persistence for SEO AI runs.

We store everything an auditor would need to reproduce a run: the
weight matrix at the time, the per-source data snapshot pointers, every
agent message, and every tool call. Storage cost is small compared to
the value of post-hoc explainability — particularly in a regulated
industry where "why did the model recommend X" must be answerable a
quarter later.

Schema choices:

- UUID primary keys so run IDs are URL-safe and never leak ordering.
- JSON columns (``JSONField``) for everything structured-but-variable.
  Postgres → jsonb under the hood; SQLite → TEXT with a JSON1 helper.
- ``related_name`` chosen for ergonomic ``run.findings.all()`` etc.
"""
from __future__ import annotations

import uuid

from django.db import models


class SEORunStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    CRITIC = "critic", "Critic"
    COMPLETE = "complete", "Complete"
    DEGRADED = "degraded", "Degraded"
    FAILED = "failed", "Failed"


class FindingSeverity(models.TextChoices):
    CRITICAL = "critical", "Critical"
    WARNING = "warning", "Warning"
    NOTICE = "notice", "Notice"


class SEORun(models.Model):
    """One end-to-end grading invocation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.CharField(max_length=255)
    triggered_by = models.CharField(max_length=64, default="api")
    status = models.CharField(
        max_length=16, choices=SEORunStatus.choices, default=SEORunStatus.PENDING
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    overall_score = models.FloatField(null=True, blank=True)
    sub_scores = models.JSONField(default=dict, blank=True)
    weights = models.JSONField(default=dict, blank=True)
    sources_snapshot = models.JSONField(default=dict, blank=True)
    model_versions = models.JSONField(default=dict, blank=True)
    total_cost_usd = models.FloatField(default=0.0)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-started_at",)
        indexes = [
            models.Index(fields=["domain", "-started_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - admin convenience
        return f"{self.domain} {self.id} {self.status}"


class SEORunFinding(models.Model):
    """One recommendation or issue produced by an agent."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        SEORun, on_delete=models.CASCADE, related_name="findings"
    )
    agent = models.CharField(max_length=64)
    severity = models.CharField(
        max_length=16, choices=FindingSeverity.choices
    )
    category = models.CharField(max_length=128)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    recommendation = models.TextField(blank=True, default="")
    evidence_refs = models.JSONField(default=list, blank=True)
    impact = models.CharField(max_length=16, default="medium")  # high/medium/low
    effort = models.CharField(max_length=16, default="medium")
    priority = models.IntegerField(default=50)  # 1–100

    class Meta:
        ordering = ("-priority",)
        indexes = [
            models.Index(fields=["run", "-priority"]),
            models.Index(fields=["agent"]),
            models.Index(fields=["severity"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"[{self.severity}] {self.title}"


class SEORunMessage(models.Model):
    """One agent-to-agent / agent-to-tool message. The audit trail."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        SEORun, on_delete=models.CASCADE, related_name="messages"
    )
    step_index = models.IntegerField()
    from_agent = models.CharField(max_length=64)
    to_agent = models.CharField(max_length=64, blank=True, default="")
    role = models.CharField(max_length=32)  # system|user|assistant|tool|critic
    content = models.JSONField(default=dict, blank=True)
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cost_usd = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("run", "step_index", "created_at")
        indexes = [
            models.Index(fields=["run", "step_index"]),
        ]


class SEORunToolCall(models.Model):
    """Every tool invocation. Replay reads this back instead of re-calling."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        SEORun, on_delete=models.CASCADE, related_name="tool_calls"
    )
    agent = models.CharField(max_length=64)
    tool_name = models.CharField(max_length=128)
    args = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    latency_ms = models.IntegerField(default=0)
    cached = models.BooleanField(default=False)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("run", "created_at")
        indexes = [
            models.Index(fields=["run", "agent"]),
        ]


# ── Gap Detection Pipeline ───────────────────────────────────────────────
# Phase-3 pipeline that decouples the data-gathering steps (LLM-generated
# queries → multi-LLM web-grounded search → SerpAPI search → top-10
# competitor aggregation → deep crawl → comparison) from the SEORun
# audit trail. Each row below is a transparent step the UI renders as
# its own panel, so users see queries, citations, SERP results, and
# the discovered competitor roster — not just the final gap findings.


class GapPipelineStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETE = "complete", "Complete"
    DEGRADED = "degraded", "Degraded"
    FAILED = "failed", "Failed"


class GapPipelineRun(models.Model):
    """One end-to-end gap-pipeline invocation for a domain.

    Stage status is stored in ``stage_status`` JSON so the polling UI
    can render live progress: each stage transitions
    ``pending → running → ok|skipped|failed``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.CharField(max_length=255)
    triggered_by = models.CharField(max_length=64, default="api")
    status = models.CharField(
        max_length=16,
        choices=GapPipelineStatus.choices,
        default=GapPipelineStatus.PENDING,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Stage 1: query synthesis. Counts so the UI can render a strip
    # without re-querying child tables.
    query_count = models.IntegerField(default=0)
    seed_keyword_count = models.IntegerField(default=0)

    # Stage 2: LLM search.
    llm_provider_count = models.IntegerField(default=0)
    llm_call_count = models.IntegerField(default=0)
    llm_total_cost_usd = models.FloatField(default=0.0)

    # Stage 3: SERP search.
    serp_engine_count = models.IntegerField(default=0)
    serp_call_count = models.IntegerField(default=0)

    # Stage 4: top competitors.
    competitor_count = models.IntegerField(default=0)

    # Stage 5: deep crawl.
    deep_crawl_pages = models.IntegerField(default=0)

    # Per-stage live status. Shape:
    # {"queries": {"status": "ok", "started_at": "...", "finished_at": "...",
    #              "note": "..."}, "llm_search": {...}, ...}
    stage_status = models.JSONField(default=dict, blank=True)

    # Overall config / inputs snapshot.
    config_snapshot = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-started_at",)
        indexes = [
            models.Index(fields=["domain", "-started_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"gap-pipeline {self.domain} {self.id} {self.status}"


class GapPipelineQuery(models.Model):
    """One LLM-synthesised query that drives stages 2 + 3.

    ``intent`` is one of: informational, commercial, comparison,
    brand_specific, long_tail, conversational (matches the seed-bucket
    taxonomy in apps.seo_ai.queries.seed_queries).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        GapPipelineRun, on_delete=models.CASCADE, related_name="queries"
    )
    query = models.CharField(max_length=512)
    intent = models.CharField(max_length=32, default="informational")
    rationale = models.CharField(max_length=512, blank=True, default="")
    source_keywords = models.JSONField(default=list, blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ("run", "order")
        indexes = [
            models.Index(fields=["run", "order"]),
        ]


class GapLLMResult(models.Model):
    """One (query × LLM provider) probe with the model's answer + cites."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        GapPipelineRun, on_delete=models.CASCADE, related_name="llm_results"
    )
    query = models.ForeignKey(
        GapPipelineQuery, on_delete=models.CASCADE, related_name="llm_results"
    )
    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=128, blank=True, default="")
    answer_text = models.TextField(blank=True, default="")
    cited_urls = models.JSONField(default=list, blank=True)
    cited_domains = models.JSONField(default=list, blank=True)
    mentions_our_brand = models.BooleanField(default=False)
    web_search_used = models.BooleanField(default=False)
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cost_usd = models.FloatField(default=0.0)
    latency_ms = models.IntegerField(default=0)
    cached = models.BooleanField(default=False)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("run", "provider", "query_id")
        indexes = [
            models.Index(fields=["run", "provider"]),
            models.Index(fields=["query"]),
        ]


class GapSerpResult(models.Model):
    """One (query × engine × device) SERP probe — top organic + featured + AI Overview."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        GapPipelineRun, on_delete=models.CASCADE, related_name="serp_results"
    )
    query = models.ForeignKey(
        GapPipelineQuery, on_delete=models.CASCADE, related_name="serp_results"
    )
    engine = models.CharField(max_length=32)
    # SerpAPI device split — "desktop" / "mobile" / "tablet". Each device
    # is a separate billed SerpAPI call, so each (query, engine, device)
    # is a distinct row. Defaults to "desktop" for back-compat with rows
    # written before the device split was introduced.
    device = models.CharField(max_length=16, default="desktop")
    # organic: [{position, title, url, domain, snippet}, ...] up to 25
    organic = models.JSONField(default=list, blank=True)
    featured_snippet = models.JSONField(default=dict, blank=True, null=True)
    ai_overview = models.JSONField(default=dict, blank=True, null=True)
    people_also_ask = models.JSONField(default=list, blank=True)
    related_searches = models.JSONField(default=list, blank=True)
    our_position = models.IntegerField(null=True, blank=True)  # 1-10 or null
    cached = models.BooleanField(default=False)
    latency_ms = models.IntegerField(default=0)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("run", "engine", "device", "query_id")
        indexes = [
            models.Index(fields=["run", "engine"]),
            models.Index(fields=["run", "engine", "device"]),
            models.Index(fields=["query"]),
        ]


class GapCompetitor(models.Model):
    """One competitor domain in the aggregated top-N list.

    Score breakdown is stored as JSON so the UI can show how the rank
    was built (LLM citations + SERP positions + featured snippets + AI
    overviews).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        GapPipelineRun, on_delete=models.CASCADE, related_name="competitors"
    )
    domain = models.CharField(max_length=255)
    rank = models.IntegerField()
    score = models.FloatField(default=0.0)
    llm_citation_count = models.IntegerField(default=0)
    serp_appearance_count = models.IntegerField(default=0)
    serp_top3_count = models.IntegerField(default=0)
    featured_snippet_count = models.IntegerField(default=0)
    ai_overview_citation_count = models.IntegerField(default=0)
    queries_appeared_for = models.JSONField(default=list, blank=True)
    score_breakdown = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("run", "rank")
        indexes = [
            models.Index(fields=["run", "rank"]),
        ]


class GapDeepCrawl(models.Model):
    """Aggregated crawl profile for one competitor — built from
    ``CompetitorCrawler`` results across the competitor's sitemap pages.

    Profile JSON shape: {page_count, avg_word_count, avg_response_ms,
    schema_pct, h1_pct, schema_types: [...], page_types: {pricing: n,
    comparison: n, calculator: n, faq: n, blog: n}, has_pricing_page,
    has_llms_txt, has_pricing_md, sample_pages: [...]}.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        GapPipelineRun, on_delete=models.CASCADE, related_name="deep_crawls"
    )
    competitor = models.ForeignKey(
        GapCompetitor,
        on_delete=models.CASCADE,
        related_name="deep_crawl",
        null=True,
        blank=True,
    )
    domain = models.CharField(max_length=255)
    is_us = models.BooleanField(default=False)
    sitemap_url_count = models.IntegerField(default=0)
    pages_attempted = models.IntegerField(default=0)
    pages_ok = models.IntegerField(default=0)
    profile = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("run", "domain")
        indexes = [
            models.Index(fields=["run", "is_us"]),
        ]


class GapComparison(models.Model):
    """One gap row from the final diff stage.

    ``dimension`` is one of: schema_coverage, page_type_coverage,
    content_depth, ai_citability, machine_readable_files,
    response_time, llm_visibility, serp_visibility. Each row carries
    our value, the competitor median, the delta, and a short
    human-readable headline.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        GapPipelineRun, on_delete=models.CASCADE, related_name="comparisons"
    )
    dimension = models.CharField(max_length=64)
    severity = models.CharField(
        max_length=16, choices=FindingSeverity.choices, default="notice"
    )
    headline = models.CharField(max_length=255)
    our_value = models.JSONField(default=dict, blank=True)
    competitor_median = models.JSONField(default=dict, blank=True)
    delta = models.JSONField(default=dict, blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    priority = models.IntegerField(default=50)

    class Meta:
        ordering = ("run", "-priority")
        indexes = [
            models.Index(fields=["run", "-priority"]),
        ]


# ── Content audit (Stage-2 — LLM-graded matched page pairs) ──────────
#
# Two-table model:
#   * GapPagePair  — "our AEM URL X matches competitor URL Y" (pure
#                    string-matcher output; no LLM call yet, just cheap
#                    URL-slug Jaccard + title cosine via page_pairing.py).
#   * GapAuditFinding — the LLM verdict on one pair: which page would an
#                       LLM cite, why, what we're missing, what to fix.
#
# Why two tables: pair creation is cheap (string math) and we want to
# regenerate pairs every time the gap pipeline runs without re-grading
# every pair. Findings are append-only history so you can see how a page
# improved over time; the latest finding per pair powers the UI.


class GapPagePair(models.Model):
    """One AEM page matched to its topically-closest competitor page.

    Generated by ``gap_pipeline/page_pairing.py`` (60% URL-slug Jaccard,
    40% title cosine, no LLM). Refreshed each gap-pipeline run. The
    same our_url / their_url can appear across multiple runs as
    competitor content shifts; the latest run's row is canonical.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        GapPipelineRun, on_delete=models.CASCADE, related_name="page_pairs"
    )
    our_url = models.URLField(max_length=2048)
    our_title = models.CharField(max_length=512, blank=True, default="")
    their_url = models.URLField(max_length=2048)
    their_title = models.CharField(max_length=512, blank=True, default="")
    competitor_domain = models.CharField(max_length=255)
    similarity_score = models.FloatField(default=0.0)         # blended 0-1
    slug_jaccard = models.FloatField(default=0.0)             # raw slug overlap
    title_cosine = models.FloatField(default=0.0)             # raw title cosine
    match_reason = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("run", "competitor_domain", "-similarity_score")
        indexes = [
            models.Index(fields=["run", "competitor_domain"]),
            models.Index(fields=["our_url"]),
        ]


class GapAuditFinding(models.Model):
    """LLM verdict on one page pair.

    Append-only: each audit run (manual or chat-tool-triggered) writes a
    fresh row. The UI shows the latest per pair and exposes prior rows
    behind a "show history" link so trends are visible.
    """

    WINNER_CHOICES = [
        ("us", "Us"),
        ("them", "Them"),
        ("tie", "Tie"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pair = models.ForeignKey(
        GapPagePair, on_delete=models.CASCADE, related_name="findings"
    )
    # Snapshotted at audit time so a deleted pair row doesn't orphan
    # historical verdicts. Use pair FK for joins, these fields for read.
    our_url = models.URLField(max_length=2048)
    their_url = models.URLField(max_length=2048)
    winner = models.CharField(max_length=8, choices=WINNER_CHOICES)
    our_score = models.IntegerField(default=0)                 # 0-100
    their_score = models.IntegerField(default=0)               # 0-100
    our_strengths = models.JSONField(default=list, blank=True)  # list[str]
    our_gaps = models.JSONField(default=list, blank=True)       # list[str]
    recommendations = models.JSONField(default=list, blank=True)
    # ↑ list of {priority: "high"|"medium"|"low", title: str, change: str}
    verdict_summary = models.TextField(blank=True, default="")
    rubric_version = models.CharField(max_length=16, default="v1")
    llm_provider = models.CharField(max_length=32, default="groq")
    llm_model = models.CharField(max_length=64, blank=True, default="")
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cost_usd = models.FloatField(default=0.0)
    triggered_by = models.CharField(max_length=64, default="chat")
    # ↑ "chat" | "api" | "scheduled" — same audit-trail pattern as SEORun
    error = models.TextField(blank=True, default="")
    graded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-graded_at",)
        indexes = [
            models.Index(fields=["pair", "-graded_at"]),
            models.Index(fields=["our_url", "-graded_at"]),
        ]


# ─────────────────────────────────────────────────────────────────────
# Brand Mentions / Visibility — third-party sites talking about Bajaj.
# ─────────────────────────────────────────────────────────────────────


class BrandVariant(models.TextChoices):
    """Which name variant the mention uses — drives the rebrand
    stickiness chart on the dashboard."""

    NEW = "new", "Bajaj Life Insurance (new brand)"
    OLD = "old", "Bajaj Allianz Life (legacy brand)"
    PARENT = "parent", "Bajaj Allianz (general — ambiguous)"
    AMBIGUOUS = "ambiguous", "Ambiguous / multiple"


class MentionSourceTier(models.TextChoices):
    """Source-authority tier. Tier-1 news + regulatory pass the most
    authority; review/forum carry sentiment weight; aggregator signals
    funnel demand."""

    NEWS_TIER_1 = "news_tier_1", "News (tier 1)"
    NEWS_TIER_2 = "news_tier_2", "News (tier 2)"
    FORUM = "forum", "Forum / community"
    REVIEW = "review", "Review site"
    AGGREGATOR = "aggregator", "Insurance aggregator"
    REGULATORY = "regulatory", "Regulatory body"
    BLOG = "blog", "Blog / other"
    OTHER = "other", "Other"


class MentionSentiment(models.TextChoices):
    POSITIVE = "positive", "Positive"
    NEUTRAL = "neutral", "Neutral"
    NEGATIVE = "negative", "Negative"
    UNSCORED = "unscored", "Unscored"


class MentionDiscoveredVia(models.TextChoices):
    """Which sub-adapter found the mention. Lets the UI show coverage
    per source and lets the operator see if e.g. Reddit fails on the
    corp network."""

    RSS = "rss", "RSS feed"
    REDDIT = "reddit", "Reddit public JSON"
    SERPAPI = "serpapi", "SerpAPI daily"
    COMMONCRAWL = "commoncrawl", "Common Crawl"
    MANUAL = "manual", "Manual import"


class BrandMention(models.Model):
    """One mention of a Bajaj brand variant on a third-party page.

    Uniqueness: a given source_url can only appear once. The adapters
    use ``update_or_create`` keyed on source_url so the same article
    appearing in multiple sources (e.g., Google web + Reddit search
    both surfacing the same Reddit thread) doesn't duplicate — the
    earlier ``first_seen_at`` wins, ``last_seen_at`` keeps updating.

    Sentiment is unscored until the Groq batch runs (usually within
    seconds of the pull). When the Groq quota is exhausted or the
    adapter is disabled, rows stay ``unscored`` and the UI shows them
    behind an "unscored" badge so the operator knows the data is real
    but unjudged.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_url = models.URLField(max_length=2000, unique=True)
    source_domain = models.CharField(max_length=255, db_index=True)
    source_title = models.CharField(max_length=512, blank=True, default="")
    snippet = models.TextField(blank=True, default="")
    # Brand variant the snippet matched on (regex-classified at write time).
    brand_variant = models.CharField(
        max_length=16,
        choices=BrandVariant.choices,
        default=BrandVariant.NEW,
        db_index=True,
    )
    # Editorial / forum / review / aggregator — drives the tier donut.
    source_tier = models.CharField(
        max_length=16,
        choices=MentionSourceTier.choices,
        default=MentionSourceTier.OTHER,
        db_index=True,
    )
    sentiment = models.CharField(
        max_length=16,
        choices=MentionSentiment.choices,
        default=MentionSentiment.UNSCORED,
        db_index=True,
    )
    sentiment_confidence = models.FloatField(default=0.0)
    # True once a second-pass page fetch confirms the brand was actually
    # wrapped in an <a href> on the page. Set by page_fetch.py adapter.
    is_linked = models.BooleanField(default=False, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    discovered_via = models.CharField(
        max_length=16,
        choices=MentionDiscoveredVia.choices,
        default=MentionDiscoveredVia.MANUAL,
    )

    # ── Deep-mention fields (filled by page_fetch.py second pass) ──
    #
    # body_excerpt: the actual paragraph from the page containing the
    # brand mention, ~2000 chars centered on the match. More
    # informative than the SERP snippet (which is Google's truncated
    # description). Empty when the page fetch failed or hasn't run.
    body_excerpt = models.TextField(blank=True, default="")

    # When is_linked=True, the anchor text(s) used to link to bajaj.
    # Multiple if the page has more than one link to us. Useful to
    # measure brand-name distribution ("Bajaj Allianz Life" vs new).
    anchor_texts = models.JSONField(default=list, blank=True)

    # Schema.org JSON-LD extracted from the page: Article, NewsArticle,
    # or Review entities. Lets us pull author + publisher entities
    # without re-parsing on every read.
    structured_data = models.JSONField(default=dict, blank=True)

    # Author + publisher entity strings — extracted from schema.org
    # markup or HTML meta tags. publisher_name often differs from
    # source_domain (e.g. domain=livemint.com, publisher="HT Media").
    author = models.CharField(max_length=255, blank=True, default="")
    publisher = models.CharField(max_length=255, blank=True, default="")

    # Competitor brands mentioned in the SAME page as Bajaj. Tells us
    # whether the mention is solo or part of a comparative article.
    # Comparative context is more valuable for SEO/AI-search signals.
    co_mentioned_brands = models.JSONField(default=list, blank=True)

    # Topical classification — is this mention in a finance/insurance
    # context (high-value) or random (low-value)? Lightweight LLM
    # judgement made once at write time.
    is_topical = models.BooleanField(default=True, db_index=True)
    topical_category = models.CharField(
        max_length=64, blank=True, default="",
    )

    # Page language — drives multi-lingual SEO tracking (Bajaj has
    # Hindi pages, competitors often don't).
    language = models.CharField(max_length=8, blank=True, default="")
    country = models.CharField(max_length=8, blank=True, default="")

    # Review-site numeric rating (e.g. 3.5 out of 5) when extractable
    # from schema.org Review markup. NULL for non-review sources.
    rating_value = models.FloatField(null=True, blank=True)
    rating_max = models.FloatField(null=True, blank=True)

    # Whether the page_fetch second pass has actually run on this row.
    # Lets the orchestrator skip already-enriched rows on re-runs.
    page_fetched_at = models.DateTimeField(null=True, blank=True)

    # Raw payload from the source adapter — useful for debugging and
    # for adding new fields without a migration. Per-adapter shape.
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-last_seen_at",)
        indexes = [
            models.Index(fields=["-last_seen_at"]),
            models.Index(fields=["source_tier", "-last_seen_at"]),
            models.Index(fields=["sentiment", "-last_seen_at"]),
            models.Index(fields=["brand_variant", "-last_seen_at"]),
            models.Index(fields=["source_domain", "-last_seen_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.source_domain} — {self.brand_variant} ({self.sentiment})"

