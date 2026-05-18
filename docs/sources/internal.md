# Internal Data Sources

Sources that don't need an API key — file ingestion (AEM exports, GSC
CSV drops, sitemap.xml) and our own HTTP crawler. These are gated by
file presence, not by env vars.

## 1. AEM (Adobe Experience Manager) JSON exports

How `bajajlifeinsurance.com` authoring content reaches the dashboard.
AEM doesn't expose a public API — instead, marketing exports the page
model as JSON and drops the bundle into a folder we read.

### File layout

```
backend/data/aem/
  <site>__page-model.json    ← top-level page metadata
  <site>__components.json    ← component tree per page
  ...
```

Or the older single-file format under `SEO_AI_SITEMAP_DIR` if that env
var is set. Both paths are gitignored.

### What we extract per AEM page

| Field | Source |
|---|---|
| `aem_path` | `/content/balic-web/en/...` — stable identifier in the CMS |
| `public_url` | The rendered URL on `bajajlifeinsurance.com` |
| `title`, `description` | Page-level metadata |
| `template_name` | The AEM template the page was built from |
| `last_modified` | AEM's mtime |
| `word_count` | Sum across all rendered components |
| `content` | Concatenated text of every text/HTML component on the page |
| `component_types` | Per-page list of `text`, `image`, `cta-banner`, etc. |

### Code map

| File | Responsibility |
|---|---|
| `apps/seo_ai/adapters/sitemap_aem.py` | `SitemapAEMAdapter` — reads the JSON bundle into a list of `AEMPage` objects |
| `apps/seo_ai/views.py` `sitemap_page_detail` | GET `/api/v1/seo/sitemap/page-detail/` — returns one page's full content by `aem_path` or `public_url`, used by the chat assistant when answering content questions |
| `apps/seo_ai/agents/*` | Several agents consume AEM content when grading "what's on the page" vs. "what does Google see" |

### Config

| Var | Default | Purpose |
|---|---|---|
| `SEO_AI_SITEMAP_DIR` | `backend/data/aem/` | Where to find the AEM JSON exports |

If the directory is empty, AEM-dependent features silently degrade — the
crawler-extracted HTML is used as the only content signal instead.

---

## 2. GSC CSV ingestion (manual drops)

For the bits of GSC that don't have an API (Coverage report aggregates,
Links report). Operator exports a CSV from the GSC UI and drops it into
a known path.

### File layout

```
backend/data/gsc/coverage/coverage_<date>.csv   ← Pages report export
backend/data/gsc/<site>/                         ← Search Analytics pulls (auto, not manual)
```

### Code map

| File | Responsibility |
|---|---|
| `apps/crawler/storage/gsc_loader.py` | Reads the most-recently-modified `coverage_*.csv` and exposes a `{url -> indexed/not_indexed/excluded/unknown}` map |
| `apps/crawler/storage/gsc_coverage_builder.py` | Builds a derived coverage CSV when no manual export exists — uses `web__page.csv` + live sitemap fetch instead |

See [`gsc.md`](./gsc.md) for the full GSC story.

### Config

| Var | Default | Purpose |
|---|---|---|
| `SEO_AI_GSC_DATA_DIR` | `backend/data/gsc/` | Where to find / write GSC artefacts |

---

## 3. Internal crawler

Our own HTTP crawler. No external API. Static `requests`-based, plus a
Phase-2 Playwright pass for real browser console capture.

### What it does

- Reads `robots.txt`, fetches every sitemap.xml (recursive: handles
  sitemapindex + gzipped sitemaps).
- BFS-crawls every in-domain URL using a thread-pool of workers
  (`max_workers=12` by default).
- Records per-page: HTTP status, content-type, title, word count,
  response time, schema markup.
- Writes 6 CSVs to `backend/data/`: `crawl_results.csv`, `crawl_errors.csv`,
  `crawl_404_errors.csv`, `crawl_errors_httperror.csv`,
  `crawl_console_log.csv`, `crawl_discovered.csv`.
- After Phase 1 finishes, launches Playwright on the top 200 www HTTP-200
  URLs to capture real JS errors + page errors + failed network requests
  (Phase 2 — see `engine/browser_console.py`).

### What's NOT crawled by default

PDFs, Office documents (`.pdf`, `.doc`, `.docx`, `.xls`, etc.) **ARE**
crawled now (recent change — Google indexes them). Images, audio, video,
fonts, CSS, JS, JSON, XML are skipped by the eligibility filter in
`engine/url_utils.py`.

### Code map

