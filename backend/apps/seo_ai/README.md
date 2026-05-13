# SEO AI Agent System

> Phase 0 implementation of the multi-agent SEO grading system from
> `docs/SEO_AI_Agents_Plan.md`. Produces a numeric SEO grade
> (0–100) for `bajajlifeinsurance.com` from the project's existing
> crawler / GSC / AEM data sources, with every claim grounded in a
> citable fact.

## Verified status

Tested end-to-end on `2026-05-13` against:

- `backend/data/crawl_results.csv` — 3 653 URLs from the file-backed crawler
- `backend/data/gsc/www.bajajlifeinsurance.com/` — 78 GSC CSVs (web/image/news/video × dimensions)
- `backend/data/aem/*.json` — 6 deduplicated AEM page-model exports
- SEMrush key (1.99 M units, India database)
- Groq `openai/gpt-oss-120b`

One end-to-end run takes **≈75 seconds** and costs **≈$0.008**.

```
technical ok ($0.0019, 6.4s)
keyword   ok ($0.0025, 18.7s)
critic    ok ($0.0019, 28.5s)   verdict=revise accepted=4 rejected=15
narrator  ok ($0.0015, 17.2s)
overall_score = 50.15
```

## Architecture (quick reference)

```
backend/apps/seo_ai/
├── adapters/            # source ingestion (file/HTTP), no Django
│   ├── crawler_csv.py   # backend/data/crawl_*.csv + crawl_state.json
│   ├── gsc_csv.py       # test/gsc_data/<site>/web__*.csv
│   ├── sitemap_aem.py   # sitemap/*.json
│   └── semrush.py       # SEMrush API + filesystem JSON cache
├── agents/              # one prompt + JSON schema per file
│   ├── base.py          # tool-loop, schema validation, retry, logging
│   ├── technical.py     # Technical SEO auditor
│   ├── keyword.py       # SERP / Keyword Intelligence
│   ├── critic.py        # judge / evidence-ref validation
│   ├── narrator.py      # executive summary
│   └── orchestrator.py  # sequential pipeline
├── llm/
│   └── provider.py      # GroqProvider + StubProvider, Windows TLS fix
├── scoring.py           # deterministic Python score math
├── models.py            # SEORun, SEORunFinding, SEORunMessage, SEORunToolCall
├── serializers.py
├── views.py             # DRF + start_grade
├── urls.py              # mounted at /api/v1/seo/
├── tasks.py             # Celery task for async kickoff
├── admin.py
└── migrations/
```

The orchestrator (`agents/orchestrator.py`) drives:

```
refresh facts → technical + keyword (specialists)
              → critic (evidence-ref validation)
              → deterministic scoring (Python)
              → narrator (executive summary)
              → persist findings + messages
```

## Why these design choices

| Choice | Reason |
| --- | --- |
| **Deterministic Python scoring** | The LLM never produces the number the user sees. A score drop is always attributable to a specific input change, not model temperature. See `scoring.py`. |
| **Adapter layer** | Agents read facts via typed adapters, not raw CSVs. Caching, column renames, and source swaps live in one place. |
| **JSON-schema enforcement** | Every agent reply is validated with `jsonschema` before being trusted. Schema failures trigger one repair attempt with a tighter prompt. |
| **Evidence refs** | Every finding cites a `<namespace>:<dotted.path>` key (e.g. `gsc:underperforming_queries[3].query`). The critic checks set-membership against the authoritative key list built deterministically by the orchestrator — the LLM cannot fabricate a citation. |
| **Conversation log persisted** | Every agent message + cost lands in `SEORunMessage`. Replayable for audit. |
| **No framework** | LangGraph / CrewAI add a debugging surface bigger than the orchestrator they'd replace. ~120 lines of plain Python beats a graph DSL at this scale. Revisit if specialist count > 6. |
| **Trimmed payloads** | Groq free tier caps `openai/gpt-oss-120b` at 8 000 tokens/minute. We send 6–10 example URLs per category plus rolled-up totals — enough to ground recommendations, not enough to hit the cap. |
| **Critic derives `rejected_indices` itself** | `gpt-oss-120b` occasionally emits concatenated-string arrays like `"01345"` instead of `[0,1,3,4,5]`. We ask only for `per_finding[].supported` and compute rejection in Python. |

## Configuration

All settings flow through `.env` → `config/settings/base.py`:

```bash
LLM_PROVIDER=groq                              # or "stub" for offline tests
GROQ_API_KEY=gsk_...
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=openai/gpt-oss-120b
GROQ_MAX_TOKENS=4096
GROQ_TEMPERATURE=0.2

SEMRUSH_API_KEY=...
SEMRUSH_DATABASE=in
SEMRUSH_DEFAULT_LIMIT=100

SEO_AI_DATA_DIR=          # default: backend/data/
SEO_AI_GSC_DATA_DIR=      # default: backend/data/gsc/
SEO_AI_SITEMAP_DIR=       # default: backend/data/aem/
SEO_AI_MAX_FINDINGS_PER_AGENT=20
SEO_AI_BUDGET_USD_PER_RUN=2.00
```

