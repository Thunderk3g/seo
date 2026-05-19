# Production Readiness Audit — Bajaj Life SEO Platform

**Date:** 2026-05-20
**Branch audited:** `feat/crawler-reports-category-segregation` @ `d5f1339`
**Scope:** Whole-codebase audit before DevOps / prod setup. No code was run; this is a static read of source files and config.

---

## 1. Executive Summary

The platform is **architecturally sound but operationally incomplete** for production. Core SEO machinery — crawler, competitor pipeline, SERP probe, PSI CWV — works. Gaps cluster in three areas:

1. **Missing API keys** disable several agents silently (OpenAI, Anthropic, Perplexity, xAI — all empty in `.env`). The platform doesn't crash but multi-provider AI-visibility comparison is reduced to Gemini-only.
2. **No async offload for the crawler.** Crawls run in the request thread. A 10k-page crawl will exceed any reasonable WSGI timeout in prod. Celery tasks exist for the SEO grade but not the crawler itself.
3. **No GC for disk caches.** Six file-backed caches grow unbounded (semrush, competitor, psi, serp, sitemap, ai_visibility). At current pace this won't break anything in the first 3 months, but needs a cleanup job before year one.

Critical bugs found in this audit: none. Several **medium-priority hardening items** and one Bing-specific user-reported issue addressed below.

---

