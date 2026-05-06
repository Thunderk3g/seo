# Lattice SEO Crawler — Vertical-Slice Design

**Date:** 2026-05-06
**Author:** Brainstormed with Claude (`superpowers:brainstorming`)
**Status:** Awaiting user review

---

## 1. Goal

Ship a usable, end-to-end SEO crawler experience: register a domain → trigger a crawl → see the results in a polished dashboard with one real AI-explained insight panel. Use the existing Django + DRF + Celery + aiohttp backend (in `backend/`), fix the known bugs blocking it from running cleanly, and build a brand-new TypeScript/Vite frontend that renders the 8-screen design from the Anthropic Design bundle at `.design-ref/` (project name "Lattice").

Every visible interactive element in the UI must call a real backend endpoint. No placeholder buttons. Anything we can't back is either removed from the UI or labeled and disabled with copy that explains why.

## 2. Concrete bug we are fixing in this slice

**Symptom (reproduced 2026-05-06 from `backend/apps/crawler/management/commands/run_crawl.py`):**

```
Domain: https://https://www.bajajlifeinsurance.com   ← duplicated scheme
[ERROR] Connection error: https://https:/robots.txt | Detail: Cannot connect to host https:443
[ERROR] Connection error: https://https://www.bajajlifeinsurance.com/ | Detail: Cannot connect to host https:443
Crawl Complete: Pages Crawled: 0, Failed: 1, Duration: 43.4s
```

**Root cause:** the input domain (`https://www.bajajlifeinsurance.com`) is unconditionally re-prefixed with `https://`. The result is a malformed URL whose host portion is the literal string `https`. `getaddrinfo` fails. The engine is otherwise healthy — the BFS loop, fetcher, parser, and persistence all work; they were just never given a real URL.

**Fix:** introduce a `normalize_seed_url()` helper and apply it at every entry point that accepts a user-supplied domain (CLI, Celery task, DRF write serializer). Out of scope for this slice but called out in the prior audit: full canonical *truth* resolution, host-health adaptive backoff, rendering-queue split, the other 6 AI agents.

## 3. Architecture

```
Browser (React 18 + TS + Vite)
    │
    │  HTTP (dev: Vite proxy 5173 → 8000) (prod: Django serves dist/)
    ▼
Django REST (DRF) ─────────────────────────────────────┐
    │                                                  │
    │  enqueue Celery task                             │  reads
    ▼                                                  ▼
Celery worker (Redis broker) ──── runs ────► CrawlerEngine (aiohttp)
    │                                                  │
    │  on success, in same task                        │ writes Pages/Links/etc
    ▼                                                  ▼
IndexingIntelligenceAgent ─── HTTPS ─►  PostgreSQL (existing schema +
    │                                    one new field: ai_insights JSONB)
    ▼
Anthropic Claude API
(prompt caching enabled — system + GSC taxonomy cached)
```

**Process boundary table:**

| Process | What it owns |
|---------|--------------|
| Django web | DRF API, static frontend bundle in prod, request validation |
| Celery worker | Crawl execution, AI insight generation, export file writes |
| Redis | Celery broker + result backend |
| Postgres | All persisted state |
| Anthropic API | One agent call per completed crawl |

**Frontend ↔ backend dev contract:**
- Vite dev server on `:5173` proxies `/api/*` to `http://localhost:8000`.
- Production: `npm run build` outputs to `frontend/web/dist/`; Django serves it at `/` via `whitenoise`.
- Types generated from DRF's OpenAPI schema via `openapi-typescript` into `frontend/web/src/api/types.ts`. Regenerate as a `predev` / `prebuild` step.

## 4. Backend changes

All changes are additive or local — no major refactors.

### 4.1 URL normalization (the bug)

New helper at `backend/apps/common/url_utils.py`:

```python
def normalize_seed_url(raw: str) -> str:
    """Accept a user-supplied domain. Return a canonical https:// URL or raise."""
    # Handles: bare domain, http(s)://, scheme-relative //, trailing slash,
    # whitespace, IDN, paths/query (preserve), :443/:80 ports, double-scheme.
```

Test cases (table-driven; required green before merge):

