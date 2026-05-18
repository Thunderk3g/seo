# SerpAPI

The traditional-SERP visibility layer. For each pipeline query, asks
Google / Bing / DuckDuckGo what the top organic results are, captures
featured snippets, "people also ask", and AI Overviews — and tells us
where (if anywhere) `bajajlifeinsurance.com` sits in the rankings.

## Authentication — static API key

| Var | Used as |
|---|---|
| `SERPAPI_API_KEY` | Required. Sent as `api_key=` on every call to `serpapi.com/search.json` |

## Pricing tiers

SerpAPI is paid, but has a free tier.

| Plan | $/month | Searches/month | Runs at default config* |
|---|---|---|---|
| **Free** | $0 | 250 | ~4 full runs (60 calls/run) |
| Developer | $75 | 5,000 | ~83 runs (daily) |
| Production | $150 | 15,000 | 250+ runs |
| Big Data | $275 | 30,000 | massive |

*Each pipeline run hits `SERP_API_MAX_QUERIES × len(SERP_API_ENGINES)`
calls — default 20 × 3 = 60. Asking for more results-per-query (`num=25`)
does NOT increase the call count; it just changes the response payload.

Current account state:
- Account: `tanishjagtap91@gmail.com`
- Plan: Free Plan (250/month, ~178 left at last check)
- Rate limit: 250/hour

## What we pull per call

Each `serpapi.com/search.json?q=<query>&engine=<google|bing|duckduckgo>`
call returns a normalised `SerpResult`:

| Field | Description |
|---|---|
| `organic` | Top N organic results (position, title, URL, domain, snippet). N controlled by `SERP_API_RESULTS_PER_QUERY` (default 25 for Google + Bing; DuckDuckGo is engine-capped at ~10–20) |
| `featured_snippet` | If present — the "answer box" at the top of the SERP |
| `people_also_ask` | Up to 10 follow-up question texts |
| `ai_overview` | If present — Google AI Overview text blocks + cited URLs |
| `related_searches` | Up to 10 "related searches" |

## Engines and what they each charge

All three engines bill **one search per call**, equal cost. The
breakdown of what you get differs:

| Engine | `num` knob | Typical results per call | AI Overview |
|---|---|---|---|
| Google | `num=25` works | up to 25 | Sometimes — when query qualifies |
| Bing | `count=25` works | up to 25 | No (Bing has its own Copilot, not exposed via SerpAPI) |
| DuckDuckGo | not supported | fixed ~10–20 by DuckDuckGo | No |

## Code map

| File | Responsibility |
|---|---|
| `backend/apps/seo_ai/adapters/serp_api.py` | SerpAPIAdapter — single HTTP client per call, 7-day disk cache, normalises every engine's response into `SerpResult` |
| `backend/apps/seo_ai/gap_pipeline/serp_search.py` | Gap pipeline Stage 3 — runs every (query × engine) combo, writes `GapSerpResult` rows to the DB |

## How it's used by the dashboard

| UI surface | SerpAPI data used |
|---|---|
| Competitor Gap → Discovery Pipeline → "What the web SERP returned" | Per-engine summary: queries hit, top-3 organic, AI Overviews present, featured snippets |
| Competitor Gap → SERP Results panel | Full organic results table — query × engine × position × competitor URL |
| Gap pipeline competitor scoring | Aggregate rank counts that go into the "Top competitors" ranked list |

## Config env vars

| Var | Default | Purpose |
|---|---|---|
| `SERP_API_ENABLED` | `true` | **Master kill switch.** Set `false` to silently skip Stage 3 (useful when on the free tier and conserving quota) |
| `SERP_API_PROVIDER` | `serpapi` | Reserved for future DataForSEO / Zenserp swaps; only `serpapi` implemented today |
| `SERPAPI_API_KEY` | (required) | Static API key |
| `SERP_API_ENGINES` | `google,bing,duckduckgo` | Comma-separated. Each one multiplies your call count |
| `SERP_API_COUNTRY` | `in` | `gl=` param — India SERPs |
| `SERP_API_LANGUAGE` | `en` | `hl=` param |
| `SERP_API_MAX_QUERIES` | `20` | Cap on queries per pipeline run. Combined with `engines`, controls calls/run |
| `SERP_API_RESULTS_PER_QUERY` | `25` | Top-N organic results per call. **Free** to crank higher — SerpAPI bills per call, not per result |
| `SERP_API_REQUEST_TIMEOUT_SEC` | `30` | Per-call HTTP timeout |
| `SERP_API_CACHE_TTL` | `604800` (7 days) | Disk-cache TTL |
| `SERP_API_SSL_VERIFY` | `false` | Set false inside the Docker container — corp MITM proxy issue |

## Caching

Disk cache at `backend/data/_serp_cache/`. Cache key is
`sha1(engine|country|language|n=<results_per_query>|query)`, so
changing `SERP_API_RESULTS_PER_QUERY` automatically invalidates old
entries (same-week re-runs on the same N are free).

Clearing the cache:
```bash
rm -rf backend/data/_serp_cache/
```
Warning — next pipeline run will burn 60+ fresh API calls.

## Free-tier-safe configs

If staying on the 250-call/month plan, throttle one of these axes:

```ini
# Option A: just Google, full query set (= 20 calls/run, 12 runs/month)
SERP_API_ENGINES=google
SERP_API_MAX_QUERIES=20

# Option B: all 3 engines, fewer queries (= 30 calls/run, 8 runs/month)
SERP_API_ENGINES=google,bing,duckduckgo
SERP_API_MAX_QUERIES=10

# Option C: kill switch
SERP_API_ENABLED=false
```

## Operator notes

- Check live quota:
  ```bash
  curl "https://serpapi.com/account.json?api_key=$SERPAPI_API_KEY"
  ```
- Failed calls (network / 4xx / 5xx) do NOT count toward your monthly
  quota — only successful searches do.
- The adapter NEVER raises out of `.search()` — failed engines just
  return a `SerpResult` with `error` filled in. The pipeline treats an
  erroring engine the same as "no data".
