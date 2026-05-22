"""HTTP fetcher — one URL -> (result row, discovered links).

Fetches are retried with exponential backoff on transient failures
(timeouts, connection resets, chunked-encoding errors, HTTP 429/5xx) so
that a momentary blip never permanently drops a page *and* the entire
link subtree reachable only through it.
"""
from __future__ import annotations

import random
import time
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter

from ..conf import settings
from ..logger import get_logger
from .parser import parse_page

log = get_logger(__name__)

# HTTP status codes worth retrying (server-side / rate-limit, not client errors).
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
# Exception types that represent transient network conditions.
_RETRYABLE_EXC = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)


def _resolve_ssl_verify(raw: str) -> bool | str:
    """Same shape as the SEMRUSH / COMPETITOR ssl_verify resolvers:
    "" / unset / "true"  → True  (default certifi+truststore)
    "false"              → False (disable — corp MITM only)
    "/path/to/ca.pem"    → custom CA bundle path
    """
    import os.path

    value = (raw or "").strip()
    if not value or value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False
    if os.path.exists(value):
        return value
    log.warning(
        "CRAWLER_SSL_VERIFY=%r does not exist on disk — falling back to "
        "default (certifi) verification.",
        value,
    )
    return True


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    })
    s.verify = _resolve_ssl_verify(getattr(settings, "ssl_verify", "true"))
    pool = max(settings.max_workers, 10) + 4
    adapter = HTTPAdapter(pool_connections=pool, pool_maxsize=pool, max_retries=0)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    if s.verify is False:
        requests.packages.urllib3.disable_warnings(  # type: ignore[attr-defined]
            requests.packages.urllib3.exceptions.InsecureRequestWarning  # type: ignore[attr-defined]
        )
    # Phase D.4 — optional forms-based auth. No-op when env not set.
    try:
        from .auth_helpers import apply_forms_auth
        apply_forms_auth(s)
    except Exception as exc:  # noqa: BLE001 — auth failure must not break crawl
        log.warning("forms auth bootstrap raised: %s", exc)
    return s


# Custom extractors are loaded once per crawl process and reused for
# every page. The cache is intentionally module-level — a new Python
# process (the next crawl run) gets a fresh load. Within a single run,
# mid-crawl edits to CustomExtractor rows are NOT picked up, so the
# crawl's extractor set is stable for the whole run.
_CUSTOM_EXTRACTOR_CACHE: list[dict] | None = None


def _load_custom_extractors_cached() -> list[dict]:
    global _CUSTOM_EXTRACTOR_CACHE
    if _CUSTOM_EXTRACTOR_CACHE is not None:
        return _CUSTOM_EXTRACTOR_CACHE
    try:
        from ..models import CustomExtractor
        _CUSTOM_EXTRACTOR_CACHE = [
            e.as_dict() for e in CustomExtractor.objects.filter(is_active=True)
        ]
    except Exception as exc:  # noqa: BLE001 — Django not booted in tests
        log.info("custom extractor load skipped: %s", exc)
        _CUSTOM_EXTRACTOR_CACHE = []
    return _CUSTOM_EXTRACTOR_CACHE


def _empty_result(url: str) -> dict:
    return {
        "url": url, "final_url": url, "status_code": 0, "status": "pending",
        "title": "", "word_count": 0, "response_time_ms": 0,
        "content_type": "", "error_type": "", "error_message": "",
        "console_errors": [], "timestamp": datetime.now().isoformat(),
    }


def _backoff_sleep(attempt: int, retry_after: float | None) -> None:
    """Sleep before the next retry. Honours Retry-After when the server sends it."""
    if retry_after is not None and retry_after > 0:
        delay = min(retry_after, settings.retry_backoff_cap)
    else:
        delay = min(
            settings.retry_backoff_cap,
            settings.retry_backoff_base * (2 ** attempt),
        )
    delay += random.uniform(0, delay * 0.25)  # jitter to avoid thundering herd
    time.sleep(delay)


