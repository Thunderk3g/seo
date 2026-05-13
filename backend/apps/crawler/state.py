"""Shared crawler state — process-wide singleton.

Verbatim port of ``crawler-engine/app/core/state.py``. The single
``STATE`` instance owns the visited set, BFS queue, accumulated results,
and live counters. Access is thread-safe via the bundled lock.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field


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


@dataclass
class CrawlState:
    visited: set[str] = field(default_factory=set)
    queued: set[str] = field(default_factory=set)
    queue: deque = field(default_factory=deque)

    results: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    error_404: list[dict] = field(default_factory=list)
    error_http: list[dict] = field(default_factory=list)
    error_connection: list[dict] = field(default_factory=list)
    error_chunked: list[dict] = field(default_factory=list)
    console_logs: list[dict] = field(default_factory=list)
    discovered_edges: list[dict] = field(default_factory=list)

    stats: CrawlStats = field(default_factory=CrawlStats)
    lock: threading.Lock = field(default_factory=threading.Lock)

    should_stop: bool = False
    is_running: bool = False

    def reset(self) -> None:
        with self.lock:
            self.visited.clear()
            self.queued.clear()
            self.queue.clear()
            self.results.clear()
            self.errors.clear()
            self.error_404.clear()
            self.error_http.clear()
            self.error_connection.clear()
            self.error_chunked.clear()
            self.console_logs.clear()
            self.discovered_edges.clear()
            self.stats = CrawlStats()
            self.should_stop = False


STATE = CrawlState()
