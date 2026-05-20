"""Concurrent PSI scheduler for inline use during a crawl.

Sits alongside the crawler: each crawled URL is submitted to a
background worker pool that calls PageSpeed Insights and streams the
four key fields (pagespeed_score, lcp_ms, cls, inp_ms) into a sidecar
``crawl_psi_inline.csv`` as they complete. After the crawl finishes
(or is stopped), the accumulated results are atomically merged into
``crawl_results.csv`` via the existing helper.

Why separate from the per-URL fetcher:
- PSI calls are 1-30 s each; running them in the fetcher's worker
  thread would multiply crawl time by ~5-10x.
- The crawler keeps an append handle on crawl_results.csv during the
  run — an atomic rewrite at that moment would orphan rows. The
  sidecar log lets us record progressive results safely; only one
  rewrite happens, at the end.
- A small thread pool (default 4) lets PSI run in parallel without
  hammering Google's per-IP rate limit.

Lifecycle::

    sched = InlinePSIScheduler()
    if sched.start():           # False when PSI disabled (no SA file etc.)
        for url in crawled_urls:
            sched.submit(url)
        sched.stop(drain=True)
        sched.merge_into_results_csv()

Disabled silently when ``cwv_psi.AdapterDisabledError`` fires. In that
mode every public method is a no-op so callers don't need conditional
branches.
"""
from __future__ import annotations

import csv
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..conf import settings as crawler_settings
from ..logger import get_logger

log = get_logger(__name__)

_SIDECAR_FIELDS = [
    "url", "pagespeed_score", "lcp_ms", "cls", "inp_ms",
    "primary_strategy", "fetched_at",
]
_SIDECAR_FILE = "crawl_psi_inline.csv"


@dataclass
class _SchedulerState:
    started_at: float | None = None
    finished_at: float | None = None
    submitted: int = 0
    in_flight: int = 0
    completed: int = 0
    failed: int = 0
    last_url: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            running = self.started_at is not None and self.finished_at is None
            return {
                "is_running": running,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "submitted": self.submitted,
                "in_flight": self.in_flight,
                "completed": self.completed,
                "failed": self.failed,
                "last_url": self.last_url,
            }


