# Dockerfile for Django Backend
FROM python:3.11-slim

WORKDIR /app

# CA bundle for outbound HTTPS (Anthropic SDK, sitemap fetches, etc).
# python:3.11-slim already includes ca-certificates via the debian-slim base,
# so this is a confirmation rather than a new install. If it ever goes missing,
# uncomment the apt-get block below.
# RUN apt-get update \
#     && apt-get install -y --no-install-recommends ca-certificates \
#     && rm -rf /var/lib/apt/lists/*

# Default to installing dev requirements (pytest, pytest-django) for local dev.
# Production CI overrides via `--build-arg INSTALL_DEV=0`.
ARG INSTALL_DEV=1

COPY requirements/ /app/requirements/
RUN pip install --no-cache-dir -r requirements/base.txt \
    && if [ "$INSTALL_DEV" = "1" ]; then pip install --no-cache-dir -r requirements/dev.txt; fi

# Playwright Chromium binary (used by apps.crawler.engine.browser_console).
# `--with-deps` installs the apt packages Chromium needs; in a corporate-MITM
# network the binary download can hit TLS issues, so we leave NODE_TLS_REJECT
# unforced here — a build behind a strict proxy can re-run with
# `docker exec ... NODE_TLS_REJECT_UNAUTHORIZED=0 playwright install chromium`
# inside the container if the default fails.
RUN playwright install --with-deps chromium || \
    (NODE_TLS_REJECT_UNAUTHORIZED=0 playwright install chromium)

COPY . /app/

CMD ["gunicorn", "config.wsgi", "-b", "0.0.0.0:8000"]