## Running

### Smoke test (synchronous, uses SQLite)

```bash
cd backend
../.venv/Scripts/python.exe smoke_test_seo_ai.py [domain]
```

The smoke test:
- Hard-overrides `DJANGO_SETTINGS_MODULE=config.settings.dev_sqlite`
  so it works without Postgres.
- Loads `.env` via a tiny in-script parser (no `python-dotenv` needed).
- Creates a `SEORun` and executes the orchestrator inline.
- Prints overall score, sub-scores, top findings, and the executive
  summary.

### REST endpoints

Once the Django dev server is up (`python manage.py runserver` against
your real settings) and a Celery worker is consuming:

```
POST /api/v1/seo/grade/start/         body: {"domain":"bajajlifeinsurance.com","sync":true}
GET  /api/v1/seo/grade/                list recent runs
GET  /api/v1/seo/grade/<id>/           run header + scores
GET  /api/v1/seo/grade/<id>/findings/  filterable by ?agent=technical|keyword
GET  /api/v1/seo/grade/<id>/messages/  conversation log (for replay UI)
```

The `sync=true` flag runs the orchestrator inline so the response
carries the score — useful for dev before Celery is wired in.
Production should use the default (async, `202` + run id).

### Production deployment (sketch)

1. Switch `DJANGO_SETTINGS_MODULE` to `config.settings.prod`.
2. Apply migrations against Postgres (`makemigrations seo_ai` was run
   on SQLite; the migration files are portable).
3. Start a Celery worker: `celery -A config worker -l info -Q default`.
4. Schedule `seo_ai.run_grade_task` via Celery beat if you want
   recurring runs. The orchestrator handles refresh-or-skip internally.

## Files outside this app that were added/touched

- `.env` — added `GROQ_*`, `LLM_*`, `SEO_AI_*`, `SEMRUSH_DATABASE`.
- `.gitignore` — already broad enough; no change needed.
- `backend/config/settings/base.py` — added `apps.seo_ai`,
  `SEO_AI`, `LLM`, `SEMRUSH` settings blocks.
- `backend/config/settings/dev_sqlite.py` — new dev profile so the
  smoke test runs without Postgres.
- `backend/requirements/base.txt` — added `openai`, `pydantic`,
  `jsonschema`.
- `backend/api/urls.py` — mounted `apps.seo_ai.urls` at `/api/v1/seo/`.
- `backend/scripts/gsc_pull.py` — moved from `test/gsc_pull.py`,
  paths anchored on `backend/data/gsc/`. OAuth client secret + token
  + pulled CSVs all colocate there (gitignored via `backend/data/`).
- `backend/smoke_test_seo_ai.py` — one-shot verification script.
- `backend/data/` — single root for every runtime artefact:
  `gsc/` (Search Console), `aem/` (page-model JSON), `_semrush_cache/`,
  and the crawler's existing `crawl_*.csv` outputs. The old top-level
  `test/` and `sitemap/` directories were removed; 4 byte-identical
  AEM duplicates were dropped during the consolidation (md5-verified).

## Phase 1 backlog (next, not yet implemented)

In priority order:

1. **Server-Sent-Events stream** — `/grade/<id>/stream` so the UI
   can show the agents talking as it happens.
2. **Content Analyzer agent** — needs pgvector embeddings of AEM
   content. Plan §4.2.
3. **Competitor Intelligence agent** — needs scheduled crawls of
   HDFC Life, Tata AIA, ICICI Pru, Max Life. Plan §4.3.
4. **Real CWV** — replace the response-time proxy with PageSpeed
   Insights / CrUX. Plan §10.
5. **Frontend `/grade` page** — see plan §11.
6. **Soften scoring penalties** — current `technical` formula went
   to 0.0 on the live site because penalties stack too aggressively.
   Re-tune against the real-data baseline.
7. **Eval harness** — golden dataset + CI gate on prompt changes.
   Plan §12.

## Known caveats

- `technical` sub-score is currently 0.0 against the live site —
  penalty formula is too punitive for the real-world numbers.
  Cosmetic only; the finding list is rich and useful.
- Critic rejected 15 / 19 findings on the verified run. Some
  rejections are legitimate (the model invented adjacent metrics),
  some are over-strict (formatting variance in evidence refs). The
  bias toward rejection is intentional for v1.
- `openai/gpt-oss-120b` on the Groq free tier is 8 000 TPM — we
  ride right under that. Upgrade to Dev tier removes this constraint
  if you scale.