| Input | Expected output |
|-------|-----------------|
| `bajajlifeinsurance.com` | `https://bajajlifeinsurance.com/` |
| `https://www.bajajlifeinsurance.com` | `https://www.bajajlifeinsurance.com/` |
| `https://https://www.x.com` | `https://www.x.com/` (the actual bug) |
| `http://x.com:80/foo` | `http://x.com/foo` |
| `https://x.com:443` | `https://x.com/` |
| `//x.com/path` | `https://x.com/path` |
| `  https://x.com/  ` (whitespace) | `https://x.com/` |
| `not a url` | raises `ValueError` |
| `ftp://x.com` | raises `ValueError` (only http/https allowed) |

Apply at three entry points:
1. `backend/apps/crawler/management/commands/run_crawl.py` — wrap the CLI argument before passing to the engine.
2. `backend/apps/crawler/tasks.py:run_on_demand_crawl` — wrap before instantiating the engine.
3. `backend/apps/crawler/serializers.py:WebsiteSerializer.validate_domain` — surface validation errors as DRF 400.

Also fix `backend/apps/crawler/services/crawler_engine.py:_seed_frontier()` so the robots.txt URL is built with `urllib.parse.urljoin(homepage, "/robots.txt")`, not string concatenation. Same root cause class.

### 4.2 New / modified endpoints

| Method | Path | Purpose | New? |
|--------|------|---------|------|
| `POST` | `/api/websites/` | Register a site (now uses `normalize_seed_url`) | modified |
| `POST` | `/api/websites/:id/crawl/` | Start an on-demand crawl | exists |
| `GET` | `/api/sessions/:id/overview/` | Live crawl progress + KPIs | exists |
| `GET` | `/api/sessions/:id/activity/?since=<iso>` | Activity-feed entries since a timestamp | **new** |
| `GET` | `/api/sessions/:id/insights/` | AI insights JSON. 202 if still computing | **new** |
| `POST` | `/api/sessions/:id/insights/regenerate/` | Force re-run of `IndexingIntelligenceAgent` | **new** |
| `GET` | `/api/sessions/:id/analytics/` | Aggregated counts for charts (status/depth/response-time/content-type) | **new** |
| `GET` | `/api/sessions/:id/tree/` | Site-structure tree (folder counts) | **new** |
| `GET` | `/api/sessions/:id/exports/` | List of generated export files | **new** |
| `POST` | `/api/sessions/:id/exports/:kind/` | Generate an export (kind ∈ `urls.csv`, `issues.xlsx`, `sitemap.xml`, `broken-links.csv`, `redirects.csv`, `metadata.json`) | **new** |
| `GET` | `/api/sessions/:id/exports/:export_id/download/` | Stream the file | **new** |
| `GET` | `/api/system/metrics/` | Live worker metrics (rps, queue depth, threads, mem) — stub: read from Celery + Redis stats | **new** |
| `GET` | `/api/settings/` / `PATCH` | Read/write `CrawlConfig` for the active site | **new** |

The `pages`, `links`, `classifications`, `sitemap-reconciliation`, `structured-data` endpoints already exist on `CrawlSessionViewSet` and are reused.

### 4.3 AI agent wiring

- New module `backend/apps/ai_agents/services/anthropic_client.py` — thin wrapper using `anthropic` Python SDK. Reads `ANTHROPIC_API_KEY` from settings.
- Default model: `claude-haiku-4-5-20251001` (cost). Configurable via `LATTICE_AI_MODEL` env var; allows upgrade to `claude-sonnet-4-6`.
- Implement `IndexingIntelligenceAgent.run(session)` end-to-end:
  - Pull session counts and exclusion breakdown via ORM.
  - Build prompt with `cache_control: ephemeral` on (a) the system message and (b) a static GSC-state taxonomy block. The dynamic per-session block goes uncached.
  - Parse the model's response into a structured shape: `{ summary: str, top_issues: [{title, severity, count, why, fix}], confidence: number }`.
  - Save to `CrawlSession.ai_insights` (new JSONB field, nullable).
- Hook into `crawler/tasks.py:run_on_demand_crawl` after engine completion:
  ```python
  try:
      result = IndexingIntelligenceAgent().run(session)
      session.ai_insights = result
  except Exception as e:
      session.ai_insights = {"error": str(e), "model": model_name}
  finally:
      session.save(update_fields=["ai_insights"])
  ```
  Failures don't fail the crawl — they show as a retryable error card in the UI.

