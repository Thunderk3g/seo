# Production deploy checklist

Hard requirements (boot will fail or behaviour will be unsafe if any
of these are skipped). Tick each one before flipping `DJANGO_SETTINGS_MODULE=config.settings.prod`.

## 1. Secrets

- [ ] **`SECRET_KEY`** — generate with
      `python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'`.
      Boot fails if missing or set to `dev-secret-key` /
      `replace-me-in-production`.
- [ ] **`ALLOWED_HOSTS`** — comma-separated, no scheme. Boot fails if
      empty.
- [ ] **`GROQ_API_KEYS`** — comma-separated pool. The `/api/v1/seo/llm/pool-stats/`
      endpoint shows live load distribution.
- [ ] **`PSI_API_KEY` / `PSI_SERVICE_ACCOUNT_JSON_PATH`** — rotate the
      JSON-SA private key that appeared in a previous transcript
      (`key id 559766c1d390...`). Do this in the GCP console *first*,
      then update the env, then `docker compose restart backend worker beat`.
- [ ] **`SEMRUSH_API_KEY`**, **`SERP_API_KEY`** — re-issue if any
      operator ever pasted them into a shared channel.
- [ ] Strip any `.env*` from the deployed image — `docker compose`
      reads `env_file: [.env]`; the actual file should never live in
      a baked image layer.

## 2. TLS posture (outbound)

Boot logs warn for each of these set to `false`:

- [ ] `LLM_SSL_VERIFY` → `true` (or path to corp CA bundle)
- [ ] `COMPETITOR_SSL_VERIFY` → `true`
- [ ] `SEMRUSH_SSL_VERIFY` → `true`
- [ ] `PSI_SSL_VERIFY` → `true`
- [ ] `AI_VISIBILITY_SSL_VERIFY` → `true`
- [ ] `ADOBE_SSL_VERIFY` → `true`
- [ ] `APIFY_SSL_VERIFY` → `true`
- [ ] `BRAND_MENTIONS_SSL_VERIFY` → `true`
- [ ] `SERP_API_SSL_VERIFY` → `true`

Behind a corp MITM proxy, point each at the corp CA bundle path
instead of disabling. `truststore` is already injected so on Windows
the system trust store works automatically — Linux needs the explicit
path.

## 3. HTTPS

`config/settings/prod.py` defaults are safe:

- `SECURE_SSL_REDIRECT=true`, `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO","https")`
- `SESSION_COOKIE_SECURE=true`, `CSRF_COOKIE_SECURE=true`
- `X_FRAME_OPTIONS=DENY`, `SECURE_REFERRER_POLICY=strict-origin-when-cross-origin`

Set when ready (start at 0 to avoid HSTS lock-in during the cutover):

- [ ] `SECURE_HSTS_SECONDS=31536000` (1 yr) once the cert + redirect
      chain is verified — this is irreversible client-side.

## 4. Static files

`whitenoise` is auto-inserted into MIDDLEWARE by `prod.py`. Before
deploy:

- [ ] `python manage.py collectstatic --noinput`
- [ ] Verify `staticfiles/` is in the image (or mounted volume).

## 5. Database

- [ ] Daily logical backup: `pg_dump -h db -U postgres seo_db | gzip > /backups/seo_db_$(date +%F).sql.gz`
- [ ] WAL archiving or PITR if recovery beyond yesterday is required.
- [ ] Fix the collation-version warning in dev/prod:
      `ALTER DATABASE seo_db REFRESH COLLATION VERSION;` then restart
      Postgres (warning, not data-corruption — but indexes built with
      the older glibc may need REINDEX after the OS upgrade).
- [ ] `CompetitorPageHistory` GC: `seo_ai.gc_competitor_history` runs
      Sun 04:30 IST with 90-day retention. Verify the celery `beat`
      service is up: `docker compose ps beat`.

## 6. Observability

- [ ] `SENTRY_DSN` set + `pip install sentry-sdk` in
      `requirements/prod.txt`. Once set, `prod.py` auto-wires Django +
      Celery integrations.
- [ ] `/api/v1/health/` wired to your ALB / k8s readinessProbe. 200 =
      all green, 503 = at least one of {db, redis} is red. LLM pool
      absence is warning-only (the deterministic crawler keeps working).
- [ ] `APP_VERSION` env set to the git SHA so health output is
      release-attributable.
- [ ] `LOG_LEVEL=INFO` (default). Drop to `WARNING` when a noisy
      vendor adapter is shouting too much.

## 7. CORS

Only set `CORS_ALLOWED_ORIGINS` if the SPA is served from a different
origin than the API. Default deploy serves both from the same host
behind the same reverse-proxy.

- [ ] If different origin: install `django-cors-headers` and set
      `CORS_ALLOWED_ORIGINS=https://spa.example.com` (comma-separated
      for multiple).

## 8. Celery beat schedule

The `beat` container fires three periodic tasks. Defaults are sane;
override via env if your traffic shape differs:

- `crawl-bajaj-daily` — 02:00 IST. Full in-house crawl.
- `walk-competitors-daily` — 03:00 IST. 8-domain roster walk, depth=2,
  max_pages=200. Triggers ChangeWatcher inside the pipeline.
- `gc-competitor-history-weekly` — Sun 04:30 IST. 90-day retention.

Roster lives in `COMPETITOR["roster"]` (env `COMPETITOR_ROSTER`,
comma-separated apex hosts). The Indian life-insurance peer set is
the default.

## 9. Deferred work (acknowledged, not blocking first deploy)

These are known gaps tracked separately from this checklist. None of
them prevent the current Groq-backed stack from going live, but each
should be picked up as a follow-up before the next major release.

- **LLM provider rewrite — OpenAI + Anthropic.** `apps.seo_ai.llm.provider.get_provider()`
  currently dispatches only `groq` / `stub`. Concrete `OpenAIProvider`
  and `AnthropicProvider` classes (plus matching config sections in
  `settings/base.py::LLM`) are pending. `OPENAI_API_KEY` /
  `ANTHROPIC_API_KEY` are already consumed by the AI-visibility probe
  subsystem; reusing them for the core LLM stack is a one-file change.
- **Apify Meta Ads — broader integration.** The
  `apps.seo_ai.adapters.apify_meta_ads` adapter is wired and the API
  key is provisioned (`APIFY_API_TOKEN`). Expansion to additional
  Apify actors (e.g. organic SERP scrapers, brand-mention crawlers)
  will land later — Apify is *not* an LLM provider, so it lives outside
  the provider factory.
- **Tier 2 TF-IDF content classifier** is documented in
  `apps/crawler/content/pipeline.py` but unimplemented. Tier 1 → Tier 3
  (MiniLM embeddings) covers the fallback path today.

## 10. Cutover smoke tests

After the first deploy, manually verify:

- [ ] `GET /api/v1/health/` → `200`, all checks green.
- [ ] `POST /api/v1/seo/content-writer/generate/` against a real URL
      → returns a proposal with `accepted >= 1`.
- [ ] `GET /api/v1/seo/llm/pool-stats/` → all keys present, no key
      stuck cooling > 60s.
- [ ] `docker compose logs beat --tail 20` → shows the next scheduled
      tick.
- [ ] `docker compose logs worker --tail 50` → no `KeyError` or
      `ImportError`; a sample task ran end-to-end.