def _parse_retry_after(resp: requests.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            when = parsedate_to_datetime(raw)
            return max(0.0, (when - datetime.now(when.tzinfo)).total_seconds())
        except Exception:  # noqa: BLE001
            return None


def fetch(url: str, session: requests.Session) -> tuple[dict, list[str]]:
    """Fetch one page (with retries). Returns (result_row, discovered_links)."""
    last: tuple[dict, list[str]] | None = None
    for attempt in range(settings.max_retries + 1):
        result, links, retryable, retry_after = _fetch_once(url, session)
        last = (result, links)
        if not retryable or attempt >= settings.max_retries:
            return result, links
        log.info(
            "retry %d/%d for %s (%s)",
            attempt + 1, settings.max_retries, url,
            result.get("error_type") or result.get("status_code"),
        )
        _backoff_sleep(attempt, retry_after)
    return last if last else (_empty_result(url), [])


def _fetch_once(
    url: str, session: requests.Session,
) -> tuple[dict, list[str], bool, float | None]:
    """One HTTP attempt. Returns (result, links, is_retryable, retry_after_seconds).

    We use ``stream=True`` so we can inspect the response headers (status,
    content-type) and only read the body for HTML/XML responses. PDFs and
    other binary docs are recorded with a 0 word_count + the actual
    Content-Type, but no megabyte-sized body download.
    """
    result = _empty_result(url)
    start = time.time()
    resp = None
    try:
        resp = session.get(url, timeout=settings.request_timeout,
                           allow_redirects=True, stream=True)
        result["response_time_ms"] = int((time.time() - start) * 1000)
        result["status_code"] = resp.status_code
        result["content_type"] = resp.headers.get("Content-Type", "")
        result["final_url"] = str(resp.url)

        if resp.status_code == 200:
            result["status"] = "OK"
            ctype = result["content_type"].lower()
            if "html" not in ctype and "xml" not in ctype:
                # PDF / image / other binary — we have the metadata we need
                # from the headers; close without reading the body to avoid
                # downloading multi-MB files. PDFs get a metadata extract
                # because the SF-parity detectors want title / page count /
                # encrypted / text-layer signals.
                if "pdf" in ctype:
                    try:
                        from ..audits import sf_parity_phase_c as _pc
                        # Cap PDF body read at 25 MB — anything larger is
                        # almost certainly not optimised for indexing.
                        pdf_bytes = b""
                        for chunk in resp.iter_content(chunk_size=64 * 1024):
                            pdf_bytes += chunk
                            if len(pdf_bytes) > 25_000_000:
                                break
                        result.update(_pc.pdf_metadata_from(pdf_bytes))
                    except Exception as exc:  # noqa: BLE001
                        log.info("pdf metadata failed on %s: %s", url, exc)
                resp.close()
                return result, [], False, None
            # HTML/XML body read. settings.max_body_bytes == 0 means
            # "no cap" — never skip a page. Positive values act as a
            # defensive guard if you ever crawl untrusted domains.
            max_bytes = int(getattr(settings, "max_body_bytes", 0))
            if max_bytes > 0:
                content_length = resp.headers.get("Content-Length")
                if (
                    content_length
                    and content_length.isdigit()
                    and int(content_length) > max_bytes
                ):
                    result["status"] = "OK (body too large — skipped)"
                    result["error_type"] = "BodyTooLarge"
                    result["error_message"] = (
                        f"Content-Length={content_length} exceeds {max_bytes}"
                    )
                    resp.close()
                    return result, [], False, None
            try:
                chunks: list[bytes] = []
                received = 0
                for chunk in resp.iter_content(chunk_size=64 * 1024, decode_unicode=False):
                    if not chunk:
                        continue
                    received += len(chunk)
                    if max_bytes > 0 and received > max_bytes:
                        result["status"] = "OK (body too large — truncated)"
                        result["error_type"] = "BodyTooLarge"
                        result["error_message"] = (
                            f"Streamed body exceeded {max_bytes} bytes"
                        )
                        resp.close()
                        return result, [], False, None
                    chunks.append(chunk)
                body_bytes = b"".join(chunks)
            finally:
                resp.close()
            # Decode using the encoding requests detected from headers/BOM,
            # falling back to utf-8 with replacement so we never crash on
            # bad bytes.
            encoding = resp.encoding or resp.apparent_encoding or "utf-8"
            try:
                body_text = body_bytes.decode(encoding, errors="replace")
            except (LookupError, TypeError):
                body_text = body_bytes.decode("utf-8", errors="replace")
            parsed = parse_page(body_text, str(resp.url))
            result["title"] = parsed["title"]
            result["word_count"] = parsed["word_count"]
            result["console_errors"] = parsed["console_errors"]

            # ── Phase A — SF parity signals ──────────────────────
            # All free signals derived from the response we already
            # have. No additional HTTP round-trips except image-size
            # checks which defer to a separate worker pool.
            try:
                from ..audits import sf_parity_helpers as _pa
                result.update(_pa.security_headers_from(resp.headers))
                result.update(_pa.redirect_chain_from_requests(resp))
                # Meta-description extraction lives in parser; pull
                # it from the parsed dict when available.
                meta_desc = parsed.get("meta_description", "") or ""
                result.update(_pa.pixel_widths_from(
                    parsed["title"], meta_desc,
                ))
                result["meta_description"] = meta_desc
                result.update(_pa.canonical_signals_from(
                    body_text, resp.headers, str(resp.url),
                ))
                mixed, insecure = _pa.mixed_content_flags(body_text, str(resp.url))
                result["has_mixed_content"] = mixed
                result["has_insecure_form"] = insecure
                img_audit = _pa.image_audit_from(body_text, str(resp.url))
                # Flatten aggregate counts onto the row; per-image
                # detail stays in image_audit_extra (JSONB).
                result["image_count"] = img_audit["image_count"]
                result["image_missing_alt"] = img_audit["image_missing_alt"]
                result["image_empty_alt"] = img_audit["image_empty_alt"]
                result["image_oversized_count"] = img_audit["image_oversized_count"]
                result["image_broken_count"] = img_audit["image_broken_count"]
                result["image_audit_extra"] = img_audit["image_audit_extra"]
            except Exception as exc:  # noqa: BLE001 — never break the crawl
                log.info("phase-a helpers failed on %s: %s", url, exc)

            # ── Phase B — hreflang + schema.org ──────────────────
            try:
                from ..audits import sf_parity_phase_b as _pb
                result.update(_pb.hreflang_signals_from(
                    body_text, resp.headers, str(resp.url),
                ))
                result.update(_pb.jsonld_signals_from(body_text))
            except Exception as exc:  # noqa: BLE001
                log.info("phase-b helpers failed on %s: %s", url, exc)

            # ── Phase C — readability + custom extractors ────────
            # JS render-delta only meaningful on Scrapy-pipeline rows
            # (the Playwright gate doesn't apply to the legacy fetcher);
            # we still stamp js_rendered=False so detectors short-circuit
            # cleanly.
            try:
                from ..audits import sf_parity_phase_c as _pc
                # Strip tags to get visible text for Flesch + spell-check.
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(body_text, "html.parser")
                for el in soup(["script", "style", "noscript", "template"]):
                    el.decompose()
                visible = soup.get_text(separator=" ", strip=True)
                # Spell-check off by default in CI — env-controlled.
                import os as _os
                spell_on = _os.environ.get(
                    "CRAWLER_SPELLCHECK", "true",
                ).lower() in ("1", "true", "yes", "on")
                result.update(_pc.readability_signals_from(
                    visible, spell_check=spell_on,
                ))
                # Phase E — LanguageTool grammar. When the LT service
                # is configured + reachable it adds grammar_* fields;
                # otherwise it returns zeros and the legacy
                # pyspellchecker output stays as the only language signal.
                try:
                    from ..audits.language_tool import grammar_check
                    result.update(grammar_check(visible))
                except Exception as gtexc:  # noqa: BLE001
                    log.info("LT grammar check failed on %s: %s", url, gtexc)
                # Custom extractors — loaded once per crawl by the
                # engine startup hook. Read from a module-level cache
                # if present; otherwise skip.
                extractors = _load_custom_extractors_cached()
                if extractors:
                    result["custom_extracted"] = _pc.custom_extractors_run(
                        body_text, extractors,
                    )
                # Legacy fetcher never goes through Playwright — stamp
                # zeros so Postgres dual-write doesn't see NULLs.
                result.update(_pc.render_delta_from(None, None))
            except Exception as exc:  # noqa: BLE001
                log.info("phase-c helpers failed on %s: %s", url, exc)

            # ── Phase D — cookies + AMP + accessibility ──────────
            try:
                from ..audits import sf_parity_phase_d as _pd
                result.update(_pd.cookie_signals_from(
                    resp.headers, str(resp.url), body_text,
                ))
                result.update(_pd.amp_signals_from(body_text, str(resp.url)))
                result.update(_pd.accessibility_signals_from(body_text))
            except Exception as exc:  # noqa: BLE001
                log.info("phase-d helpers failed on %s: %s", url, exc)

            return result, parsed["links"], False, None

        if resp.status_code == 404:
            result["status"] = "404 Not Found"
            result["error_type"] = "HTTPError"
            result["error_message"] = f"HTTP {resp.status_code}"
            return result, [], False, None

        # other HTTP status
        result["status"] = f"HTTP {resp.status_code}"
        result["error_type"] = "HTTPError"
        result["error_message"] = f"HTTP {resp.status_code}"
        retryable = resp.status_code in _RETRYABLE_STATUS
        return result, [], retryable, _parse_retry_after(resp) if retryable else None

    except requests.exceptions.Timeout as exc:
        _mark_error(result, start, "Timeout", "Timeout", exc)
        return result, [], True, None
    except requests.exceptions.ChunkedEncodingError as exc:
        _mark_error(result, start, "Chunked Encoding Error", "ChunkedEncodingError", exc)
        return result, [], True, None
    except requests.exceptions.SSLError as exc:
        _mark_error(result, start, "SSL Error", "SSLError", exc)
        return result, [], False, None
    except requests.exceptions.ConnectionError as exc:
        _mark_error(result, start, "Connection Error", "ConnectionError", exc)
        return result, [], True, None
    except requests.exceptions.TooManyRedirects as exc:
        _mark_error(result, start, "Too Many Redirects", "TooManyRedirects", exc)
        return result, [], False, None
    except requests.RequestException as exc:
        _mark_error(result, start, "Error", type(exc).__name__, exc)
        return result, [], False, None


def _mark_error(result: dict, start: float, status: str, etype: str, exc: Exception) -> None:
    result["status"] = status
    result["error_type"] = etype
    result["error_message"] = str(exc)[:200]
    result["response_time_ms"] = int((time.time() - start) * 1000)