### 4.4 Database migration

Single Django migration on `crawl_sessions`:

```python
ai_insights = models.JSONField(null=True, blank=True)
ai_insights_generated_at = models.DateTimeField(null=True, blank=True)
ai_insights_model = models.CharField(max_length=64, blank=True, default="")
```

### 4.5 Docker compose

Add what's missing for the stack to actually boot from a clean clone:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
  worker:
    build: ./backend
    command: celery -A config worker -l info
    depends_on: [redis, db]
    env_file: [.env]
  backend:
    # ... existing ...
    command: >
      sh -c "python manage.py migrate &&
             python manage.py runserver 0.0.0.0:8000"
```

`requirements/base.txt` adds:
- `anthropic>=0.40.0`
- `playwright>=1.45.0` (default `enable_js_rendering=False` for v1; install browser via post-install note in README)
- `whitenoise>=6.6.0` (serve frontend in prod)
- `django-cors-headers>=4.3.0` (dev only, scoped to localhost:5173)

## 5. Frontend

### 5.1 Stack

- **Vite** + **React 18** + **TypeScript** (strict).
- **TanStack Query** for server state, polling, request dedup, retry/backoff.
- **Wouter** (~2 KB) for routing — no nested layouts, 8 flat routes.
- **No CSS framework.** We lift `.design-ref/project/styles.css` (1294 lines) verbatim into `src/styles/lattice.css`. The design's CSS variables (`--accent`, `--surface`, etc.) become our entire theming system.
- **No state library.** TanStack Query handles server state; React `useState` handles UI state.
- **`openapi-typescript`** for types generated from DRF's auto-generated schema.

### 5.2 Design tokens (verbatim from `.design-ref/project/styles.css`)

```css
:root {
  --bg: #0a0d12;
  --bg-2: #0f141b;
  --surface: #141a23;
  --text: #e7eaef;
  --accent: #6ee7b7;        /* mint default */
  --error: #f87171;
  --warning: #fbbf24;
  --notice: #60a5fa;
  --radius: 10px;
  --radius-lg: 14px;
}
```

5 accent palettes (Mint, Cyan, Indigo, Magenta, Amber), 3 density modes (compact/regular/comfy), light/dark theme via `[data-theme="light"]` on `<html>`. All applied through CSS variables.

Fonts: Inter (UI) + JetBrains Mono (URLs, IDs, numerics). Loaded from Google Fonts in `index.html`.

### 5.3 Directory layout

```
frontend/web/
├── package.json, vite.config.ts, tsconfig.json, index.html
├── src/
│   ├── main.tsx, App.tsx
│   ├── api/
│   │   ├── client.ts          # fetch wrapper, error normalizer
│   │   ├── types.ts           # generated by openapi-typescript
│   │   └── hooks/             # TanStack Query hooks per resource
│   │       ├── useSession.ts, useSessions.ts, useWebsites.ts
│   │       ├── useInsights.ts, useAnalytics.ts, useTree.ts
│   │       ├── useExports.ts, useSettings.ts, useMetrics.ts
│   │       └── useActivity.ts
│   ├── components/            # ports of design components, retyped to TS
│   │   ├── Sidebar.tsx, Topbar.tsx, StatusBar.tsx
│   │   ├── StatCard.tsx, Panel.tsx
│   │   ├── charts/Sparkline.tsx, Donut.tsx, Gauge.tsx,
│   │   │       Meter.tsx, BarChart.tsx, LiveArea.tsx
│   │   ├── tables/PagesTable.tsx, SessionsTable.tsx
│   │   ├── icons/Icon.tsx, BrandMark.tsx
│   │   └── status/StatusPill.tsx, SeverityBar.tsx
│   ├── pages/                 # 8 routes, 1:1 with the design
│   │   ├── DashboardPage.tsx, SessionsPage.tsx
│   │   ├── PagesUrlsPage.tsx, IssuesPage.tsx
│   │   ├── AnalyticsPage.tsx, VisualizationsPage.tsx
│   │   ├── ExportsPage.tsx, SettingsPage.tsx
│   │   └── (no auth pages — single-user)
│   └── styles/lattice.css     # lifted from design-ref
```

### 5.4 Screen-by-screen mapping (the "no false buttons" contract)

For each screen below: which design elements ship in v1, which API call backs each interaction, what gets cut.

#### 5.4.1 Dashboard

| Component (design) | Backed by | Notes |
|--------------------|-----------|-------|
| 5 KPI cards (Total / Crawled / Pending / Failed / Excluded) | `GET /sessions/:id/overview/` | Sparkline data: client-side rolling buffer of last 32 polls |
| SEO Health gauge | `GET /sessions/:id/overview/` | Top score = `((index_eligible) / max(crawled,1)) * 100`. Three sub-scores in the gauge breakdown: **Technical** = `(non-error pages / crawled)` × 100; **Content** = `((pages with title AND meta) / html_200_pages)` × 100; **Performance** = `(pages with response_time < 1s / crawled)` × 100. All computed server-side in the overview aggregation |
| Issue distribution donut | `GET /sessions/:id/overview/` | Server returns `{errors, warnings, notices}` counts |
| Crawl overview table | `GET /sessions/:id/overview/` | Static rows from session: started, duration, avg response, URLs/sec, max depth, user agent, JS rendered y/n, robots followed y/n |
| URL mini-table (4 tabs) | `GET /sessions/:id/pages/?content_type=html&limit=8` etc. | Paginated, real |
| Activity feed | `GET /sessions/:id/activity/?since=<ts>` | Polled every 1.5s while running. Entries are `crawl_event` log rows persisted to a new lightweight `CrawlEvent` model |
| System metrics | `GET /api/system/metrics/` | rps from Celery, queue from Redis `LLEN`, threads/mem from `psutil` on worker |
| Top issues | `GET /sessions/:id/overview/` | Top 8 by count |
| Site structure mini | `GET /sessions/:id/tree/` | Top-level folders only |

**Cut from this screen:** any "View report" / "View all" links go to their respective pages (not removed). The "Live" pulsing dot is real (running status).

#### 5.4.2 Crawl Sessions

| Component | Backed by | Notes |
|-----------|-----------|-------|
| Sessions table | `GET /api/sessions/?website=<id>` | Pagination, filtering by status |
| "New crawl" button | `POST /api/websites/:id/crawl/` | Real |
| "Schedule" button | **Cut.** No scheduler in v1 — Celery beat is out of scope. Replace button with a tooltip-disabled state and helper text |
| Row "more" menu | Subset only: View detail (link), Cancel running (`POST /api/sessions/:id/cancel/` — **new** endpoint), Re-run (`POST .../crawl/`). Drop "Export this session" from row menu |

#### 5.4.3 Pages / URLs

| Component | Backed by | Notes |
|-----------|-----------|-------|
| Tabs (All/HTML/Images/4xx/3xx/5xx) | `GET /sessions/:id/pages/?content_type=&status_class=` | Real query params |
| Search | Same endpoint, `?q=` | Server-side ILIKE on path + title |
| Status filter dropdown | Same endpoint, `?status_class=` | Real |
| Sort by column | Same endpoint, `?ordering=` | Real |
| Pagination | Cursor pagination on existing endpoint | Real |
| "Advanced filters" | **Cut.** Hide button in v1 |
| "Export CSV" | `POST /api/sessions/:id/exports/urls.csv/` then poll for download | Real |
| "Re-crawl" | `POST /api/websites/:id/crawl/` | Triggers fresh session for the same site |

#### 5.4.4 Issues

| Component | Backed by | Notes |
|-----------|-----------|-------|
| Issue list (left) | `GET /sessions/:id/issues/` (**new**) | Derived server-side from `pages` + `url_classifications`; same 12-category taxonomy as the design's `data.js:deriveIssues()` |
| Severity tabs | Client-side filter on the array | Real |
| Issue detail (right) | `GET /sessions/:id/issues/:issue_id/` (**new**) | Returns affected URLs slice |
| "Copy list" | Client-side: copies URL list to clipboard | Real |
| "Export" | `POST /api/sessions/:id/exports/issues.xlsx/` | Real |
| "Configure rules" | **Cut.** No issue-rule customization in v1 |

#### 5.4.5 Analytics

| Component | Backed by | Notes |
|-----------|-----------|-------|
| Status code donut | `GET /sessions/:id/analytics/` | Single endpoint returns all 4 chart datasets |
| Depth distribution bars | Same | |
| Response time histogram | Same | |
| Content type donut | Same | |

No buttons on this screen. Pure read-only.

#### 5.4.6 Visualizations

| Component | Backed by | Notes |
|-----------|-----------|-------|
| Tab: Network graph | `GET /sessions/:id/links/?layout=force` (existing endpoint, new query param) | Server returns nodes + edges with pre-computed layout coordinates. Render is client-side SVG (no live force simulation in browser, matching the design's deterministic-layout approach) |
| Tab: Site tree | `GET /sessions/:id/tree/` | Real |
| Tab: Treemap | Same `/tree/` endpoint, client-side slice-and-dice | Real |

#### 5.4.7 Exports

| Component | Backed by | Notes |
|-----------|-----------|-------|
| Card grid of exports | `GET /sessions/:id/exports/` | List of previously-generated files |
| "Download" button | `GET /api/sessions/:id/exports/:export_id/download/` | Streams from server |
| "New export" button | Modal → `POST /api/sessions/:id/exports/:kind/` | 6 kinds: `urls.csv`, `issues.xlsx`, `sitemap.xml`, `broken-links.csv`, `redirects.csv`, `metadata.json` |

Each export is generated synchronously via Celery task (small enough to fit in 30s for v1 sites < 50k URLs); for larger sites, the API returns `202 + {export_id}` and the UI polls.

#### 5.4.8 Settings

| Component | Backed by | Notes |
|-----------|-----------|-------|
| Crawl configuration card (UA, rate, depth, max URLs, JS toggle, robots toggle, nofollow toggle) | `GET / PATCH /api/settings/` (subset of `CrawlConfig`) | Real |
| **Appearance card (accent / density / light-dark)** | localStorage `lattice.prefs`, no backend | Real, see §5.4.9 |
| Schedule card | **Cut.** No scheduler. Replace with a small "Coming soon — manual crawls only in v1" panel that is visually consistent but obviously informational |
| Inclusions / exclusions card | `GET / PATCH /api/settings/` (`excluded_paths`, `excluded_params`) | Real |
| API & integrations card | `API key`: read-only display from settings. `Webhook` and `GA4 connection`: **cut** (Slack/GA4 are third-party we don't have credentials for). Replace with a single "Coming soon" card |

#### 5.4.9 AI Insights drawer (new, repurposes the Tweaks panel slot)

The design's "Tweaks" panel is a developer affordance — accent picker, density, light/dark mode, crawl-speed simulation, sidebar quick-stats toggle. The first three (accent, density, light/dark) are real user preferences that need a home. The last two (crawl-speed, quick-stats) are simulation knobs we don't need.

**Decision:**
- A small "Appearance" section is added to the **Settings** screen with the three real preferences (accent palette, density, light/dark). Persisted to `localStorage` keyed by `lattice.prefs`.
- The right-side drawer slot is repurposed for **AI Insights**. Triggered by a top-bar button (lights up when `session.ai_insights` is non-null). Drawer slides in showing `IndexingIntelligenceAgent` output (markdown summary + structured top-issues list + "Regenerate" button). Styling lifted from the design's `.tweaks-panel` CSS.
- The original Tweaks panel is preserved verbatim in dev only, accessible via `?tweaks=1` query param, for the developer who wants the full simulation knobs while iterating.

### 5.5 State conventions

- Every data read is a `useQuery` hook, keyed by `[resource, ...args]`.
- Polling: `refetchInterval: session.status === 'running' ? 2000 : false`. TanStack Query handles this.
- Activity feed: `useInfiniteQuery` with `since=<lastTs>` cursor; merges new entries into a 14-row rolling buffer client-side (matching the design's animation pattern).
- Sparkline / live-area data: client-side rolling buffer of the last 32 polled values per metric. *Not* persisted — the design renders live sparkles from a 32-tick history, and we replicate by buffering polls.
- Mutations: `useMutation`; on `onSuccess`, invalidate the relevant query keys.

## 6. Data flow — one journey end-to-end

```
1. User on /sites enters "https://www.bajajlifeinsurance.com"
   POST /api/websites/  →  normalize_seed_url()  →  Website row
   201 Created          →  invalidate ['websites']

