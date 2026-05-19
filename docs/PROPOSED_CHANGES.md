# Proposed Changes — Bajaj Life SEO Platform

**Date:** 2026-05-20
**Authored from chat with:** ai.marketing@bajajlife.com
**Companion doc:** `docs/PRODUCTION_READINESS_AUDIT.md` (broad audit of current state)
**This doc:** specific changes the operator has proposed during the 2026-05-20 chat session, with implementation specs and acceptance criteria.

---

## Overview

The platform is feature-complete for v1. The gap is between **what the data layer can do** and **what the operator-facing surfaces expose**. This document is the agreed roadmap to close that gap, structured in two stages:

| Stage | When | Theme |
|---|---|---|
| **Stage 1** | This week — local dev now, prod-ready by deploy | Operator velocity: on-demand competitor analysis + nightly fresh data |
| **Stage 2** | After LLM billing approved (OpenAI / Anthropic / Perplexity / xAI) | LLM-graded content audit per matched page-pair |

---

## Stage 1 — Ship This Week

### Change 1 — SerpAPI: cap results-per-query to 3 ✅ DONE

**Status:** Committed `.env` and `.env.example` on 2026-05-20.

**What changed:**

- `.env`: `SERP_API_RESULTS_PER_QUERY=3` (was 25)
- `.env.example`: documented as 10 default with a comment explaining it does NOT affect quota
- Existing wiring (`settings/base.py:272`, `serp_api.py:104`, `serp_api.py:165` (Google `num`), `serp_api.py:169` (Bing `count`)) already passes the value through unchanged

**Why this change does NOT save quota:**

SerpAPI bills **one credit per API call**, regardless of how many results you request. The `num` / `count` parameters only change response payload size. To actually save quota you'd lower one of:

| Lever | Current | Effect |
|---|---|---|
| `SERP_API_MAX_QUERIES=20` | 20 queries/run | × |
| `SERP_API_ENGINES=google,bing,duckduckgo` | 3 engines | × |
| `SERP_API_DEVICES=desktop,mobile` | 2 devices | = 120 calls/run |

→ Free tier (250/mo) = ~2 runs/month at current settings.

**Why we still made the change:** smaller payloads in the UI tables, faster JSON parsing, less storage in `GapSerpResult` rows. Top-3 is also more aligned with what an operator scans visually.

**Activation:** `docker-compose restart backend worker` picks up the new `.env`. No rebuild needed. Old cache entries auto-invalidate (cache key includes `n={results_per_query}` at `serp_api.py:298`).

---

### Change 2 — On-demand "compare us with this competitor" in chat ❌ TODO

**Status:** Not built. Underlying machinery exists in adapters; only the chat-tool wrappers are missing.

**User story:**

> In the assistant panel I type "check axismaxlife.com and compare it with us". I expect the assistant to (1) crawl axismaxlife's sitemap, (2) fetch their content + CWV, (3) compare structurally to us, (4) emit a card with the deltas.

**Gap today:**

The chat tools in `backend/apps/seo_ai/chat/tools.py` expose 9 functions. None of them can take an arbitrary competitor domain and crawl it on demand. `get_competitor_gap()` runs the full pipeline but **auto-discovers** rivals via SEMrush — the operator can't say "use this specific rival".

**Implementation — exactly 2 new tools:**

#### Tool A: `crawl_competitor_domain`

**File:** `backend/apps/seo_ai/chat/tools.py` (additive)

**Behaviour:** Given a domain, kick off a Celery task that runs the existing `SitemapXMLAdapter` + `CompetitorCrawler.fetch_pages()` + `enrich_with_cwv()` + `_build_profile()`. Returns a `job_id` immediately because the crawl + PSI takes ~30-60 seconds.

```python
@_safe
def crawl_competitor_domain(domain: str) -> dict[str, Any]:
    """Discover, crawl, and PSI-score any competitor domain. Async —
    returns a job_id; ask back in ~60 sec for results."""
    from ..tasks import crawl_competitor_task

    job = crawl_competitor_task.delay(domain)
    return {"ok": True, "job_id": str(job.id), "domain": domain,
            "estimated_seconds": 60,
            "message": "Crawl started. Use get_competitor_profile(job_id) "
                       "in ~60 sec to fetch results."}
```

**New Celery task** in `backend/apps/seo_ai/tasks.py`:

