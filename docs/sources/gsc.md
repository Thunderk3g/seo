# Google Search Console (GSC)

The most important external data source. Surfaces what Google actually
knows about `bajajlifeinsurance.com` — which URLs are indexed, what
queries they rank for, sitemap submission state, and per-URL coverage
verdicts.

## Authentication — OAuth, not an API key

Despite the `GSC_API_KEY` placeholder env var in `.env`, GSC does **not**
use a static API key. It uses OAuth2 with the `webmasters.readonly`
scope. The token is acquired once via browser sign-in and cached locally.

| File | What's in it |
|---|---|
| `backend/data/gsc/client_secret_*.json` | OAuth client secret JSON downloaded from the Google Cloud Console |
| `backend/data/gsc/token.json` | Refresh + access tokens after first sign-in. Auto-refreshed on subsequent calls |

Both files are gitignored. To rotate the token, delete `token.json` and
re-run `backend/scripts/gsc_pull.py`; the script opens a browser to the
Google sign-in page.

## What we pull

### 1. Search Analytics (clicks / impressions / CTR / position)

The bulk of what we use. We pull every combination of:

| Dimensions | Output file |
|---|---|
| `query` | `web__query.csv` |
| `page` | `web__page.csv` (**also our "indexed URLs" set**) |
| `country` | `web__country.csv` |
| `device` | `web__device.csv` |
| `date` | `web__date.csv` |
| `searchAppearance` | `web__searchAppearance.csv` |
| `query × page`, `page × device`, `date × country`, ... | (cross-tab files) |

Files land under `backend/data/gsc/<site>/` (one folder per verified
property). Pulled separately for `web`, `image`, `video`, `news`,
`discover`, and `googleNews` search types.

History window: **16 months** (GSC's max). Free quota: 25,000 requests/day.

### 2. URL Inspection (per-URL definitive indexing verdict)

Use this to convert "unknown" indexing status into one of:
- `Submitted and indexed`
- `Crawled - currently not indexed`
- `Discovered - currently not indexed`
- `Page with redirect`
- `Duplicate, Google chose different canonical than user`
- `Excluded by 'noindex' tag`
- ...etc.

**Quota:** 2,000 inspections/day **per property**. So a 5,000-URL audit
takes 3 days of runs.

Triggered from the UI on `/crawler/reports` via the "Verify unknowns"
button on the GSC banner, or via CLI:

```bash
docker exec seo-backend-1 python manage.py gsc_inspect_unknowns --max 1900
```

### 3. Sitemaps (submitted + indexed counts per sitemap)

Per-sitemap metadata: last submitted date, errors/warnings, the
per-content-type aggregate `{submitted: N, indexed: M, type: web}`.
Pulled into `backend/data/gsc/<site>/sitemaps.json` alongside the
performance CSVs.

### 4. Sites (verified properties + permission levels)

Lists every property the OAuth account can access. Saved as
`backend/data/gsc/sites.json`.

## What we do NOT pull from GSC

| Surface | Why not |
|---|---|
| Coverage / Pages report aggregates (the "1.29k indexed / 2.04k non-indexed" numbers in the UI) | **No API exists** — only available via manual CSV export from the GSC UI |
| Links report | UI-only |
| Manual actions | UI-only |
| Rich Results aggregates | UI-only (per-URL state is available via URL Inspection) |
| Core Web Vitals aggregates | Use the **CrUX API** or PageSpeed Insights API instead — separate Google product |

## Code map

| File | Responsibility |
|---|---|
| `backend/scripts/gsc_pull.py` | Main OAuth pull. Walks every verified site × every dimension combo. Run interactively because of the browser sign-in step |
| `backend/apps/seo_ai/adapters/gsc_csv.py` | Reads the pulled CSVs into the SEO grading agents |
| `backend/apps/crawler/storage/gsc_loader.py` | Reads the GSC Coverage CSVs (manual export OR derived) into the coverage map used by the crawler reports |
| `backend/apps/crawler/storage/gsc_coverage_builder.py` | Derives a coverage CSV from `web__page.csv` + a live sitemap fetch. Also runs URL Inspection API. The `Pull coverage from GSC` and `Verify unknowns` buttons hit functions here |
| `backend/apps/crawler/management/commands/gsc_inspect_unknowns.py` | CLI wrapper for URL Inspection runs |
| `backend/apps/crawler/management/commands/gsc_build_coverage.py` | CLI wrapper for the derivation builder |

## How it's used by the dashboard

| UI surface | Uses |
|---|---|
| Reports → Indexing status cards | Coverage map (derived from `web__page.csv` + sitemap fetch, refined by URL Inspection) |
| Reports → Sitemap presence cards | Live sitemap.xml fetch (free, no quota) |
| Reports → Errors by type | Per-URL `indexed_status` from coverage map, joined onto crawler results |
| Competitor Gap → Indexed pages section | `web__page.csv` URL list |
| SEO Grading → Top queries / pages tiles | Search Analytics CSVs |

## Config env vars

| Var | Default | Purpose |
|---|---|---|
| `GSC_API_KEY` | empty | **Placeholder only** — GSC uses OAuth. Safe to leave blank |
| `SEO_AI_GSC_DATA_DIR` | `backend/data/gsc/` | Where to find / write the pulled CSVs |

## Operator workflow

1. **First time / token rotation:**
   ```bash
   python backend/scripts/gsc_pull.py
   ```
   Opens browser → Google sign-in → writes `token.json` and pulls 16 months of data. **~10 minutes** for a full pull across all dimensions.

2. **Coverage refresh** (after fresh GSC export or after a new crawl):
   ```bash
   docker exec seo-backend-1 python manage.py gsc_build_coverage --backfill-sitemap
   ```
   Builds `coverage_derived_<date>.csv` and rewrites the `indexed_status`
   column on every crawler CSV.

3. **URL Inspection sweep** (optional, when you want definitive verdicts
   on unknowns):
   ```bash
   docker exec seo-backend-1 python manage.py gsc_inspect_unknowns --max 1900
   ```
   2,000/day quota — run on consecutive days for full coverage of a
   ~6,000-URL set.
