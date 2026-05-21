"""Base settings for Django 12-factor project."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.common",
    "apps.crawler",
    "apps.seo_ai",
    # apps.crawl_sessions removed — replaced by the file-backed crawler-engine
    # port now living in apps.crawler. The following apps still reference
    # the deleted ORM models (CrawlSession / Page / Link / etc.) and will
    # need rework before they can be re-enabled:
    #   - apps.ai_agents
    #   - apps.gsc_integration
    #   - apps.dashboard
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "seo_db"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "postgres"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

STATIC_URL = "/static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─────────────────────────────────────────────────────────────
# REST Framework
# ─────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# ─────────────────────────────────────────────────────────────
# Celery Configuration
# ─────────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

# ─────────────────────────────────────────────────────────────
# SEO AI Agent System
# ─────────────────────────────────────────────────────────────
# All data sources live under backend/data/ so the deployable backend
# is self-contained — no scratch directories in the project root, no
# absolute paths to host-specific scratch dirs. Subtypes:
#   backend/data/                  → crawler CSVs + crawl_state.json (legacy default)
#   backend/data/gsc/              → Search Console pull (gsc_pull.py output + OAuth files)
#   backend/data/aem/              → AEM page-model JSON exports
#   backend/data/_semrush_cache/   → SEMrush response cache
# Every path is still overridable via .env so prod can mount volumes
# elsewhere.

SEO_AI = {
    "data_dir": Path(
        os.environ.get("SEO_AI_DATA_DIR") or (BASE_DIR / "data")
    ),
    "gsc_data_dir": Path(
        os.environ.get("SEO_AI_GSC_DATA_DIR") or (BASE_DIR / "data" / "gsc")
    ),
    "sitemap_dir": Path(
        os.environ.get("SEO_AI_SITEMAP_DIR") or (BASE_DIR / "data" / "aem")
    ),
    "max_findings_per_agent": int(os.environ.get("SEO_AI_MAX_FINDINGS_PER_AGENT", "20")),
    "budget_usd_per_run": float(os.environ.get("SEO_AI_BUDGET_USD_PER_RUN", "2.00")),
}

LLM = {
    "provider": os.environ.get("LLM_PROVIDER", "groq"),
    # TLS verification for outbound LLM calls. Accepts:
    #   "" / unset / "true"  → default (certifi + truststore on Windows)
    #   "false"              → disable verification (dev only — corp MITM)
    #   "/path/to/ca.pem"    → custom CA bundle, e.g. corporate root CA
    "ssl_verify": os.environ.get("LLM_SSL_VERIFY", "").strip(),
    "groq": {
        "api_key": os.environ.get("GROQ_API_KEY", ""),
        "base_url": os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        "model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
        "max_tokens": int(os.environ.get("GROQ_MAX_TOKENS", "4096")),
        "temperature": float(os.environ.get("GROQ_TEMPERATURE", "0.2")),
    },
}

SEMRUSH = {
    "api_key": os.environ.get("SEMRUSH_API_KEY", ""),
    "database": os.environ.get("SEMRUSH_DATABASE", "in"),
    "default_limit": int(os.environ.get("SEMRUSH_DEFAULT_LIMIT", "100")),
    # Same semantics as LLM_SSL_VERIFY above. Needed inside the Docker
    # image because the Debian-slim trust store lacks the corp MITM root.
    "ssl_verify": os.environ.get("SEMRUSH_SSL_VERIFY", "").strip(),
    # Competitor-discovery and top-pages calls bill the same units but
    # change far less often than headline overviews — give them a much
    # longer TTL so day-to-day grade re-runs don't burn the budget.
    "competitor_cache_ttl": int(
        os.environ.get("SEMRUSH_COMPETITOR_CACHE_TTL", str(7 * 24 * 3600))
    ),
}

# Competitor SEO Gap analysis — discovers our top organic rivals via
# SEMrush, samples their best pages, and feeds the CompetitorAgent.
# Disabled silently when SEMRUSH_API_KEY is unset or COMPETITOR_ENABLED
# is "false"; never crashes a grading run.
COMPETITOR = {
    "enabled": os.environ.get("COMPETITOR_ENABLED", "true").lower()
    in ("1", "true", "yes", "on"),
    "top_n": int(os.environ.get("COMPETITOR_TOP_N", "10")),
    "pages_per_competitor": int(os.environ.get("COMPETITOR_PAGES_PER_COMP", "50")),
    "keywords_per_competitor": int(os.environ.get("COMPETITOR_KW_PER_COMP", "100")),
    "rate_limit_sec": float(os.environ.get("COMPETITOR_RATE_LIMIT_SEC", "1.0")),
    "timeout_sec": int(os.environ.get("COMPETITOR_TIMEOUT_SEC", "15")),
    # Phase 2A — how many of OUR top URLs to crawl live for the
    # symmetric comparison. 200 ≈ 4 min crawl at 1 req/s.
    "our_pages_limit": int(os.environ.get("COMPETITOR_OUR_PAGES_LIMIT", "200")),
    # Bot-identifiable UA strings get 403'd by Cloudflare/Akamai on
    # most enterprise sites, so default to a recent Chrome UA. We still
    # respect robots.txt and rate-limit at COMPETITOR_RATE_LIMIT_SEC,
    # i.e. behave as a single human user.
    "user_agent": os.environ.get(
        "COMPETITOR_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    ),
    "cache_ttl_seconds": int(
        os.environ.get("COMPETITOR_CACHE_TTL_SECONDS", str(7 * 24 * 3600))
    ),
    # Same semantics as SEMRUSH_SSL_VERIFY. Inside the Docker image set
    # to "false" because the Debian trust store doesn't include the
    # corporate MITM root that intercepts competitor HTTPS traffic.
    "ssl_verify": os.environ.get("COMPETITOR_SSL_VERIFY", "").strip(),
    # Hard byte cap on the response body. ``0`` (or negative) disables
    # the cap entirely — needed for the AEM-vs-competitor content
    # comparison view, which wants the full body of every sampled page.
    # Default 100 MB is a soft safety net for pathological responses
    # from untrusted competitor hosts; flip to 0 in .env to take it off.
    "max_body_bytes": int(
        os.environ.get("COMPETITOR_MAX_BODY_BYTES", str(100 * 1024 * 1024))
    ),
    # Number of fetch attempts before giving up on a URL. Each attempt
    # is followed by exponential backoff with jitter (same shape as the
    # in-house fetcher). Default 3 means one fetch + two retries.
    "retry_attempts": int(os.environ.get("COMPETITOR_RETRY_ATTEMPTS", "3")),
    # Error responses (4xx / 5xx / network) are cached with a SHORT
    # TTL so a transient 503 doesn't lock out a competitor for the
    # full 7-day cache window. Default 1 hour. 200 responses still
    # use cache_ttl_seconds.
    "error_cache_ttl_seconds": int(
        os.environ.get("COMPETITOR_ERROR_CACHE_TTL_SECONDS", "3600")
    ),
    # Parallel fetching across hosts. Each unique host still respects
    # its own rate_limit_sec; this caps how many hosts can be in flight
    # simultaneously. With 10 competitors typically on 10 distinct CDNs,
    # 10 is fine. Set to 1 for fully-sequential legacy behaviour.
    "fetch_concurrency": int(os.environ.get("COMPETITOR_FETCH_CONCURRENCY", "10")),
    # Max characters of visible body text kept per page after HTML
    # stripping. ``0`` (or negative) = unlimited — every word from
    # navbar to footer survives into ``CompetitorPage.body_text`` and
    # downstream into ``GapDeepCrawl.profile.sample_pages[].body_text``.
    # Default 0 because the AEM-vs-competitor comparison flow needs the
    # full text. Set a positive value (e.g. 200000 for ~30k words) to
    # cap if Postgres JSONB rows start getting unwieldy.
    "body_text_max_chars": int(
        os.environ.get("COMPETITOR_BODY_TEXT_MAX_CHARS", "0")
    ),
    # Engine selector. "legacy" = the requests + BeautifulSoup fetcher
    # in adapters/competitor_crawler.py (default — battle-tested across
    # six callers). "scrapy" routes through adapters/
    # competitor_crawler_scrapy.py which spawns the Scrapy spider
    # (apps.seo_ai.spiders.competitor_spider.CompetitorSpider) in a
    # subprocess per competitor domain and persists every fetched page
    # to CrawlerPageResult so per-competitor Health Score works.
    #
    # The Scrapy path keeps body_text capture identical — no content
    # is dropped. It also runs the audit detectors against the
    # competitor's snapshot, so each domain ends up with a Health
    # Score visible via /api/v1/crawler/competitors/<domain>/health.
    "engine": os.environ.get("COMPETITOR_ENGINE", "legacy").strip().lower(),
    # When the Scrapy engine is active, this toggles the Playwright
    # JS-rendering gate (same middleware used by BajajSpider). Off by
    # default because Playwright adds ~3s/page; flip on for SPA-heavy
    # competitor rosters (ICICI Pru, Tata AIA) where the static fetch
    # returns thin HTML.
    "use_playwright_fallback": os.environ.get(
        "COMPETITOR_USE_PLAYWRIGHT_FALLBACK", "false",
    ).strip().lower() in ("1", "true", "yes", "on"),
}

# ─────────────────────────────────────────────────────────────
# Apify — Meta Ad Library (competitor ad intel via scraper-as-a-service).
# ─────────────────────────────────────────────────────────────
# Why Apify instead of Graph API directly: the corp Cisco WSA filter
# blocks `graph.facebook.com` at the URL-category layer (social-media).
# Apify scrapes the public Ad Library from their own infrastructure and
# returns the data via `api.apify.com`, which is in the allow-list
# (whitelisted business-data service, same class as SEMrush + SerpAPI).
#
# Actor used: ``curious_coder/facebook-ads-library-scraper`` — 12.8M+
# runs, ~$0.75 / 1000 ads. The free tier starts with $5 credit which
# covers ~6,000 ad records.
APIFY = {
    "enabled": bool(os.environ.get("APIFY_API_TOKEN", "").strip()),
    "api_token": os.environ.get("APIFY_API_TOKEN", "").strip(),
    "meta_ads_actor": os.environ.get(
        "APIFY_META_ADS_ACTOR",
        "curious_coder~facebook-ads-library-scraper",
    ),
    # Competitor list source-of-truth is the latest GapPipelineRun.
    # The view dynamically resolves competitors from GapCompetitor rows
    # (the same competitors the deep crawl identified). This env-var
    # exists only as a fallback when no GapPipelineRun has been run
    # yet on a fresh install; leave it empty to force the dynamic path.
    "default_meta_ads_competitors": [
        c.strip() for c in os.environ.get(
            "APIFY_META_ADS_COMPETITORS", "",
        ).split(",") if c.strip()
    ],
    "default_country": os.environ.get("APIFY_DEFAULT_COUNTRY", "IN"),
    # Per-competitor ad cap. Actor enforces a 10-row minimum. 25 is a
    # good "show me the top creatives" snapshot without burning credits.
    "default_count_per_competitor": int(
        os.environ.get("APIFY_DEFAULT_COUNT_PER_COMPETITOR", "25")
    ),
    # Disk cache TTL — Meta ad churn is slow enough that 24h is fine.
    "cache_ttl_seconds": int(
        os.environ.get("APIFY_CACHE_TTL_SECONDS", str(24 * 3600))
    ),
    # SSL verify — Docker base lacks corp MITM root.
    "ssl_verify": os.environ.get("APIFY_SSL_VERIFY", "false").strip(),
}

# ─────────────────────────────────────────────────────────────
# Adobe Analytics 2.0 — operator-approved per
# docs/SEO_TOOLS_ARCHITECTURE/API_KEYS_AND_FALLBACKS.md
# ─────────────────────────────────────────────────────────────
# Server-to-Server OAuth (client_credentials grant) → IMS token →
# Analytics 2.0 endpoints under https://analytics.adobe.io/api/{cid}/.
# Disabled silently when ADOBE_CLIENT_ID is unset; never crashes a
# render. Token caching + 24-hour TTL is handled by the adapter.
ADOBE_ANALYTICS = {
    "enabled": bool(os.environ.get("ADOBE_CLIENT_ID", "").strip()),
    "client_id": os.environ.get("ADOBE_CLIENT_ID", "").strip(),
    "client_secret": os.environ.get("ADOBE_CLIENT_SECRET", "").strip(),
    "global_company_id": os.environ.get("ADOBE_GLOBAL_COMPANY_ID", "").strip(),
    "rsid": os.environ.get("ADOBE_RSID", "").strip(),
    "lead_hash_evar": os.environ.get("ADOBE_LEAD_HASH_EVAR", "").strip(),
    # SSL verification — same shape as SEMRUSH_SSL_VERIFY. Default empty
    # means truststore is injected at import-time so corp MITM proxies
    # work without disabling verification.
    "ssl_verify": os.environ.get("ADOBE_SSL_VERIFY", "").strip(),
    "ims_token_url": "https://ims-na1.adobelogin.com/ims/token/v3",
    "analytics_base": "https://analytics.adobe.io/api",
    "default_lookback_days": int(
        os.environ.get("ADOBE_DEFAULT_LOOKBACK_DAYS", "7")
    ),
    "default_top_pages_limit": int(
        os.environ.get("ADOBE_DEFAULT_TOP_PAGES_LIMIT", "25")
    ),
}

# ─────────────────────────────────────────────────────────────
# AI Search Visibility (Phase 2 of the competitor-gap detection suite)
# ─────────────────────────────────────────────────────────────
# Probes multiple LLM-based search engines to detect whether the focus
# domain is cited / mentioned vs. its rivals. Every provider key is
# independent — missing OPENAI_API_KEY skips the OpenAI probe but the
# Anthropic / Gemini / Perplexity / xAI probes still run. The agent
# itself is disabled silently when AI_VISIBILITY_ENABLED is "false" or
# every provider key is empty.
AI_VISIBILITY = {
    "enabled": os.environ.get("AI_VISIBILITY_ENABLED", "true").lower()
    in ("1", "true", "yes", "on"),
    "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
    "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    "google_api_key": os.environ.get("GOOGLE_API_KEY", ""),
    "perplexity_api_key": os.environ.get("PERPLEXITY_API_KEY", ""),
    "xai_api_key": os.environ.get("XAI_API_KEY", ""),
    # Optional model overrides per provider — leave blank to use each
    # adapter's documented default.
    "openai_model": os.environ.get("OPENAI_AI_VISIBILITY_MODEL", "gpt-4o-mini"),
    "anthropic_model": os.environ.get(
        "ANTHROPIC_AI_VISIBILITY_MODEL", "claude-3-5-haiku-latest"
    ),
    "google_model": os.environ.get(
        "GOOGLE_AI_VISIBILITY_MODEL", "gemini-2.0-flash"
    ),
    "perplexity_model": os.environ.get(
        "PERPLEXITY_AI_VISIBILITY_MODEL", "sonar"
    ),
    "xai_model": os.environ.get("XAI_AI_VISIBILITY_MODEL", "grok-2-latest"),
    "max_queries": int(os.environ.get("AI_VISIBILITY_MAX_QUERIES", "20")),
    "request_timeout_sec": int(
        os.environ.get("AI_VISIBILITY_REQUEST_TIMEOUT_SEC", "30")
    ),
    "cache_ttl_seconds": int(
        os.environ.get("AI_VISIBILITY_CACHE_TTL", str(7 * 24 * 3600))
    ),
    "ssl_verify": os.environ.get("AI_VISIBILITY_SSL_VERIFY", "").strip(),
}

# ─────────────────────────────────────────────────────────────
# SERP API (Phase 3 of the competitor-gap detection suite)
# ─────────────────────────────────────────────────────────────
# Traditional SERP visibility via SerpAPI. The provider key allows
# swapping in DataForSEO / Zenserp later without changing the adapter
# interface; only SerpAPI is implemented this iteration. The agent is
# silently skipped when no SERPAPI_API_KEY is configured.
SERP_API = {
    "enabled": os.environ.get("SERP_API_ENABLED", "true").lower()
    in ("1", "true", "yes", "on"),
    "provider": os.environ.get("SERP_API_PROVIDER", "serpapi"),
    "api_key": os.environ.get("SERPAPI_API_KEY", ""),
    "engines": tuple(
        e.strip()
        for e in os.environ.get(
            "SERP_API_ENGINES", "google,bing,duckduckgo"
        ).split(",")
        if e.strip()
    ),
    # Device split — Google honours `device=desktop|mobile|tablet`. Each
    # device is a SEPARATE billed SerpAPI call, so the run cost scales
    # linearly with len(devices). Default to both desktop + mobile so
    # the dashboard can show how rankings differ across surfaces.
    "devices": tuple(
        d.strip().lower()
        for d in os.environ.get(
            "SERP_API_DEVICES", "desktop,mobile"
        ).split(",")
        if d.strip()
    ),
    # The "primary" device whose rows feed competitor aggregation and
    # the visibility comparison. Multi-device probes are persisted but
    # only this device counts toward leaderboard/dedupe to avoid
    # double-counting the same competitor across devices.
    "primary_device": (
        os.environ.get("SERP_API_PRIMARY_DEVICE", "desktop").strip().lower()
        or "desktop"
    ),
    "country": os.environ.get("SERP_API_COUNTRY", "in"),
    "language": os.environ.get("SERP_API_LANGUAGE", "en"),
    "max_queries": int(os.environ.get("SERP_API_MAX_QUERIES", "20")),
    # Number of organic results to request per (query, engine). One
    # SerpAPI call is billed the same whether we ask for 10 or 100 —
    # only the response payload grows. Defaults to 25 so each query
    # surfaces a broader competitor set in the report.
    "results_per_query": int(os.environ.get("SERP_API_RESULTS_PER_QUERY", "25")),
    "request_timeout_sec": int(
        os.environ.get("SERP_API_REQUEST_TIMEOUT_SEC", "30")
    ),
    "cache_ttl_seconds": int(
        os.environ.get("SERP_API_CACHE_TTL", str(7 * 24 * 3600))
    ),
    "ssl_verify": os.environ.get("SERP_API_SSL_VERIFY", "").strip(),
}

# ─────────────────────────────────────────────────────────────
# PageSpeed Insights (Core Web Vitals enrichment for competitor pages)
# ─────────────────────────────────────────────────────────────
# Calls Google's PSI API to capture LCP/CLS/INP/FCP/TBT/TTFB for each
# competitor page — both lab (Lighthouse) and field (CrUX) metrics.
# Authenticated via a Google Cloud service account so the daily quota
# (25k calls) bills against our project. Silently disabled when the
# service-account file is missing or PSI_ENABLED is "false".
#
# The SA needs no special IAM role beyond the default; PSI accepts any
# bearer token from a project that has the PageSpeed Insights API
# enabled (scopes used: openid + userinfo.email).
def _resolve_repo_path(raw: str, default: Path) -> str:
    """Resolve a path env var across host (BASE_DIR=backend/) and Docker
    (BASE_DIR=/app, where backend/data is mounted to /app/data via the
    compose volume).

    Strategy:
      * Absolute paths pass through.
      * Relative paths starting with ``backend/`` get that prefix
        stripped, then resolve against BASE_DIR — so the same
        ``.env`` value works on host (becomes ``backend/data/...``)
        and inside the container (becomes ``/app/data/...``).
      * Other relative paths also resolve against BASE_DIR.
    """
    if not raw:
        return str(default)
    p = Path(raw.strip())
    if p.is_absolute():
        return str(p)
    parts = p.parts
    if parts and parts[0] == "backend":
        p = Path(*parts[1:]) if len(parts) > 1 else Path()
    return str(BASE_DIR / p)


PSI = {
    "enabled": os.environ.get("PSI_ENABLED", "true").lower()
    in ("1", "true", "yes", "on"),
    "service_account_json": _resolve_repo_path(
        os.environ.get("PSI_SERVICE_ACCOUNT_JSON", ""),
        BASE_DIR / "data" / "secrets" / "psi-sa.json",
    ),
    # Strategies to capture per URL. Each strategy = 1 PSI call. Default
    # to both so the audit can flag mobile-only regressions.
    "strategies": tuple(
        s.strip().lower()
        for s in os.environ.get("PSI_STRATEGIES", "mobile,desktop").split(",")
        if s.strip()
    ),
    # PSI mobile calls finish in 1-3s but desktop can take 30-40s. Set
    # generous timeout — these calls are slow, not flaky.
    "request_timeout_sec": int(os.environ.get("PSI_REQUEST_TIMEOUT_SEC", "120")),
    # Field/CrUX data shifts slowly (28-day rolling window) so 7-day
    # cache is safe. Lab data also reasonably stable for content audit.
    "cache_ttl_seconds": int(
        os.environ.get("PSI_CACHE_TTL", str(7 * 24 * 3600))
    ),
    # Cap per refresh — PSI quota is 25k/day; this prevents a runaway
    # crawl from burning the whole budget. Set to 0 for unlimited.
    "max_urls_per_run": int(os.environ.get("PSI_MAX_URLS_PER_RUN", "100")),
    # Concurrent PSI worker count used by both the in-house crawler's
    # inline scheduler (apps.crawler.engine.psi_scheduler) and the
    # competitor crawler's enrich_with_cwv pass. 4 is conservative —
    # Google PSI tolerates ~8 concurrent calls per IP before 429s.
    "inline_workers": int(os.environ.get("PSI_WORKERS", "4")),
    "ssl_verify": os.environ.get("PSI_SSL_VERIFY", "").strip(),
}

# ─────────────────────────────────────────────────────────────
# Logging Configuration
# ─────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
        },
    },
    "loggers": {
        "seo": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
        },
    },
}