2. User clicks "Start crawl"
   POST /api/websites/:id/crawl/
        creates CrawlSession (status=created)
        enqueues run_on_demand_crawl.delay(session.id)
        returns 202 + {session_id}
   FE redirects to /sessions/:id (auto-selected as "active")

3. /sessions/:id mounts → Dashboard / Sessions detail layout
   Polls every 2s while status='running':
     GET /sessions/:id/overview/   → KPIs, health, issue counts
     GET /sessions/:id/activity/?since=<ts>  → new feed entries
     GET /api/system/metrics/  → live worker metrics
   Topbar progress bar fills (crawled/total). ETA computed client-side
   from rolling rate history.

4. Worker meanwhile:
   engine.run() does BFS, fetches, parses, persists Pages bulk_create
   on completion, IndexingIntelligenceAgent.run(session) calls
   Anthropic with prompt-cached system + GSC taxonomy
   writes session.ai_insights
   session.status = 'completed'

5. FE detects status flip on next poll:
   - polling stops
   - all 8 screens have data
   - "AI Insights" button on top bar lights up

6. User clicks AI Insights → drawer opens
   GET /sessions/:id/insights/
     200 → render markdown summary + structured top-issues list
     202 → "Generating insights..." with spinner; poll every 2s
     200 with {error: ...} → error card with "Regenerate" button
                              POST .../insights/regenerate/