```python
@shared_task(max_retries=0, time_limit=300)
def crawl_competitor_task(domain: str) -> dict:
    from .adapters.competitor_crawler import CompetitorCrawler
    from .adapters.sitemap_xml import SitemapXMLAdapter
    from .gap_pipeline.deep_crawl import _build_profile, _CWV_PAGES_PER_COMPETITOR
    # ... discover URLs, crawl, enrich, build profile, persist to a new
    # OnDemandCompetitorProfile model
```

**New persistence model** — `OnDemandCompetitorProfile(domain, profile_json, fetched_at, requested_by)`. Cached 24h so back-to-back queries about the same competitor reuse.

#### Tool B: `compare_with_competitor`

**File:** same.

**Behaviour:** Given a domain, pull (a) the on-demand profile from Tool A and (b) our profile from the latest gap pipeline run, then run the existing `_PROFILE_GAP_BUILDERS` from `comparison.py` to produce findings.

```python
@_safe
def compare_with_competitor(domain: str) -> dict[str, Any]:
    """Compare us vs a specific competitor. Profile must exist
    (call crawl_competitor_domain first if needed)."""
    from ..gap_pipeline.comparison import _PROFILE_GAP_BUILDERS
    from ..models import OnDemandCompetitorProfile, GapDeepCrawl, GapPipelineRun

    their = OnDemandCompetitorProfile.objects.filter(domain=domain).first()
    if not their:
        return {"ok": False, "error": "no profile — call crawl_competitor_domain first"}

    us = GapDeepCrawl.objects.filter(is_us=True).order_by("-id").first()
    if not us:
        return {"ok": False, "error": "no baseline — run gap pipeline first"}

    rows = [b(us.profile, [their.profile_json]) for b in _PROFILE_GAP_BUILDERS]
    rows = [r for r in rows if r is not None]
    return {"ok": True, "domain": domain, "findings": [asdict(r) for r in rows]}
```

#### Tool schemas

Append two new entries to `TOOL_SCHEMAS` in `tools.py` so the LLM knows when to call them. System prompt at `chat/system_prompt.py` should be updated with usage guidance:

> When the user asks to compare with a *named* competitor (vs the auto-discovered top-10), call `crawl_competitor_domain` first, wait, then `compare_with_competitor`.

#### Frontend

The chat surface already renders structured tool results via `ToolCallChip.tsx`. Add a new card type `competitor_compare` to `CompetitorDeltaCard.tsx` that takes `compare_with_competitor`'s output shape.

**Estimate:** 4-6 hours backend + 1-2 hours frontend.

**Acceptance criteria:**

- [ ] User types "compare us with axismaxlife.com" → assistant kicks off `crawl_competitor_domain`, reports back in ~60 sec
- [ ] Follow-up "show me the comparison" → assistant calls `compare_with_competitor`, emits inline card with findings sorted by severity
- [ ] Cached: repeating the same query within 24h returns instantly from `OnDemandCompetitorProfile`
- [ ] Handles unreachable domains gracefully: 404 sitemap / network error → `{"ok": false, "error": "..."}` returned to LLM, which apologises

---

### Change 3 — Nightly crawler cron via Celery Beat ❌ TODO (prod only)

**Status:** Not built. Celery is wired (`config/celery.py`), Redis broker is running, but **no Beat schedule exists** (`config/celery.py` tries to import a non-existent module and silently falls through).

**User story:**

> Every night at 00:00 IST, the crawler runs end-to-end against our own site so the morning operator sees fresh data: page counts, console errors, CWV scores.

**Why deferred for local dev:**

Operator says "for now it is local, so we don't need to update it every night" — so this lands when we configure prod deployment, not now. The code change is small but pointless without an always-running worker.

**Implementation:**

#### Beat schedule

**File:** `backend/config/celery.py`

```python
app.conf.beat_schedule = {
    "nightly-full-crawl": {
        "task": "apps.crawler.tasks.run_nightly_crawl",
        "schedule": crontab(hour=0, minute=0),   # 00:00 IST
        "options": {"expires": 6 * 3600},        # don't queue if missed by 6 hr
    },
    "weekly-gap-pipeline": {
        "task": "apps.seo_ai.tasks.run_gap_pipeline_weekly",
        "schedule": crontab(hour=2, minute=0, day_of_week="sunday"),
    },
}
app.conf.timezone = "Asia/Kolkata"
```

#### Nightly crawl task

