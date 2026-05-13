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


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    })
    s.verify = False
    pool = max(settings.max_workers, 10) + 4
    adapter = HTTPAdapter(pool_connections=pool, pool_maxsize=pool, max_retries=0)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    requests.packages.urllib3.disable_warnings(  # type: ignore[attr-defined]
        requests.packages.urllib3.exceptions.InsecureRequestWarning  # type: ignore[attr-defined]
    )
    return s


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
    """One HTTP attempt. Returns (result, links, is_retryable, retry_after_seconds)."""
    result = _empty_result(url)
    start = time.time()
    try:
        resp = session.get(url, timeout=settings.request_timeout, allow_redirects=True)
        result["response_time_ms"] = int((time.time() - start) * 1000)
        result["status_code"] = resp.status_code
        result["content_type"] = resp.headers.get("Content-Type", "")
        result["final_url"] = str(resp.url)

        if resp.status_code == 200:
            result["status"] = "OK"
            ctype = result["content_type"].lower()
            if "html" not in ctype and "xml" not in ctype:
                return result, [], False, None
            parsed = parse_page(resp.text, str(resp.url))
            result["title"] = parsed["title"]
            result["word_count"] = parsed["word_count"]
            result["console_errors"] = parsed["console_errors"]
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