```

## 7. Error handling

**Design philosophy (borrowed from the GitHub `tanish-24-git/webcrawler` reference reviewed during research):** every fetch failure inside the crawler becomes a typed `FetchResult.error` string, never a raised exception that escapes the worker pool. The existing engine already does this — we keep it.

**Backend additions:**
- `fetcher.py` honors `Retry-After` on 429 (sleep then retry once, then mark failed).
- `WebsiteSerializer.validate_domain` raises `serializers.ValidationError` with a human-readable message when `normalize_seed_url` fails. DRF returns 400.
- `IndexingIntelligenceAgent` wraps every Anthropic call in try/except; on failure writes `{error: str(e), model: name, retryable: True}` to `ai_insights`.
- New `CrawlSession.error_message` field (TextField, blank=True) for engine-level failures.

**Frontend additions:**
- Single `<ErrorBoundary>` in `App.tsx` → fallback panel with the design's error styling.
- TanStack Query auto-retries 3× with exponential backoff (default).
- Form errors (Add Site) mapped to per-field errors via DRF validation response.
- AI insights error card has a "Regenerate" button (real `POST /insights/regenerate/`).

## 8. Testing

Scaled to v1 scope. Don't write tests for code we're not changing.

**Backend (pytest + pytest-django):**
- `test_url_utils.py` — table-driven tests for `normalize_seed_url`, including the actual bug case (`https://https://x.com`). ~15 cases.
- `test_indexing_agent.py` — runs `IndexingIntelligenceAgent.run()` against a recorded `CrawlSession` fixture with `anthropic.Anthropic` mocked. Assert prompt structure (system message present, cache_control set, user message contains exclusion breakdown) and output parsing.
- `test_normalize_seed_integration.py` — POST `/api/websites/` with bad inputs; assert 400 + correct error shape.
- `test_smoke_crawl.py` (slow, skipped in default CI) — register `httpbin.org`, run the engine, assert pages exist in DB. Tagged `@pytest.mark.slow`.