**File:** `backend/apps/crawler/tasks.py` (new file — currently no `tasks.py` in the crawler app)

```python
from celery import shared_task
from .services import crawler_service

@shared_task(time_limit=4*3600, max_retries=0)
def run_nightly_crawl():
    """Fresh full crawl, runs at 00:00 IST. Wipes state + CSVs first
    (same as the manual Start button), then runs Phase 1 + 2 + 3."""
    ok, msg = crawler_service.start()
    return {"ok": ok, "message": msg}
```

#### Weekly gap pipeline task

Already exists as `apps.seo_ai.tasks.run_gap_pipeline_task` — wrap it in a no-arg `run_gap_pipeline_weekly` that picks our default domain.

#### Why two separate schedules

| Task | Frequency | Why |
|---|---|---|
| Full crawler | Daily 00:00 | Cheap, our content changes daily |
| Gap pipeline | Weekly Sun 02:00 | Heavy: SEMrush units + competitor crawls × N rivals. Once a week is enough to spot competitor moves. |

**Estimate:** 1 hour backend + needs prod Celery worker running.

**Acceptance criteria:**

- [ ] `docker-compose ps` shows `seo-worker-1` and `seo-beat-1` (new beat service) running
- [ ] At 00:00 IST a fresh `crawl_results.csv` is written
- [ ] At 02:00 Sun IST the gap pipeline runs and `GapPipelineRun.created_at` shows weekly cadence
- [ ] Missed schedules (worker down) don't pile up — `expires` clears them

#### Compose addition

Add a `beat` service to `docker-compose.yml`:

```yaml
beat:
  build: { context: ./backend }
  command: celery -A config beat -l info -s /tmp/celerybeat-schedule
  env_file: [.env]
  environment:
    DB_HOST: db
    CELERY_BROKER_URL: redis://redis:6379/0
  depends_on: [db, redis, worker]
```

---

### Change 4 — Compose source-mount for dev velocity ❌ OPTIONAL

**Status:** Not built. Currently every code change requires `docker-compose build backend worker`.

**Proposed addition to `docker-compose.yml`:**

```yaml
backend:
  volumes:
    - ./backend/data:/app/data
    - ./backend/reports:/app/reports
    - ./backend:/app          # ← new: source code live-mount
```

**Tradeoff:**

- ✅ Pro: code edits land instantly, `runserver` auto-reloads, no rebuild needed
- ⚠️ Con: prod images must NOT have this mount (they should bake the source in)
- Suggested: keep the mount in `docker-compose.yml` (dev) and document a `docker-compose.prod.yml` override that drops it

**Estimate:** 5 minutes.

---

## Stage 2 — After LLM Billing Approved

### Change 5 — Audit agent: LLM-graded matched page-pairs

**Status:** Deferred. Requires OpenAI / Anthropic / Perplexity / xAI billing set up — keys currently empty in `.env` (see `PRODUCTION_READINESS_AUDIT.md` §4).

**User story:**

> For each of our top pages, pair it to the topically-closest competitor page, ask an LLM "which is more SEO-optimised and why", and surface a side-by-side audit so I can see exactly what to fix in our content.

**Pre-work to do NOW (before LLM billing approved):**

These pieces are LLM-free and can be merged today without billing:

1. **Page-pair matcher** — `backend/apps/seo_ai/gap_pipeline/page_pairing.py`
   - Input: our top 200 AEM pages + 10 competitors × 50 sampled pages
   - Pairing strategy: URL slug similarity + title cosine + SEMrush head-keyword overlap
   - Output: ~200 `GapPagePair(run, our_url, their_url, similarity_score, our_topic, their_topic)` rows

2. **New models** in `backend/apps/seo_ai/models.py`:
   - `GapPagePair` — the matched pairs
   - `GapAuditFinding` — LLM verdict per pair (winner, score, strengths, gaps, recommendations) — keep nullable so the row exists once paired, even before LLM grading

3. **Scoring rubric** — `backend/apps/seo_ai/agents/content_audit_prompts/v1.md`
   - What dimensions the LLM grades: E-E-A-T, intent match, freshness, structural extractability, schema coverage, internal links, citation worthiness
   - Versioned in markdown so prompt edits are reviewable

4. **Stub adapter** — `backend/apps/seo_ai/adapters/llm_audit.py`
   - Same gating pattern as the AI-visibility probes: raise `AdapterDisabledError` when no LLM key is set
   - Code merges today, flips live the moment a key lands in `.env`

