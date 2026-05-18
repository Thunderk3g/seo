# Data Sources

How every external data source in this project is wired up — API keys, what
we pull, where it's used in the code, and what it costs.

This folder is the operator's manual for the keys in `.env`. If something
in the dashboard is missing data, you can almost always trace it to a
provider listed here.

## Files

| File | Source | Key vars |
|---|---|---|
| [`gsc.md`](./gsc.md) | Google Search Console (OAuth + URL Inspection + Sitemaps + Coverage) | OAuth token in `backend/data/gsc/` |
| [`semrush.md`](./semrush.md) | SEMrush (organic keywords, competitor discovery, top pages) | `SEMRUSH_API_KEY` |
| [`serpapi.md`](./serpapi.md) | SerpAPI (Google / Bing / DuckDuckGo SERPs) | `SERPAPI_API_KEY` |
| [`llm-providers.md`](./llm-providers.md) | Groq (primary) + OpenAI / Anthropic / Google / Perplexity / xAI (AI-visibility probes) | `GROQ_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `PERPLEXITY_API_KEY`, `XAI_API_KEY` |
| [`internal.md`](./internal.md) | Internal sources: AEM JSON exports, our own crawler, GSC CSV ingestion paths | `SEO_AI_SITEMAP_DIR`, `SEO_AI_GSC_DATA_DIR` |

## Where the keys live

| Surface | File | Gitignored? |
|---|---|---|
| Local development | `.env` (repo root) | ✅ yes — never committed |
| Docker container | env via `env_file: [.env]` in `docker-compose.yml` | inherits from `.env` |
| OAuth tokens (GSC) | `backend/data/gsc/token.json`, `backend/data/gsc/client_secret_*.json` | ✅ yes |
| Cached responses | `backend/data/_semrush_cache/`, `backend/data/_serp_cache/`, `backend/data/_competitor_cache/`, `backend/data/_ai_visibility_cache/` | ✅ yes |

The whole `backend/data/` tree is gitignored — it holds the keys, the
caches, and the crawler output, so nothing sensitive ever lands in git.

## Quick health check

```bash
# Show which keys are configured (without revealing values)
docker exec seo-backend-1 python -c "
from django.conf import settings; import os, django
django.setup() if not settings.configured else None
def has(name): return '✓' if os.environ.get(name) else '✗'
for k in ('SEMRUSH_API_KEY', 'SERPAPI_API_KEY', 'GROQ_API_KEY',
          'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GOOGLE_API_KEY',
          'PERPLEXITY_API_KEY', 'XAI_API_KEY'):
    print(f'  {has(k)} {k}')
"
```

## Per-source feature gating

Every adapter follows the same pattern: if the key is missing, the agent
that uses it is **silently skipped** — never raises. This means you can
turn off any single source by clearing its env var without breaking the
rest of the stack. See each file in this folder for the exact env-var
toggles and how they propagate.
