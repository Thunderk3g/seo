"""Real browser-side console capture using Playwright.

The static crawler in ``engine.py`` fetches HTML with the ``requests``
library — it never executes JavaScript, so any console errors thrown by
the live site are invisible to it. The previous heuristic in
``parser.detect_console_errors`` tried to regex-match "Uncaught ..."
strings in HTML, which was noisy and missed all the actual JS bugs that
only manifest at runtime.

This module does the right thing: launches headless Chromium, navigates
to each URL, waits for the page to settle, captures:

    * console messages (level + text + source location)
    * page errors (uncaught exceptions)
    * failed network requests (broken images, dead asset URLs, etc.)

Results are written to the existing ``crawl_console_log.csv`` stream so
the UI's "Console log" report card surfaces them without any other
plumbing changes.

Run via:

    python manage.py capture_console [--limit N] [--subdomain X]

or via the POST endpoint that wraps this module in a background thread.
"""
from __future__ import annotations

import csv
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from ..conf import settings
from ..logger import get_logger
from ..storage import csv_writer

log = get_logger(__name__)


# ── Status singleton (separate from the main crawl STATE) ──────────────────
@dataclass
class BrowserCaptureState:
    is_running: bool = False
    should_stop: bool = False
    total: int = 0
    processed: int = 0
    failed: int = 0
    console_rows_written: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    last_url: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def as_dict(self) -> dict:
        with self.lock:
            return {
                "is_running": self.is_running,
                "should_stop": self.should_stop,
                "total": self.total,
                "processed": self.processed,
                "failed": self.failed,
                "console_rows_written": self.console_rows_written,
                "last_url": self.last_url,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }

    def reset(self) -> None:
        with self.lock:
            self.is_running = False
            self.should_stop = False
            self.total = 0
            self.processed = 0
            self.failed = 0
            self.console_rows_written = 0
            self.started_at = None
            self.finished_at = None
            self.last_url = ""


CAPTURE_STATE = BrowserCaptureState()


# ── URL selection ──────────────────────────────────────────────────────────
def select_target_urls(
    *,
    limit: int = 200,
    subdomain: str = "www",
    only_status: str = "200",
) -> list[str]:
    """Read crawl_results.csv and pick which URLs to inspect.

    Defaults: top ``limit`` www URLs that returned HTTP 200. Reading from
    the existing crawler output means we never inspect a URL the regular
    crawler considered ineligible (skip-extension, robots-disallowed, etc.).
    """
    path = settings.data_path / "crawl_results.csv"
    if not path.exists():
        return []
    out: list[str] = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if subdomain and row.get("subdomain") != subdomain:
                    continue
                if only_status and (row.get("status_code") or "") != only_status:
                    continue
                url = (row.get("url") or "").strip()
                if not url:
                    continue
                # PDFs / images / other non-HTML have no JS console — skip.
                ctype = (row.get("content_type") or "").lower()
                if ctype and "html" not in ctype and "xml" not in ctype:
                    continue
                out.append(url)
                if limit and len(out) >= limit:
                    break
    except OSError as exc:
        log.warning("browser_console: cannot read %s: %s", path, exc)
    return out