**Implementation when billing lands:**

5. **Audit agent** — `backend/apps/seo_ai/agents/content_audit_agent.py`
   - For each `GapPagePair`, fetch both page bodies, build the rubric prompt, call Groq (default — already paid) + optionally a premium LLM for spot-checks
   - Persist `GapAuditFinding`
   - Run as a separate gap-pipeline stage (Stage 7)

6. **Frontend tab** — new "Content Audit" tab on the Competitors page
   - Table of pairs sortable by gap severity / LLM score delta
   - Click-through opens a side-by-side view: our content | their content | LLM verdict + recommendations

**Estimate:** 2 days pre-work (matcher + models + stub) + 3 days full agent + 2 days frontend = ~1 week total.

**Acceptance criteria when fully shipped:**

- [ ] Every gap-pipeline run produces ~200 page pairs
- [ ] Stage 7 grades all pairs in <5 min using Groq (gpt-oss-120b)
- [ ] "Content Audit" tab shows: % of pairs we won, % of pairs we lost, top-10 worst gaps
- [ ] Drilling into a "lost" pair shows: "their lead paragraph defines the term in 65 words, ours buries it in marketing copy. Recommendation: rewrite the first paragraph as a 50-word definition."

---

## Cross-Cutting: What This Plan Does NOT Cover

To be honest about scope, these things are out of this proposals doc — they belong elsewhere:

- **DevOps / infrastructure setup** — Sentry, CORS, STATIC_ROOT, backups, auth. Covered in `PRODUCTION_READINESS_AUDIT.md` §7 checklist.
- **Trend tracking / weekly digest email** — listed in audit §9 as the #1 missing feature for "monitor whether SEO is improving", but not yet a hard commitment. Decide after Stage 1 ships.
- **Replace CSV with Postgres** — audit §9 item 16. Larger refactor, not in this plan.
- **Hardcoded value cleanup** — audit §5. Six small env-ifications, do them opportunistically.

---

## Open Questions to Resolve Before Stage 1 Starts

1. **What's the prod LLM bill budget?** — affects how aggressive Stage 2 can be (cheap Groq audit on 200 pairs vs expensive premium-LLM cross-check on the worst 20)
2. **Where does the on-demand profile cache live?** — Redis (fast, ephemeral) or Postgres (persistent across restarts but slower)? My pick: Postgres `OnDemandCompetitorProfile` model with a 24h TTL filter — survives container restarts.
3. **Which competitors should the chat default to surfacing in suggestions?** — auto-pick from `GapCompetitor` table's top 5, or hard-code an India-insurance allow-list? Pick: auto-pick from SEMrush so the list adapts when rivals shift.
4. **Should nightly crawl also trigger a re-grade?** — runs the agent stack against fresh data. Cheaper said than done — depends on Groq quota. Default: no, regrade weekly with the gap pipeline.

---

## Implementation Order (Recommended)

If we ship in 2-3 weeks:

```
Week 1  ┬─ Stage 1 / Change 2: chat tools (2 new tools + Celery task + model)
        └─ Stage 2 pre-work: page_pairing.py + models + prompt rubric
Week 2  ┬─ Stage 1 / Change 3: Celery Beat + nightly crawler task
        └─ Stage 1 / Change 4: source-mount in compose (5 min)
Week 3  ┬─ Stage 2 full: audit agent + frontend tab (waits on LLM billing approval)
        └─ Cleanup: address audit §7 checklist items (Sentry, CORS, etc.)
```

If billing approval slides, the Stage 1 items still ship on Week 1-2. Stage 2 unblocks the moment billing lands.

---

## Sign-off Section

When each change ships, add a line here so we have a definitive log:

| Change | Status | Commit | Date |
|---|---|---|---|
| 1. SerpAPI top-3 | ✅ DONE | pending push | 2026-05-20 |
| 2. Chat tools (compare-with-competitor) | ⏳ TODO | | |
| 3. Nightly crawler cron | ⏳ TODO | | |
| 4. Source-mount in compose | ⏳ TODO | | |
| 5. Audit agent (Stage 2) | ⏳ DEFERRED — needs LLM billing | | |

---

*Doc author: Claude Opus 4.7 (1M context). Captures decisions made in chat with the operator on 2026-05-20. No code executed during this drafting pass — all references are to existing files in the repo at commit `d5f1339`.*