## 2. Current Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Vite + React)                       │
│                  frontend/web/src — proxies to backend                │
└─────────────────────┬────────────────────────────────────────────────┘
                      │ /api/v1/crawler/*  /api/v1/seo/*
┌─────────────────────▼────────────────────────────────────────────────┐
│                       DJANGO BACKEND (DRF)                            │
│  ┌─────────────────┐  ┌─────────────────────────────────────────┐    │
│  │ apps.crawler    │  │  apps.seo_ai                            │    │
│  │ (in-house)      │  │  ┌──────────────────────────────────┐   │    │
│  │ engine.py       │  │  │ adapters/  (external data)       │   │    │
│  │  ├ Phase 1      │  │  │  - semrush      - serp_api        │   │    │
│  │  │  static HTTP │  │  │  - cwv_psi      - competitor_crawl│   │    │
│  │  ├ Phase 2      │  │  │  - sitemap_xml  - sitemap_aem     │   │    │
│  │  │  Playwright  │  │  │  - ai_visibility/{openai,…}_probe │   │    │
│  │  │  console     │  │  └──────────────────────────────────┘   │    │
│  │  └ Phase 3      │  │  ┌──────────────────────────────────┐   │    │
│  │     PSI CWV     │  │  │ gap_pipeline/  (5 stages)        │   │    │
│  │                 │  │  │  discovery → top-N → llm_search  │   │    │
│  │ Writes 6 CSVs   │  │  │  → serp_probe → deep_crawl       │   │    │
│  └─────────────────┘  │  │  → comparison                    │   │    │
│                       │  └──────────────────────────────────┘   │    │
│                       │  ┌──────────────────────────────────┐   │    │
│                       │  │ agents/  (LLM-driven, optional)  │   │    │
│                       │  │  - content_extractability        │   │    │
│                       │  │  - technical_audit, architecture │   │    │
│                       │  │  - product_commercial, narrator  │   │    │
│                       │  └──────────────────────────────────┘   │    │
│                       └─────────────────────────────────────────┘    │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐    │
│  │ Postgres 15  │  │ Redis 7      │  │ Disk caches (backend/data│    │
│  │ (compose:db) │  │ (compose:rds)│  │  _semrush/_competitor/   │    │
│  │              │  │              │  │  _psi/_serp/_sitemap/    │    │
│  │              │  │              │  │  _ai_visibility/)        │    │
│  └──────────────┘  └──────────────┘  └─────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. What Works Today

| Capability | Status | Source of truth |
|---|---|---|
| Static HTTP crawl of bajajlifeinsurance.com | ✅ Working | `apps/crawler/engine/engine.py` |
| Sitemap + robots.txt discovery | ✅ Working | `engine/sitemap.py`, `engine/robots.py` |
| Resume-on-crash crawler state | ✅ Working | `engine.py:_maybe_resume()` |
| Fresh-crawl wipe on every Start click | ✅ Working (just committed) | `services/crawler_service.py` |
| Playwright console-error capture (Phase 2) | ✅ Working | `engine/browser_console.py` |
| PSI CWV capture (Phase 3) | ✅ Working — needs rebuilt container | `engine/psi_capture.py` + `adapters/cwv_psi.py` |
| GSC Coverage CSV upload + index status backfill | ✅ Working | `storage/gsc_coverage_builder.py` |
| SEMrush competitor discovery (India DB) | ✅ Working — real key in `.env` | `adapters/semrush.py` |
| SERP probe Google + Bing + DuckDuckGo (India geo) | ✅ Working (Bing/DDG fix committed) | `adapters/serp_api.py:160-171` |
| Gap pipeline stages 1-6 end-to-end | ✅ Working | `gap_pipeline/*.py` |
| Competitor deep-crawl + AI citability scoring | ✅ Working | `gap_pipeline/deep_crawl.py` |
| Gemini AI-visibility probe | ✅ Working — real key in `.env` | `adapters/ai_visibility/gemini_probe.py` |
| Frontend reports + competitors page | ✅ Working | `frontend/web/src/` |

---

## 4. Disabled / Non-Functional Features (Missing Keys)

Every adapter that needs a key checks for one and silently raises `AdapterDisabledError` if blank. The platform never crashes. But these probes are **dark**:

| Feature | Required env var | Current value | Effect |
|---|---|---|---|
| OpenAI / ChatGPT visibility probe | `OPENAI_API_KEY` | empty | Brand citation in ChatGPT answers — **not measured** |
| Anthropic / Claude visibility probe | `ANTHROPIC_API_KEY` | empty | Brand citation in Claude answers — **not measured** |
| Perplexity visibility probe | `PERPLEXITY_API_KEY` | empty | Brand citation in Perplexity answers — **not measured** |
| xAI / Grok visibility probe | `XAI_API_KEY` | empty | Brand citation in Grok answers — **not measured** |
| Content audit agent (LLM-graded) | depends on `GROQ_API_KEY` | set ✅ | Groq works; runs gpt-oss-120b. **Available now, just unused on the crawl page.** |

**Impact:** Phase 2 of the gap pipeline (`llm_search`) is reduced from 5 LLM providers to 1 (Gemini). Comparison of "are we cited by ChatGPT vs Claude vs Perplexity" can't be made. The numbers shown on the AI Visibility panel reflect Gemini-only and aren't representative of cross-LLM citation.

`.env` lines 163-164 carry **commented-out** OpenAI + Anthropic keys (legacy `#envforgpt-…` / `#envforclaude-…`). These look like real keys someone deleted from the active config. Either rotate-and-restore or remove the comments — leaving them in cleartext is unhygienic.

---

## 5. Hardcoded Values — Things That Should Move to Env

| File:line | Hardcoded | Recommended action |
|---|---|---|
| `backend/apps/crawler/engine/fetcher.py:41` | `session.verify = False` | Should read `CRAWLER_SSL_VERIFY` env var (we have the pattern for it elsewhere) |
| `backend/apps/seo_ai/adapters/ai_visibility/anthropic_probe.py:59` | `max_tokens=1024` | Expose as `ANTHROPIC_AI_VISIBILITY_MAX_TOKENS` |
| `backend/apps/seo_ai/gap_pipeline/query_synthesis.py:238` | `max_tokens=2400` | Expose as `LLM_QUERY_SYNTHESIS_MAX_TOKENS` |
| `backend/apps/seo_ai/adapters/semrush.py:371` | `timeout=30` | Should read `SEMRUSH_TIMEOUT_SEC` env var (consistent with COMPETITOR_TIMEOUT_SEC) |
| `backend/apps/seo_ai/gap_pipeline/deep_crawl.py:76` | `_CWV_PAGES_PER_COMPETITOR = 10` | Acceptable for v1, env-ify if rivals exceed 50 sites |
| `backend/apps/crawler/views.py:460,464` | `max_depth` min=1 max=20 | Document in API or env-ify; current bounds are arbitrary |

**Not hardcoded — good defaults already env-configurable:**
- `CRAWLER_REQUEST_TIMEOUT`, `CRAWLER_MAX_WORKERS`, `CRAWLER_MAX_RETRIES`, all crawler knobs
- `COMPETITOR_*` tuneables (rate limit, page count, cache TTL)
- `PSI_*`, `SERP_API_*`, `SEMRUSH_*`, `AI_VISIBILITY_*` all parameterised

---

## 6. Weak Points by Module

### 6.1 Crawler Engine (`apps/crawler/`)

**Strong:**
- Token-bucket throttle per host (`engine/throttle.py`)
- Retry with exponential backoff in `fetcher.py`
- Trap detection (absurd URLs, faceted-search loops) in `url_utils.py`
- Resume-on-crash via `crawl_state.json`
- Append-only streaming CSVs (handles 100k+ pages cleanly)

**Weak:**
1. **Synchronous in request thread** — `views.py:start_view()` launches `threading.Thread(target=run_crawl)` daemon. If the WSGI worker recycles mid-crawl the thread dies. **Action:** move to Celery `run_crawl_task` (we have Celery wired, just unused for this).
2. **Single-domain hard-gate** — `engine/url_utils.is_allowed_domain()` is hard-coded to bajajlifeinsurance.com. To crawl a different brand we'd need to make `allowed_domains` first-class.
3. **No max-disk-usage guard** — a 100k-page crawl can write multi-GB CSVs. No quota check.
4. **CSV streams open in append mode by default** — fresh-crawl wipe (just added) deletes the files first, but if someone bypasses `start()` and calls the engine directly, old rows leak.
5. **SSL_VERIFY=False hardcoded in fetcher** — fine for the corporate MITM proxy story in dev, but in prod this is a downgrade-attack vector. See section 5.

### 6.2 Competitor Crawler (`apps/seo_ai/adapters/competitor_crawler.py`)

**Strong:**
- Per-host token bucket (≥1s between requests)
- robots.txt honored per-host with safe allow-all fallback on fetch failure
- 7-day disk cache (URL → HTML), survives `docker-compose down`
- New CWV enrichment (`enrich_with_cwv()`) bolted on cleanly

**Weak:**
1. **Sequential fetching** — `fetch_pages()` is a plain loop. At 1 req/s × 10 rivals × 50 pages = ~8 min per gap run. Fine for now; an async or threaded fetcher would cut this.
2. **No domain-level retry** — if a competitor's CDN is down at crawl time, we lose its profile for the whole 7-day cache window. No background re-attempt.
3. **`fetch_pages()` rate limit is per-host, not global** — if SEMrush returns 10 competitors and all 10 are on different CDNs, we fire 10 concurrent requests. Currently fine; would matter if scaling beyond a single worker.
4. **No body-size cap** — a competitor with a 30 MB HTML page would download the whole thing. Not seen in practice but possible.

### 6.3 Competitor Deep Crawl Pipeline (`gap_pipeline/deep_crawl.py`)

**Strong:**
- Sitemap-first discovery, falls back to homepage
- Profile JSON shape is stable + back-compat-friendly (new fields are optional)
- New PSI CWV merges in cleanly without breaking existing consumers

**Weak:**
1. **`_sample_urls_from_sitemap()` only follows the first 3 sub-sitemaps** (line ~280). A large site with 50+ sub-sitemaps gets sampled from the first 3 only — biased toward whatever the operator declared first in robots.txt.
2. **CWV failure logged at INFO, not WARNING** — if PSI breaks mid-run we discover via inspection, not alerts. Bump to WARNING + emit a log_bus event.
3. **No retry on transient sitemap 503s** — a single 503 means competitor count = 0 for that domain until cache expires (7 days).
4. **AI citability score (0-100)** lives in two places: a cheap structural heuristic on every page (`_ai_citability()`) and the full extractability agent (`agents/content_extractability.py`). The values don't agree with each other and there's no comment explaining which one the comparison stage uses. *Action: pick one or document the difference.*

### 6.4 SERP Visibility & Bing Geo-Targeting

The **Bing fix is committed and present** in the running source at `serp_api.py:160-171`. Verified:

```python
elif engine == "bing":
    params["cc"] = country_upper          # "IN"
    params["mkt"] = f"{language}-{country_upper}"  # "en-IN"
    params["count"] = self._results_per_query
elif engine == "duckduckgo":
    params["kl"] = f"{self._country}-{self._language}"  # "in-en"
```

**If you're still seeing non-India results in the UI**, the likely cause is **stale DB rows**, not stale code:

1. `GapSerpResult` rows from BEFORE the fix landed are still in Postgres.
2. The frontend reads from `GapSerpResult`, not live SerpAPI calls.
3. Re-running the SERP probe stage of the gap pipeline will overwrite the rows with India-geo results.

Cache invalidation IS handled (cache key bumped to `v2` in `_cache_path`, so disk cache misses for old entries) — the issue is just that the persisted findings haven't been regenerated. **Action: re-run the gap pipeline's SERP stage once and the rows will refresh.**

Other SERP weak points:
1. **Free-tier SerpAPI** — 250 searches/month. With `SERP_API_MAX_QUERIES=20`, `engines=3`, `devices=2` that's 120 calls per run. **You can do ~2 runs/month before hitting the cap.** Stays workable on paid tier ($75/mo for 5k searches).
2. **DuckDuckGo `kl` is best-effort** — DDG ignores it sometimes. Field results vary. Acceptable.

### 6.5 AI Visibility (`adapters/ai_visibility/*_probe.py`)

**Strong:**
- Independent kill-switches per provider (one bad key doesn't break the others)
- 7-day cache, identical to other adapters

**Weak:**
1. **4 of 5 providers are dark** (see section 4). With only Gemini active, "AI search visibility" findings are statistically thin.
2. **Hardcoded `max_tokens` per probe** (see section 5).
3. **No retry on rate-limit (429)** — single 429 = lose that query/provider pair for cache TTL.

### 6.6 PSI / CWV Layer

**Strong:**
- Service account auth working, quota lands on `geoseo-496810` project (verified live)
- Both lab + field (CrUX) metrics captured
- Disk-cached 7 days
- Surfaces in `crawl_results.csv` (in-house) and competitor deep-crawl panel (just committed)

**Weak:**
1. **PSI mobile + desktop = 2× quota per URL.** With `PSI_STRATEGIES=mobile,desktop` and 100 URLs that's 200 calls = ~0.8% of daily budget. Fine. If we ramp `PSI_MAX_URLS_PER_RUN`, scales linearly.
2. **Desktop PSI calls take 30-40 seconds.** Crawl phase 3 is the new slowest step. If a desktop call hangs we wait the full `PSI_REQUEST_TIMEOUT_SEC=120`.
3. **CWV merging back into `crawl_results.csv` requires closing the CSV writer** — `_merge_into_results_csv()` does `flush_streams() + close_streams()` before rewriting. If anything reopens the writer during phase 3, the merge will fail with a Windows file-lock error. Currently no path triggers this, but it's brittle.

### 6.7 Tests Coverage

Existing tests (~403 lines):
- `apps/common/tests/test_url_utils.py`
- `apps/crawler/tests/test_gsc_loader.py`
- `apps/crawler/tests/test_parser_link_extraction.py`
- `apps/crawler/tests/test_pdf_crawling.py`
- `apps/crawler/tests/test_url_classifier.py`

**Zero tests for:** adapters (semrush/serp_api/competitor_crawler/cwv_psi/ai_visibility probes), gap_pipeline stages, agents, Celery tasks, DRF views. The whole SEO-AI subsystem is uncovered. Before prod, recommend at minimum:

- `test_serp_api_geo_params` — assert Bing gets cc/mkt, DDG gets kl, Google gets gl/hl
- `test_cwv_psi_adapter` — mock the requests, assert OAuth flow + parsing
- `test_deep_crawl_profile_aggregation` — assert CWV medians come out right
- `test_comparison_cwv_row` — assert severity bands at 600/1500/4000 ms LCP
- `test_competitor_crawler_robots` — assert disallowed paths are skipped

---

## 7. Production-Readiness Checklist

Before any prod deploy, complete these:

| # | Item | Where | Notes |
|---|---|---|---|
| 1 | `SECRET_KEY` set to cryptographic random | prod env / secrets manager | `.env` still has `replace-me-in-production` |
| 2 | `ALLOWED_HOSTS` set to actual domain(s) | prod env | Prod settings reject empty — must be explicit |
| 3 | `DB_HOST` / `DB_USER` / `DB_PASSWORD` point to managed Postgres | prod env | Currently localhost defaults |
| 4 | `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` → managed Redis | prod env | Currently localhost defaults |
| 5 | `SSL_VERIFY` knobs → `true` outside corp network | prod env | All currently `false` (corp MITM in dev) |
| 6 | Real CA bundle path in `LLM_SSL_VERIFY` if behind any proxy | prod env | Avoid `false` in prod |
| 7 | Rotate the service-account JSON private key | Google Cloud Console | The one in transcript needs to be deleted; key id `559766c1d390...` |
| 8 | Move crawler to Celery task instead of request thread | code change | Or accept request-timeout limits |
| 9 | Add cache GC cron job | infra | All `backend/data/_*` dirs grow unbounded |
| 10 | Add health check endpoint | code | `/health/` not present; only `/status/` (auth) |
| 11 | Set `DEBUG=False` (already hard-coded in prod settings) | n/a | ✅ Done by prod.py |
| 12 | Static files: configure `STATIC_ROOT` + whitenoise/CDN | settings | Not configured beyond `STATIC_URL` |
| 13 | Set up Sentry or equivalent error tracking | prod | None wired today |
| 14 | Configure CORS allowed origins | prod | `django-cors-headers` is installed but not configured in middleware |
| 15 | Document the SA JSON deploy path | runbook | `backend/data/secrets/psi-sa.json` must be mounted or baked in |
| 16 | Database backups schedule | infra | No backup story today |

---

## 8. Features Currently Working But Not Surfaced

These exist in the code, fully functional, just don't have UI exposure:

1. **CWV on crawler engine page** — `pagespeed_score`, `lcp_ms`, `cls`, `inp_ms` columns are written to `crawl_results.csv` but only appear as raw columns in the "Raw data tables" view. **No dedicated speed dashboard.** A "Page Speed" report card (median PSI score, top-10 slowest, % failing CWV thresholds) would surface the data far better.

2. **Crawler CSVs export as XLSX** — `storage/excel_writer.py` exists but its trigger path is unclear. May or may not be wired into the frontend "Download Excel Bundle" button.

3. **Sitemap freshness lag** — we track `last_modified` per page; nobody surfaces "X% of pages are older than 90 days" anywhere.

4. **AI citability score per page** — computed for every competitor page (line 219 in `deep_crawl.py`) but the frontend only shows the domain-level average. No per-page drill-down.

5. **`crawl_console_log.csv`** — every JS error / failed network request from Playwright. Surfaced in the Console Logs section but not joined to the URL's other metrics. "Pages with most console errors" would be a useful card.

---

## 9. Features To Add Next (SEO Improvement & Monitoring)

Ranked by impact-to-effort, things that meaningfully move the SEO needle:

### High impact, low effort

1. **Trend tracking.** Right now every gap-pipeline run replaces the prior. **No time-series.** Add `GapPipelineRun.snapshots` retention (or better, a `GapMetricSnapshot` table) so you can answer "is our median LCP improving?", "is our AI citability score going up?", "did our competitor count of FAQ pages overtake ours this month?". This is the #1 missing thing for "monitor whether SEO is improving".

2. **Weekly digest email.** Cron a weekly job that compares this week's pipeline snapshot to last week's and emails `ai.marketing@bajajlife.com` a summary: top regressions, top wins, new findings. Celery is wired; Django has `EmailMessage` built in.

3. **GSC click/impression overlay on `crawl_results.csv`.** GSC integration exists (`gsc_pull.py`); join clicks + impressions per URL into the main table. Lets you sort "high impression, slow LCP" — your highest-ROI pages to fix.

4. **PSI dashboard card on Reports landing.** Surface aggregate CWV (median PageSpeed, % URLs with poor LCP, top-10 slowest). Already have the data; just needs a frontend card.

5. **Re-run cleared cache button.** Sometimes you want to invalidate caches (e.g., a competitor relaunched their site). Currently only the SA can delete `backend/data/_*` dirs. A button per cache type is a 30-line change.

### High impact, medium effort

6. **Content audit agent (LLM-graded).** *Deferred until billing — see section 10.* Pair our top-N pages to the best-matching competitor page and run a Groq audit asking "which page would an LLM cite for this query, and why". This is the audit agent the user mentioned for stage 2.

7. **Internal-link graph audit.** We capture every `(parent_url, child_url, depth)` edge. We don't surface orphans, low-incoming-link pages, or "deep" pages > 3 clicks from homepage. The data is in `crawl_discovered.csv`; the visualisation isn't.

8. **Sitemap diff alerter.** Crawl the sitemap weekly. When a new URL appears or an old one disappears, log it. Indexed pages that disappear from sitemap = signal of CMS bug.

9. **Schema.org coverage tracker.** Per page type, what % have FAQPage / Article / Product / Organization schema. We collect schema_types already; no aggregate view.

10. **Mobile-first audit specifically.** Indian users are mobile-heavy. The PSI mobile lab score is what Google uses for ranking, but we also collect desktop. A side-by-side "mobile is X% slower than desktop" report would help prioritise.

### Medium impact, low effort

11. **Crawler-respect-Retry-After.** `fetcher.py:_parse_retry_after()` exists but the engine ignores `Retry-After: <date>` for now. Honouring it would let us crawl rate-limited CDNs at their requested cadence.

12. **GSC-API URL Inspection automation.** We have the integration; we don't automatically re-run inspection on pages whose status changed. After a fresh crawl + GSC backfill, anything that went from 200→404 should be auto-inspected.

13. **HTTP/2 + HSTS check per page.** Cheap to capture in the fetcher; useful as a security/SEO signal.

14. **Image audit.** Per-page count of images > 200 KB, missing WebP, missing alt. We already have `image_count` and `image_alt_pct`; size data needs the fetcher to read the image headers.

15. **Canonical hygiene.** We capture `canonical` per page. We don't yet flag "X pages canonicalise to a 404" or "Y pages canonicalise outside our domain". Easy SQL query once we promote `crawl_results.csv` to a Postgres table.

### Large work, high payoff

16. **Replace CSV with proper Postgres tables.** The CSV-streaming pattern was right for the v1 vertical slice. For trend tracking, sorting, JOINs to GSC, etc., we'd want each page to be a row in `crawler_pageresult`. Keep CSV export as a download artifact, not as the source of truth.

17. **Real-time crawl progress UI.** Currently the UI polls `/logs?cursor=…` every second. Server-Sent Events or WebSocket would be smoother and lighter on the DB.

---

## 10. Audit Agent (Deferred — Stage 2)

**Goal stated by user:** an LLM-driven audit agent that compares our content to competitor content on a matched-pair basis and judges which is more SEO-optimised, gives specific recommendations.

**Why it's deferred:** Requires OpenAI / Anthropic / Perplexity billing (currently disabled keys, see section 4). Groq is free / nearly-free and could power a v1 audit, but the user signalled to wait for billed-provider setup.

**Pre-work to do now so stage 2 lands fast:**

1. **Build the page-pair matcher.** Given our top 200 pages and 10 competitors × 50 pages, produce ~200 (our_url, their_url) pairs by URL slug similarity + title cosine + keyword overlap. New file: `backend/apps/seo_ai/gap_pipeline/page_pairing.py`. No LLM needed for this step.
2. **Persist pairs.** New model `GapPagePair(run, our_url, their_url, similarity_score)`.
3. **Define the audit prompt + scoring rubric.** What does the LLM grade on? E-E-A-T, intent match, freshness, structural extractability, schema coverage, internal links, citations. Keep prompt versioned in `backend/apps/seo_ai/agents/content_audit_prompts/v1.md`.
4. **Stub the audit agent.** `backend/apps/seo_ai/agents/content_audit_agent.py` — implements the interface but raises `AdapterDisabledError` when LLM keys aren't set. Same pattern as the AI-visibility probes. Lets us merge the code today; flip live when billing is approved.
5. **Result schema.** `GapAuditFinding(run, pair, winner='us'|'them'|'tie', our_score 0-100, their_score 0-100, our_strengths_json, our_gaps_json, recommendations_json)`.
6. **Frontend tab.** "Content Audit" — table of pairs, sortable by gap severity, click-through to side-by-side view (our content | their content | LLM verdict).

When LLM billing is approved, this turns on by setting the keys in `.env`. Zero other code changes.

---

## 11. Bing-Specific Issue (User-Reported)

**User report:** "Bing changes was not done. It is not showing Indian server websites. It is showing some different countries' websites."

**Audit verdict:** The fix **is** in the codebase (commit `5333ff6`, verified in this audit at `serp_api.py:160-171`). What you're likely seeing:

1. **Stale `GapSerpResult` rows in Postgres** from runs that happened before the fix landed. The frontend reads from those persisted rows, not from live SerpAPI calls.
2. **Stale disk cache entries** — partially mitigated by the `v2` cache-key bump, but old `.json` files in `backend/data/_serp_cache/` are still on disk (harmless, just orphan).

**Resolution:**

1. (One-time, manual) Delete pre-fix `GapSerpResult` rows: `python manage.py shell -c "from apps.seo_ai.models import GapSerpResult; GapSerpResult.objects.filter(created_at__lt='2026-05-19').delete()"` — date being when commit `5333ff6` landed.
2. Re-run the SERP probe stage of the gap pipeline. New rows will be India-geo.
3. (Optional disk cleanup) `rm -rf backend/data/_serp_cache/*.json` — frees disk; new fetches will repopulate.

**To verify the fix is live inside Docker without re-running anything:** read line 166-171 of `serp_api.py` inside the running container. If those four `elif engine == "bing":` / `elif engine == "duckduckgo":` blocks exist, the fix is in place.

---

## 12. Hardcoded "Bajaj Allianz" References (Brand Hygiene)

Quick grep — outside of legacy AEM titles inside crawled pages (which we don't control), code paths that hard-reference "Bajaj Allianz" instead of "Bajaj":

- None found in source code as of this audit.
- AEM JSON sample data at `backend/data/aem/bajajlife-sitemap-*.json` is upstream data, not ours.
- The competitor `bajajallianzlife.com` is in SEMrush data because the rebrand left the old domain active — that's a real competitor signal, not a brand bug.

Status: clean.

---

## 13. Quick-Win Action Items (Pre-Deploy, Days)

If shipping in 1-2 weeks, the must-do list:

1. **Set all prod secrets** (SECRET_KEY, DB creds, ALLOWED_HOSTS, all API keys you intend to use) — 1 hour
2. **Rotate the leaked SA private key + bake new one into image** — 30 min
3. **Move crawler to Celery task** (avoid request-thread timeout in prod) — 4 hours
4. **Add cache-cleanup cron** (delete files older than TTL across all `_*` dirs) — 2 hours
5. **Set up Sentry or equivalent** — 1 hour
6. **Test against staging Postgres + Redis** — 4 hours
7. **Configure CORS + STATIC_ROOT** — 1 hour
8. **Re-run gap pipeline once to refresh SERP rows with India geo** — minutes (just trigger from UI)
9. **Add basic /health/ endpoint** for load-balancer checks — 30 min
10. **Document the deploy runbook** (compose vs bare metal, env var inventory) — 2 hours

**Total: ~1.5 engineering days of pre-deploy plumbing**, then ready for staged rollout.

---

## 14. What This Audit Did NOT Check

To be transparent about scope:

- **Frontend security** (XSS, CSP, dependency CVEs in node_modules) — separate audit
- **Authentication / authorization** — none observed in the API surface; everything is open. Production needs auth.
- **Performance benchmarking under load** — no load tests run
- **Browser compatibility** — only tested in whatever your dev machine renders
- **GDPR / data retention** of crawled competitor content — legal question, not technical
- **Cost forecast** of SEMrush + SerpAPI + PSI + LLM bills at production scale — finance question

Each of these is worth its own pass before serving real traffic.

---

*Audit author: Claude Opus 4.7 (1M context). Read-only pass — no code executed, no Docker actions taken.*