| File | Responsibility |
|---|---|
| `apps/crawler/engine/engine.py` | `run_crawl()` — top-level orchestrator. Phase 1 static crawl, then Phase 2 Playwright. try/finally around everything so `is_running` always clears |
| `apps/crawler/engine/fetcher.py` | One URL → one HTTP fetch. `stream=True` so binary content doesn't download the body |
| `apps/crawler/engine/parser.py` | HTML → title + word count + links. Filters out non-URL values in `data-*` attributes (so `data-link="false"` doesn't get crawled) |
| `apps/crawler/engine/url_utils.py` | Normalisation (preserves trailing slash) + eligibility filter |
| `apps/crawler/engine/browser_console.py` | Playwright headless Chromium pass — Phase 2 |
| `apps/crawler/storage/csv_writer.py` | 6 streaming CSV writers + 5 enrichment columns (subdomain, page_type, category_key, from_sitemap, indexed_status) |
| `apps/crawler/storage/url_classifier.py` | URL → (subdomain, page_type, category_key) classifier |
| `apps/crawler/storage/repository.py` | Read-only access to the CSVs for the UI |

### Config

| Var | Default | Purpose |
|---|---|---|
| `CRAWLER_SEED_URL` | `https://www.bajajlifeinsurance.com/` | Where the crawl starts |
| `CRAWLER_ALLOWED_DOMAINS` | `bajajlifeinsurance.com,www.bajajlifeinsurance.com` | Comma-sep allowlist. Add `branch.bajajlifeinsurance.com`, `investmentcorner.bajajlifeinsurance.com` to crawl subdomains |
| `CRAWLER_MAX_WORKERS` | `12` | Concurrent HTTP fetchers |
| `CRAWLER_MAX_DEPTH` | `0` (unlimited) | Depth cap |
| `CRAWLER_MAX_PAGES` | `0` (unlimited) | Page cap |
| `CRAWLER_RESUME` | `true` | Resume from `crawl_state.json` on next run |
| `CRAWLER_CAPTURE_CONSOLE_AFTER_CRAWL` | `true` | Run Phase 2 Playwright pass after the static crawl |
| `CRAWLER_CONSOLE_CAPTURE_LIMIT` | `200` | Top-N URLs to inspect with Playwright |
| `CRAWLER_USER_AGENT` | (default polite UA) | UA string |
| `CRAWLER_REQUEST_TIMEOUT` | `30` | Per-page HTTP timeout (sec) |

### How it's used by the dashboard

| UI surface | Crawler data used |
|---|---|
| Crawler Dashboard | Live progress + recent pages |
| Site Tree | `crawl_discovered.csv` parent→child edges |
| Live Logs | Polling log feed |
| Reports → Indexing / Sitemap / Errors sections | `crawl_results.csv` + enrichment columns |
| Reports → Console log card | `crawl_console_log.csv` (populated by Phase 2 Playwright) |
| Competitor Dashboard → Apples-to-apples comparison | Top-200 own pages crawled symmetrically vs the same-count rival pages |

---

## 4. Competitor crawler (sibling crawler — limited scope)

Separate from the main `apps/crawler` engine because of a domain-allowlist
constraint.

| File | Purpose |
|---|---|
| `apps/seo_ai/adapters/competitor_crawler.py` | Small, self-contained fetcher used by the gap pipeline + Competitor Dashboard. Crawls competitor domains the main engine refuses to (the main engine is hard-gated to `bajajlifeinsurance.com`) |

| Var | Default | Purpose |
|---|---|---|
| `COMPETITOR_ENABLED` | `true` | Master kill switch |
| `COMPETITOR_TOP_N` | `10` | Number of rivals to track |
| `COMPETITOR_PAGES_PER_COMP` | `50` | Pages crawled per rival |
| `COMPETITOR_KW_PER_COMP` | `100` | SEMrush keyword count per rival |
| `COMPETITOR_RATE_LIMIT_SEC` | `1.0` | Politeness delay per request |
| `COMPETITOR_TIMEOUT_SEC` | `15` | Per-request HTTP timeout |
| `COMPETITOR_USER_AGENT` | (browser-like) | UA |
| `COMPETITOR_CACHE_TTL_SECONDS` | `604800` (7 days) | Disk-cache TTL |
| `COMPETITOR_OUR_PAGES_LIMIT` | `200` | How many of OUR top pages to crawl symmetrically |
| `COMPETITOR_SSL_VERIFY` | `false` | Corp MITM bypass |

Cache: `backend/data/_competitor_cache/`.

---

## 5. Database & queue (Postgres + Redis)

Internal storage. Not user-facing data sources but worth documenting.

| Container | Purpose | Config |
|---|---|---|
| `seo-db-1` | Postgres 15 — stores SEORun rows, GapPipelineRun + GapDeepCrawl + GapSerpResult, etc. | `DB_NAME=seo_db`, `DB_USER=postgres`, `DB_PASSWORD=postgres`, `DB_HOST=db` (in compose), `DB_PORT=5432` |
| `seo-redis-1` | Redis — Celery broker + result backend | `CELERY_BROKER_URL=redis://redis:6379/0`, `CELERY_RESULT_BACKEND=redis://redis:6379/0` |
| `seo-worker-1` | Celery worker | Inherits all env from compose |

Volumes:
- `pg_data` (Docker named volume) — persists Postgres data across `docker compose down`
- `backend/data` (bind-mount) — crawler / GSC / SEMrush / SerpAPI / AI Visibility caches survive container rebuilds
- `backend/reports` (bind-mount) — XLSX reports

All of `backend/data/` and `backend/reports/` are gitignored.
