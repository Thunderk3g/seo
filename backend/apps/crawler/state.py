"""Shared crawler state — process-wide singleton.

Verbatim port of ``crawler-engine/app/core/state.py``. The single
``STATE`` instance owns the visited set, BFS queue, accumulated results,
and live counters. Access is thread-safe via the bundled lock.

Per-list memory growth is bounded via ``collections.deque(maxlen=N)``
on the activity lists (results, errors, console_logs, discovered_edges).
CSV is the authoritative store; the in-process lists feed only the
"recent activity" UI surface, so dropping the oldest entries past the
cap is fine. Bound is configurable via ``CRAWLER_RESULTS_BUFFER_CAP``.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field


# Hardcoded fallback used at module-import time (settings may not be
# loaded yet). reset() re-reads the operator-configured cap from
# crawler conf and rebuilds the deques accordingly.
_DEFAULT_BUFFER_CAP = 2000


@dataclass
class CrawlStats:
    discovered: int = 0
    crawled: int = 0
    ok: int = 0
    errors: int = 0
    errors_404: int = 0
    queue_size: int = 0
    active_workers: int = 0
    started_at: float | None = None
    finished_at: float | None = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _bounded_list() -> deque:
    """Factory: a deque with the module-level fallback cap. Re-built
    in reset() once crawler settings are loaded."""
    return deque(maxlen=_DEFAULT_BUFFER_CAP)


@dataclass
class CrawlState:
    visited: set[str] = field(default_factory=set)
    queued: set[str] = field(default_factory=set)
    queue: deque = field(default_factory=deque)

    # Bounded ring buffers. CSV is the source of truth; these only
    # serve the live-activity UI, so we keep at most N most-recent.
    results: deque = field(default_factory=_bounded_list)
    errors: deque = field(default_factory=_bounded_list)
    error_404: deque = field(default_factory=_bounded_list)
    error_http: deque = field(default_factory=_bounded_list)
    # error_connection / error_chunked retired — not surfaced anywhere.
    console_logs: deque = field(default_factory=_bounded_list)
    discovered_edges: deque = field(default_factory=_bounded_list)

    # URLs harvested from sitemap.xml during _seed(); read by csv_writer to
    # stamp ``from_sitemap`` on each row. Normalised via engine.url_utils.
    sitemap_urls: set[str] = field(default_factory=set)

    stats: CrawlStats = field(default_factory=CrawlStats)
    lock: threading.Lock = field(default_factory=threading.Lock)

    should_stop: bool = False
    is_running: bool = False

    def reset(self) -> None:
        # Re-read the buffer cap from settings on every reset so a
        # change to CRAWLER_RESULTS_BUFFER_CAP takes effect on the
        # next crawl without restarting the process. Falls back to
        # the module-level default if settings aren't reachable yet.
        try:
            from .conf import settings as crawler_settings
            cap = int(getattr(crawler_settings, "results_buffer_cap", _DEFAULT_BUFFER_CAP))
            cap = max(100, cap)
        except Exception:  # noqa: BLE001
            cap = _DEFAULT_BUFFER_CAP
        with self.lock:
            self.visited.clear()
            self.queued.clear()
            self.queue.clear()
            self.results = deque(maxlen=cap)
            self.errors = deque(maxlen=cap)
            self.error_404 = deque(maxlen=cap)
            self.error_http = deque(maxlen=cap)
            self.console_logs = deque(maxlen=cap)
            self.discovered_edges = deque(maxlen=cap)
            self.sitemap_urls.clear()
            self.stats = CrawlStats()
            self.should_stop = False


STATE = CrawlState()