**Frontend (Vitest + Testing Library):**
- One smoke render per page (8 tests).
- API hook tests with MSW (mock service worker): `useSession` polls while running, stops on completed.
- One integration test per critical button: Add Site → 400 surfaces, → 201 navigates, Start Crawl → redirects, AI insights drawer opens & polls.
- **No E2E (Playwright/Cypress).** Defer to v2.

**CI:**
- `pytest -m "not slow"` (~30s)
- `vitest run` (~20s)
- `tsc --noEmit` (~5s)
- `ruff check backend/` (~3s)
- Total ~60s. GitHub Actions, single job.

## 9. Sequencing — one screen at a time

Each numbered day below ends with a working, demoable artifact. Approach 1 from the brainstorm.

**Day 0 (foundation, half day):**
- `normalize_seed_url` + tests. URL bug fixed.
- `frontend/web/` Vite scaffold; lift `lattice.css`; basic `App.tsx` shell with sidebar + topbar + status bar (no live data yet).
- `openapi-typescript` generation pipeline.
- `docker-compose.yml` updated; full stack boots from `docker compose up`.

**Day 1 — Pages 1 & 2 (Add Site + Crawl Sessions):**
- DRF serializer validation wired.
- Sites view (small modal in topbar URL field, since the design has no `/sites` page — the sidebar project picker handles it).
- Crawl Sessions screen wired to existing `/api/sessions/`.
- Trigger crawl button works end-to-end. New `POST /sessions/:id/cancel/` endpoint added.