# ── Capture loop ───────────────────────────────────────────────────────────
def capture(
    urls: Iterable[str],
    *,
    wait_after_load_ms: int = 1500,
    nav_timeout_ms: int = 25_000,
    levels: tuple[str, ...] = ("error", "warning"),
) -> dict:
    """Run Playwright sequentially over ``urls``. Returns a summary dict.

    ``levels`` controls which console message types surface in the CSV.
    Defaults to error+warning — keeps the CSV focused on actionable bugs
    instead of routine ``console.log`` noise. Pass ``("error", "warning",
    "info", "log", "debug")`` to capture everything.

    Page errors (uncaught exceptions) and failed network requests are
    ALWAYS captured — they're the highest-signal events.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"ok": False, "error": "playwright not installed"}

    url_list = list(urls)
    CAPTURE_STATE.reset()
    with CAPTURE_STATE.lock:
        CAPTURE_STATE.is_running = True
        CAPTURE_STATE.total = len(url_list)
        CAPTURE_STATE.started_at = time.time()

    rows_written = 0
    failed = 0

    # csv_writer.append() is a no-op if streams aren't open. Open them in
    # append mode so this command works standalone (no concurrent crawl).
    # If a crawl IS running, the streams will already be open and we'll
    # share them — also fine, the file lock makes appends atomic.
    streams_opened_here = False
    try:
        if not csv_writer._handles:        # noqa: SLF001 (intentional)
            csv_writer.open_streams(resume=True)
            streams_opened_here = True
    except Exception as exc:  # noqa: BLE001
        log.warning("browser_console: could not open csv streams: %s", exc)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
                                "(+ BajajLife console-audit)"),
                    ignore_https_errors=True,
                )
                for i, url in enumerate(url_list):
                    if CAPTURE_STATE.should_stop:
                        log.info("browser_console: stop requested at %s/%s",
                                 i, len(url_list))
                        break
                    try:
                        n = _capture_one(context, url,
                                         wait_after_load_ms=wait_after_load_ms,
                                         nav_timeout_ms=nav_timeout_ms,
                                         levels=levels)
                        rows_written += n
                    except Exception as exc:  # noqa: BLE001
                        log.warning("browser_console: %s failed: %s", url, exc)
                        failed += 1
                        _append_row(url, "error", "playwright",
                                    f"capture exception: {type(exc).__name__}: {exc}",
                                    source="capture_loop")
                        rows_written += 1
                    with CAPTURE_STATE.lock:
                        CAPTURE_STATE.processed = i + 1
                        CAPTURE_STATE.failed = failed
                        CAPTURE_STATE.console_rows_written = rows_written
                        CAPTURE_STATE.last_url = url
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        log.exception("browser_console: top-level crash")
        return {"ok": False, "error": str(exc)}
    finally:
        with CAPTURE_STATE.lock:
            CAPTURE_STATE.is_running = False
            CAPTURE_STATE.finished_at = time.time()
        # Flush+close streams only if WE opened them. If a regular crawl
        # is in progress, leave the streams alone for that crawl to manage.
        if streams_opened_here:
            try:
                csv_writer.flush_streams()
                csv_writer.close_streams()
            except Exception:  # noqa: BLE001
                pass

    return {
        "ok": True,
        "urls_inspected": min(len(url_list), CAPTURE_STATE.processed),
        "failed": failed,
        "rows_written": rows_written,
    }


def _capture_one(context, url, *, wait_after_load_ms, nav_timeout_ms, levels):
    """Inspect a single URL. Returns number of CSV rows written for it."""
    page = context.new_page()
    captured: list[tuple[str, str, str, str]] = []  # (kind, level, text, source)

    page.on("console", lambda m: captured.append((
        "console", m.type, m.text[:500] if m.text else "",
        _msg_source(m),
    )))
    page.on("pageerror", lambda e: captured.append((
        "pageerror", "error", str(e)[:500], "",
    )))
    page.on("requestfailed", lambda req: captured.append((
        "requestfailed", "warning",
        f"{req.method} {req.url}: {req.failure or 'unknown'}"[:500],
        req.url,
    )))

    try:
        page.goto(url, timeout=nav_timeout_ms, wait_until="domcontentloaded")
        if wait_after_load_ms > 0:
            page.wait_for_timeout(wait_after_load_ms)
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass

    written = 0
    for kind, level, text, source in captured:
        if kind == "console" and level not in levels:
            continue
        _append_row(url, level, kind, text, source=source)
        written += 1
    return written


def _msg_source(msg) -> str:
    try:
        loc = msg.location
        if loc:
            url = (loc.get("url") or "").rsplit("/", 1)[-1]
            line = loc.get("lineNumber")
            col = loc.get("columnNumber")
            if url:
                return f"{url}:{line}:{col}" if line is not None else url
    except Exception:  # noqa: BLE001
        pass
    return ""


def _append_row(url: str, level: str, kind: str, text: str, source: str = "") -> None:
    """Append a single console event to crawl_console_log.csv.

    Existing CSV schema is ``timestamp, url, error, <enrichment fields>``.
    We pack ``level``, ``kind`` and optional source location into the
    ``error`` column so we don't have to migrate the CSV. csv_writer's
    DictWriter(extrasaction="ignore") tolerates unknown keys; the
    classifier-based enrichment fields are auto-stamped by csv_writer.
    """
    error_text = f"[{level}] {kind}: {text}"
    if source:
        error_text += f"  (at {source})"
    csv_writer.append("console_logs", {
        "timestamp": datetime.now().isoformat(),
        "url": url,
        "error": error_text,
    })


def request_stop() -> None:
    with CAPTURE_STATE.lock:
        CAPTURE_STATE.should_stop = True
