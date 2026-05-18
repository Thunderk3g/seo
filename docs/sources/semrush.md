# SEMrush

The competitor + keyword intelligence layer. Tells us which sites rank
against `bajajlifeinsurance.com`, what queries we're already winning,
and what queries our rivals own that we don't.

## Authentication — static API key

| Var | Used as |
|---|---|
| `SEMRUSH_API_KEY` | Required. Sent as the `key=` query parameter on every call to `api.semrush.com` |

The key shows up in `.env` line 28. SEMrush bills "API units" per call —
not requests — so a single response can cost 10, 40, or more units
depending on what's queried.

## What we pull

### 1. Domain overview (rank / traffic / keyword count)

Endpoint: `domain_ranks`
Cost: 10 units per call.
Returns the high-level position summary for one domain: organic search
keywords, organic traffic, paid keywords, paid traffic, rank.

### 2. Organic keywords for a domain

Endpoint: `domain_organic`
Cost: 10 units per row × number of rows requested.
Returns the keywords a domain currently ranks for, with position, search
volume, CPC, traffic share, etc. Limit set by `SEMRUSH_DEFAULT_LIMIT`
(default 100).

### 3. Competitor discovery — who else ranks for OUR queries

Endpoint: `domain_organic_organic`
Cost: 40 units per call.
Returns the list of domains that have organic-keyword overlap with the
target. Used to seed the "top 10 rivals" set on the Competitor
Dashboard.

### 4. Top organic pages for a competitor

Endpoint: `domain_organic_pages`
Cost: 10 units per row.
Used during the deep-crawl phase — once we know who the rivals are, we
ask SEMrush for their top organic pages and crawl those URLs ourselves
to inspect content depth, schema, etc.

## What we do NOT pull from SEMrush

- Backlinks — separate billing pool; not currently surfaced
- Brand-monitoring tools — out of scope
- Site audit module — we use our own crawler instead

## Code map

| File | Responsibility |
|---|---|
| `backend/apps/seo_ai/adapters/semrush.py` | Single HTTP client + disk cache (7-day TTL by default). All SEMrush requests go through this adapter |
| `backend/apps/seo_ai/agents/competitor.py` | `CompetitorAgent.build_facts()` orchestrates: domain_ranks for us, domain_organic_organic to find rivals, domain_organic + domain_organic_pages for each rival, then schedules our crawler to fetch sample pages |
| `backend/apps/seo_ai/gap_pipeline/query_synthesis.py` | Stage 1 of the gap pipeline reads SEMrush organic-keyword data (top 50 of ours + top 25 from each top-5 rival) and feeds them to Groq to generate the 24 visibility-probe queries |

## How it's used by the dashboard

| UI surface | SEMrush data used |
|---|---|
| Competitor Dashboard | Full pipeline — rival list, kw overlap counts, top pages |
| SEO Grading → Overview tile | `domain_ranks` for our own domain |
| Competitor Gap → Keyword gaps table | Cross-tab of our keywords vs rivals' top-ranking keywords |
| Discovery Pipeline → query synthesis | Top-50 our + top-25-per-rival keyword corpus, used as the LLM seed |

## Config env vars

| Var | Default | Purpose |
|---|---|---|
| `SEMRUSH_API_KEY` | (required) | Static API key |
| `SEMRUSH_DATABASE` | `in` | Geographic database. `in` = India SERPs |
| `SEMRUSH_DEFAULT_LIMIT` | `100` | Max rows per `domain_organic` call |
| `SEMRUSH_SSL_VERIFY` | `false` | Set false inside the Docker container — corporate MITM proxy breaks the Debian trust chain on `api.semrush.com` |
| `SEMRUSH_COMPETITOR_CACHE_TTL` | `604800` (7 days) | Disk-cache TTL for competitor + top-pages calls. Same-week re-runs cost 0 units |

## Caching

Disk cache at `backend/data/_semrush_cache/`. Every response is keyed by
the full request URL (params + endpoint) and saved as JSON. Cache TTL
is 7 days. Clearing the cache:

```bash
rm -rf backend/data/_semrush_cache/
```

Be deliberate — the next `Competitor Dashboard` load will re-fetch
~100 units worth of data.

## Operator notes

- The `bajajlifeinsurance.com` lookup currently uses ~150–200 units per
  fresh load (one `domain_ranks` + one `domain_organic_organic` + 10 ×
  `domain_organic` + 10 × `domain_organic_pages`).
- SEMrush units are pre-purchased; this account's balance is **not**
  visible from the API — check at `https://semrush.com/api-analytics/`.
- If you see HTTP 401 from the adapter, the key is wrong or out of units.
- If you see HTTP 200 but empty results, the domain may not be in the
  `in` database — try switching `SEMRUSH_DATABASE=us` temporarily.