**Day 2 — Page 3 (Pages/URLs) + Activity feed:**
- New `CrawlEvent` model + persistence in engine logger.
- New `/sessions/:id/activity/` endpoint.
- Pages/URLs screen wired with sort/filter/search/pagination against existing `/pages/` endpoint.

**Day 3 — Page 4 (Issues) + Page 5 (Analytics):**
- `/sessions/:id/issues/` and `/issues/:issue_id/` endpoints (the 12-category taxonomy from `data.js` ported to Python).
- `/sessions/:id/analytics/` endpoint (single SQL aggregation per chart).
- Both screens wired.

**Day 4 — Page 6 (Visualizations) + Page 7 (Exports):**
- `/sessions/:id/tree/` endpoint.
- Network graph uses existing `/links/` endpoint with new `layout` param.
- Exports endpoints + 6 export generators (each is a single function in `apps/exports/services/`).

**Day 5 — Page 8 (Settings) + AI agent + polish:**
- `/api/settings/` GET/PATCH wired to `CrawlConfig`.
- `IndexingIntelligenceAgent` end-to-end with real Anthropic calls + prompt caching.
- AI Insights drawer wired.
- Dashboard's KPI strip + health gauge + system metrics polish (left for last because it depends on every other endpoint being live).
- End-to-end smoke: register, crawl, see all 8 screens populated for `bajajlifeinsurance.com`.

## 10. Out of scope (explicit list)

These are the prior audit's findings we are *not* fixing in this slice. They are tracked separately.

- Canonical truth resolution (the spec's signal-weighted clustering pass).
- Host-health adaptive crawl budget (Section 11 of the engine spec).
- Two-phase rendering queue split (rendering happens inline today; that's fine for v1).
- The other 6 AI agents (`LinkIntelligenceAgent`, `PerformanceAgent`, `SitemapAgent`, `Orchestrator`, `Narrator`, RAG ChatBot).
- Auth, multi-user, RBAC, SSO. Single-user app.
- Real-time updates via SSE/WebSocket. Polling only.
- Schedule (Celery beat). Manual crawls only.
- Slack / GA4 / webhook integrations.
- Soft-404 detection improvements.
- Cross-session deduplication / persistent visited-URL cache.
- Change-detection diff view.
- URL inspection mode UI (the `/websites/:id/inspect/` API exists but no UI).
- E2E tests.

## 11. Open questions

1. **Anthropic API key source.** Does Bajaj have an existing Anthropic contract, or should we use a personal/team key for now? Spec assumes the latter (`ANTHROPIC_API_KEY` env var). If neither is available, the agent must be feature-flagged off and the AI Insights drawer hidden — **the design must still ship** in that case.
2. **Brand name.** The design ships as "Lattice". We can keep that or rebrand to something like "Bajaj SEO" / "Coverage Lens". Trivial change; ask user before committing.
3. **Multi-tenancy scope.** The `Website` model already supports multiple sites. Spec assumes single-user; do we need any per-user filtering at the API layer if we ever add auth? **Decision: no — defer until auth lands.**
4. **Activity-feed retention.** New `CrawlEvent` rows will accumulate. Should we cap at N most recent per session, or use a TTL job? **Decision: cap at 5,000 rows per session, drop older via a post-crawl cleanup task.**