class InlinePSIScheduler:
    """Concurrent PSI worker pool + streaming sidecar CSV."""

    _SENTINEL: Any = object()

    def __init__(
        self,
        *,
        workers: int | None = None,
        strategies: tuple[str, ...] | None = None,
    ) -> None:
        from django.conf import settings as dj_settings

        cfg = getattr(dj_settings, "PSI", {}) or {}
        if workers is None:
            workers = getattr(crawler_settings, "psi_inline_workers", 4)
        self.workers = max(1, int(workers))
        if strategies is None:
            raw = cfg.get("strategies") or ("mobile", "desktop")
            strategies = tuple(raw)
        self.strategies = strategies
        self._primary = "mobile" if "mobile" in strategies else strategies[0]
        self._queue: queue.Queue = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._stop_evt = threading.Event()
        self.state = _SchedulerState()
        self._psi: Any = None
        self._adapter_error: str | None = None
        self._results: dict[str, dict] = {}
        self._results_lock = threading.Lock()
        self._sidecar_path = crawler_settings.data_path / _SIDECAR_FILE
        self._sidecar_lock = threading.Lock()
        self._seen: set[str] = set()
        self._seen_lock = threading.Lock()

    # ── public lifecycle ───────────────────────────────────────────

    def start(self) -> bool:
        """Initialise PSI adapter, truncate sidecar, spawn workers.
        Returns ``True`` if the scheduler is live (PSI usable);
        ``False`` if PSI is disabled — caller should treat the
        scheduler as a no-op in that case.
        """
        if self._threads:
            return not self.is_disabled
        try:
            from apps.seo_ai.adapters.cwv_psi import (
                AdapterDisabledError, PSIAdapter,
            )
            try:
                self._psi = PSIAdapter()
            except AdapterDisabledError as exc:
                self._adapter_error = str(exc)
                log.info("psi_scheduler: disabled (%s)", exc)
                self._psi = None
        except ImportError as exc:
            self._adapter_error = f"cwv_psi import: {exc}"
            log.warning("psi_scheduler: import failed: %s", exc)
            self._psi = None
        if self._psi is None:
            return False
        try:
            with self._sidecar_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=_SIDECAR_FIELDS)
                writer.writeheader()
        except OSError as exc:
            log.warning(
                "psi_scheduler: cannot init sidecar %s: %s",
                self._sidecar_path, exc,
            )
            self._psi = None
            self._adapter_error = f"sidecar init failed: {exc}"
            return False
        with self.state.lock:
            self.state.started_at = time.time()
            self.state.finished_at = None
        for i in range(self.workers):
            t = threading.Thread(
                target=self._worker, name=f"psi-sched-{i}", daemon=True,
            )
            t.start()
            self._threads.append(t)
        log.info(
            "psi_scheduler: started %d worker(s) strategies=%s",
            self.workers, list(self.strategies),
        )
        return True

    def submit(self, url: str) -> None:
        """Enqueue a URL. No-op when scheduler is disabled or url is
        already pending. Cheap to call after every row write."""
        if self._psi is None or not url:
            return
        with self._seen_lock:
            if url in self._seen:
                return
            self._seen.add(url)
        self._queue.put(url)
        with self.state.lock:
            self.state.submitted += 1

    def stop(self, drain: bool = True, timeout: float = 120.0) -> None:
        """Stop workers. ``drain=True`` waits for the queue to empty
        before signalling shutdown; ``False`` aborts immediately and
        discards pending URLs."""
        if not self._threads:
            return
        if drain:
            try:
                self._queue.join()
            except Exception:  # noqa: BLE001
                pass
        self._stop_evt.set()
        for _ in self._threads:
            self._queue.put(self._SENTINEL)
        for t in self._threads:
            t.join(timeout=timeout)
        self._threads.clear()
        with self.state.lock:
            self.state.finished_at = time.time()

    def merge_into_results_csv(self) -> int:
        """Atomically merge accumulated PSI rows into crawl_results.csv.
        Safe only AFTER the crawler has closed its append handle (which
        the engine does in its ``finally`` block). Returns the number
        of rows that were merged."""
        results = self.results()
        if not results:
            return 0
        from .psi_capture import _merge_into_results_csv
        try:
            return _merge_into_results_csv(results)
        except Exception as exc:  # noqa: BLE001
            log.warning("psi_scheduler: final merge failed: %s", exc)
            return 0

    # ── snapshot / accessors ───────────────────────────────────────

    @property
    def is_disabled(self) -> bool:
        return self._psi is None

    @property
    def disabled_reason(self) -> str | None:
        return self._adapter_error

    def results(self) -> dict[str, dict]:
        with self._results_lock:
            return dict(self._results)

    def progress(self) -> dict[str, Any]:
        snap = self.state.snapshot()
        snap["workers"] = self.workers
        snap["strategies"] = list(self.strategies)
        snap["primary_strategy"] = self._primary
        snap["queue_size"] = self._queue.qsize()
        snap["disabled"] = self.is_disabled
        if self._adapter_error:
            snap["disabled_reason"] = self._adapter_error
        return snap

    # ── worker internals ───────────────────────────────────────────

    def _worker(self) -> None:
        while not self._stop_evt.is_set():
            try:
                url = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if url is self._SENTINEL:
                self._queue.task_done()
                break
            with self.state.lock:
                self.state.in_flight += 1
                self.state.last_url = url
            try:
                self._process(url)
            except Exception as exc:  # noqa: BLE001
                log.warning("psi_scheduler: %s crashed: %s", url, exc)
                with self.state.lock:
                    self.state.failed += 1
            finally:
                with self.state.lock:
                    self.state.in_flight = max(0, self.state.in_flight - 1)
                self._queue.task_done()

    def _process(self, url: str) -> None:
        from .psi_capture import _row_from_record

        primary_row: dict | None = None
        had_error = False
        for strategy in self.strategies:
            if self._stop_evt.is_set():
                return
            try:
                record = self._psi.fetch(url, strategy=strategy)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "psi_scheduler: %s/%s fetch error: %s",
                    strategy, url, exc,
                )
                had_error = True
                continue
            if record is None or getattr(record, "error", None):
                had_error = had_error or bool(record and record.error)
                continue
            if strategy == self._primary:
                primary_row = _row_from_record(record)
        if primary_row is None:
            primary_row = {
                "pagespeed_score": "", "lcp_ms": "", "cls": "", "inp_ms": "",
            }
            if had_error:
                with self.state.lock:
                    self.state.failed += 1
        with self._results_lock:
            self._results[url] = primary_row
        self._append_sidecar(url, primary_row)
        with self.state.lock:
            self.state.completed += 1

    def _append_sidecar(self, url: str, row: dict) -> None:
        out_row = {
            "url": url,
            "pagespeed_score": row.get("pagespeed_score", ""),
            "lcp_ms": row.get("lcp_ms", ""),
            "cls": row.get("cls", ""),
            "inp_ms": row.get("inp_ms", ""),
            "primary_strategy": self._primary,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._sidecar_lock:
            try:
                with self._sidecar_path.open(
                    "a", encoding="utf-8", newline="",
                ) as f:
                    writer = csv.DictWriter(
                        f, fieldnames=_SIDECAR_FIELDS, extrasaction="ignore",
                    )
                    writer.writerow(out_row)
                    f.flush()
            except OSError as exc:
                log.warning(
                    "psi_scheduler: sidecar append failed for %s: %s",
                    url, exc,
                )


# ── module-level handle so the API view can poll the current run ────
# The engine sets this at the start of each crawl and clears it at the
# end. Concurrent crawls aren't supported by this app, so a single
# slot is fine.

_current: InlinePSIScheduler | None = None
_current_lock = threading.Lock()


def get_current() -> InlinePSIScheduler | None:
    with _current_lock:
        return _current


def set_current(sched: InlinePSIScheduler | None) -> None:
    global _current
    with _current_lock:
        _current = sched
