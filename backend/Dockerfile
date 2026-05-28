# Dockerfile for Django Backend
FROM python:3.11-slim

WORKDIR /app

# Corporate root CAs (Bajaj Life intranet + Cisco Umbrella SIG) intercept
# outbound TLS, so the build container has to trust them or pip / requests /
# certifi-backed libs all fail with CERTIFICATE_VERIFY_FAILED. Drop any PEMs in
# backend/certs/ named *.crt and they get folded into the system bundle here.
# PIP_CERT / REQUESTS_CA_BUNDLE / SSL_CERT_FILE point pip and runtime HTTP libs
# at the system bundle instead of certifi's own (which doesn't know corp CAs).
COPY certs/ /usr/local/share/ca-certificates/
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

# Default to installing dev requirements (pytest, pytest-django) for local dev.
# Production CI overrides via `--build-arg INSTALL_DEV=0`.
ARG INSTALL_DEV=1

COPY requirements/ /app/requirements/

# Pre-install CPU-only torch BEFORE base.txt. sentence-transformers pulls torch
# transitively, and the default PyPI torch wheel hard-depends on the CUDA 13
# runtime on Linux (~2.5 GB of nvidia-* wheels we never use — we do not
# GPU-accelerate). Installing CPU torch first means the sentence-transformers
# resolve finds torch already satisfied and skips the CUDA chain entirely.
#
# --retries/--timeout: the dep chain is heavy (torch alone is ~200 MB even on
# CPU); a transient PyPI hiccup mid-resolve should not kill a 10-minute build.
RUN pip install --no-cache-dir --retries 10 --timeout 120 \
        --index-url https://download.pytorch.org/whl/cpu \
        torch \
    && pip install --no-cache-dir --retries 10 --timeout 120 \
        -r requirements/base.txt \
    && if [ "$INSTALL_DEV" = "1" ]; then \
        pip install --no-cache-dir --retries 10 --timeout 120 \
            -r requirements/dev.txt; \
    fi

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
