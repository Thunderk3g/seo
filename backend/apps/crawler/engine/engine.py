"""BFS crawl engine — thread-pool worker loop.

Designed to crawl an entire site to completion:
  * retry-with-backoff (in the fetcher) so transient failures don't drop
    a page *and* the subtree only reachable through it;
  * streaming, append-only CSV output (no O(n^2) rewrites);
  * resumable — state is checkpointed to ``crawl_state.json`` and reloaded
    on the next run;
  * crawler-trap guards (absurd URLs / faceted-search explosions);
  * sitemap + sitemap-index harvesting on top of link discovery;
  * optional ``max_depth`` / ``max_pages`` ceilings (0 == unlimited).
"""
from __future__ import annotations

import json
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse

from .. import log_bus
from ..conf import settings
from ..logger import get_logger
from ..state import STATE, CrawlStats
from ..storage import csv_writer
from . import robots as robots_mod
from . import sitemap as sitemap_mod
from .fetcher import fetch, new_session
from .url_utils import has_skip_extension, is_allowed_domain, is_trap, normalize

log = get_logger(__name__)

# Common sitemap locations to probe in addition to whatever robots.txt declares.
_SITEMAP_GUESSES = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/sitemap.xml.gz")


def _eligible(url: str | None, rp) -> str | None:
    """Normalize + run every admission filter. Returns the URL if crawlable, else None."""
    if not url:
        return None
    if not is_allowed_domain(url) or has_skip_extension(url) or is_trap(url):
        return None
    if not robots_mod.can_fetch(rp, url):
        return None
    return url


def _enqueue(url: str, parent: str | None, depth: int) -> bool:
    """Add a URL to the frontier if unseen."""
    if url in STATE.queued or url in STATE.visited:
        return False
    STATE.queue.append((url, parent, depth))
    STATE.queued.add(url)
    return True


def _depth_ok(depth: int) -> bool:
    return settings.max_depth <= 0 or depth <= settings.max_depth


def _collect_sitemap_urls(session, robots_sitemaps: list[str]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    p = urlparse(settings.seed_url)
    origin = f"{p.scheme}://{p.netloc}"
    sources = list(robots_sitemaps) + [origin + g for g in _SITEMAP_GUESSES]
    for sm in sources:
        if sm in seen:
            continue
        seen.add(sm)
        urls.extend(sitemap_mod.harvest(sm, session))
    out, dedup = [], set()
    for u in urls:
        if u not in dedup:
            dedup.add(u)
            out.append(u)
    return out


def _seed(session, rp, robots_sitemaps) -> int:
    """Populate the frontier with the seed URL + everything in the sitemap(s)."""
    sitemap_urls = _collect_sitemap_urls(session, robots_sitemaps)
    log_bus.post({
        "type": "info",
        "message": f"Harvested {len(sitemap_urls)} URL(s) from sitemap(s)",
        "timestamp": datetime.now().isoformat(),
    })
    added = 0
    for raw in [settings.seed_url, *sitemap_urls]:
        url = _eligible(normalize(raw), rp)
        if url and _enqueue(url, None, 0):
            added += 1
    with STATE.lock:
        STATE.stats.discovered = max(STATE.stats.discovered, len(STATE.queued) + len(STATE.visited))
        STATE.stats.queue_size = len(STATE.queue)
    return added


def _visited_from_results_csv() -> set[str]:
    """Every URL already recorded in crawl_results.csv (for robust resume)."""
    path = settings.data_path / "crawl_results.csv"
    if not path.exists():
        return set()
    import csv as _csv
    out: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = _csv.reader(f)
            header = next(reader, None)
            if not header or "url" not in header:
                return set()
            idx = header.index("url")
            for row in reader:
                if len(row) > idx and row[idx]:
                    out.add(row[idx])
    except Exception:  # noqa: BLE001
        return set()
    return out


def _requeue_gaps_from_discovered_csv(rp) -> int:
    """After a resume, re-queue any discovered-but-not-yet-crawled URL that the
    saved frontier is missing (it can lag the discovered-edges CSV by up to one
    checkpoint window). Keeps the crawl from silently dropping a subtree."""
    path = settings.data_path / "crawl_discovered.csv"
    if not path.exists():
        return 0
    import csv as _csv
    added = 0
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = _csv.reader(f)
            header = next(reader, None)
            if not header:
                return 0
            iu = header.index("url") if "url" in header else 0
            ip = header.index("discovered_from") if "discovered_from" in header else 1
            idp = header.index("depth") if "depth" in header else 2
            for row in reader:
                if len(row) <= iu or not row[iu]:
                    continue
                child = row[iu].strip()
                parent = row[ip].strip() if len(row) > ip else None
                try:
                    depth = int(row[idp]) if len(row) > idp and row[idp] else 1
                except ValueError:
                    depth = 1
                if child in STATE.visited or child in STATE.queued:
                    continue
                if not _depth_ok(depth) or _eligible(child, rp) is None:
                    continue
                STATE.queue.append((child, parent, depth))
                STATE.queued.add(child)
                added += 1
    except Exception:  # noqa: BLE001
        return added
    return added


def _maybe_resume() -> bool:
    """If a saved crawl exists and resume is enabled, restore it. Returns True if resumed."""
    if not settings.resume:
        return False
    path = settings.data_path / "crawl_state.json"
    if not path.exists():
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        visited = data.get("visited") or []
        queue = data.get("queue") or []
        if not visited and not queue:
            return False
        STATE.visited = set(visited)
        STATE.visited |= _visited_from_results_csv()
        STATE.queued = set(data.get("queued") or [])
        STATE.queue = deque(
            (item[0], item[1] if len(item) > 1 else None, int(item[2]) if len(item) > 2 else 0)
            for item in queue if item
            and item[0] not in STATE.visited
        )
        st = data.get("stats") or {}
        fields = CrawlStats.__dataclass_fields__
        STATE.stats = CrawlStats(**{k: v for k, v in st.items() if k in fields})
        STATE.stats.started_at = time.time()
        STATE.stats.finished_at = None
        STATE.stats.queue_size = len(STATE.queue)
        STATE.stats.active_workers = 0
        log_bus.post({
            "type": "info",
            "message": (
                f"Resumed crawl — {len(STATE.visited)} pages already done, "
                f"{len(STATE.queue)} queued"
            ),
            "timestamp": datetime.now().isoformat(),
        })
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("resume failed (%s) — starting fresh", exc)
        return False


def _ingest(url: str, parent: str | None, depth: int,
            result: dict, links: list[str], rp) -> int:
    """Merge a fetch result into global state + stream it to disk. Returns links queued."""
    added = 0
    final_url = result.get("final_url") or url
    error_entry = None
    error_stream = None
    console_entries: list[dict] = []
    with STATE.lock:
        STATE.visited.add(url)
        STATE.visited.add(final_url)         # de-dup redirect targets
        STATE.queued.discard(url)
        STATE.queued.discard(final_url)
        STATE.results.append(result)
        STATE.stats.crawled += 1
        if result["status"] == "OK":
            STATE.stats.ok += 1
        if result["error_type"]:
            error_entry = {
                "timestamp": result["timestamp"], "url": url,
                "error_type": result["error_type"],
                "error_message": result["error_message"],
            }
            STATE.errors.append(error_entry)
            STATE.stats.errors += 1
            if result["status_code"] == 404:
                STATE.error_404.append(error_entry)
                STATE.stats.errors_404 += 1
                error_stream = "error_404"
            elif result["error_type"] == "ConnectionError":
                STATE.error_connection.append(error_entry)
                error_stream = "error_connection"
            elif result["error_type"] == "ChunkedEncodingError":
                STATE.error_chunked.append(error_entry)
                error_stream = "error_chunked"
            elif result["error_type"] == "HTTPError":
                STATE.error_http.append(error_entry)
                error_stream = "error_http"
        for ce in result.get("console_errors") or []:
            entry = {"timestamp": result["timestamp"], "url": url, "error": ce}
            STATE.console_logs.append(entry)
            console_entries.append(entry)
        if _depth_ok(depth + 1):
            for link in links:
                eligible = _eligible(link, rp)
                if not eligible or eligible in STATE.visited or eligible in STATE.queued:
                    continue
                STATE.queue.append((eligible, url, depth + 1))
                STATE.queued.add(eligible)
                edge = {"url": eligible, "discovered_from": url, "depth": depth + 1}
                STATE.discovered_edges.append(edge)
                csv_writer.append("discovered_edges", edge)
                added += 1
        STATE.stats.discovered += added
        STATE.stats.queue_size = len(STATE.queue)

    # disk writes outside the state lock
    csv_writer.append("results", result)
    if error_entry is not None:
        csv_writer.append("errors", error_entry)
        if error_stream:
            csv_writer.append(error_stream, error_entry)
    for entry in console_entries:
        csv_writer.append("console_logs", entry)
    return added


def _post_log(result: dict, url: str, depth: int, added: int) -> None:
    log_bus.post({
        "type": "success" if result["status"] == "OK" else "error",
        "message": (
            f"[{result['status_code']}] {url} — "
            f"{result['response_time_ms']}ms | {(result['title'] or '')[:60]}"
        ),
        "timestamp": datetime.now().isoformat(),
        "url": url,
        "depth": depth,
        "new_links": added,
        "crawled": STATE.stats.crawled,
        "queue_size": STATE.stats.queue_size,
        "discovered": STATE.stats.discovered,
        "errors": STATE.stats.errors,
        "ok": STATE.stats.ok,
    })


def _limit_reached() -> bool:
    return settings.max_pages > 0 and STATE.stats.crawled >= settings.max_pages


def run_crawl() -> None:
    """Top-level crawl runner. Blocks until the frontier is drained or stop requested."""
    STATE.is_running = True
    STATE.should_stop = False

    session = new_session()
    rp, robots_sitemaps = robots_mod.load(session)
    delay = robots_mod.crawl_delay(rp)
    log_bus.post({
        "type": "info",
        "message": (
            f"Loaded robots.txt — {len(robots_sitemaps)} sitemap ref(s)"
            + (f", crawl-delay {delay}s" if delay else "")
        ),
        "timestamp": datetime.now().isoformat(),
    })

    resumed = _maybe_resume()
    if not resumed:
        STATE.stats = CrawlStats(started_at=time.time())
    else:
        regained = _requeue_gaps_from_discovered_csv(rp)
        if regained:
            log_bus.post({
                "type": "info",
                "message": f"Re-queued {regained} discovered URL(s) missing from the saved frontier",
                "timestamp": datetime.now().isoformat(),
            })
    csv_writer.open_streams(resume=resumed)

    seeded = _seed(session, rp, robots_sitemaps)
    log_bus.post({
        "type": "info",
        "message": (
            f"Frontier ready — {len(STATE.queue)} URL(s) queued "
            f"({seeded} new this run)"
        ),
        "timestamp": datetime.now().isoformat(),
    })

    # effective politeness pause applied after every fetch
    per_request_pause = max(delay, settings.per_worker_delay / max(settings.max_workers, 1))
    per_request_pause += max(0.0, settings.extra_request_delay)

    def submit(pool: ThreadPoolExecutor) -> Future | None:
        if not STATE.queue or STATE.should_stop or _limit_reached():
            return None
        url, parent, depth = STATE.queue.popleft()
        STATE.stats.active_workers += 1
        fut = pool.submit(fetch, url, session)
        fut._meta = (url, parent, depth)  # type: ignore[attr-defined]
        return fut

    def fill(pool: ThreadPoolExecutor, in_flight: set[Future]) -> None:
        """Top the pool up to max_workers."""
        with STATE.lock:
            while len(in_flight) < settings.max_workers:
                f = submit(pool)
                if f is None:
                    return
                in_flight.add(f)

    with ThreadPoolExecutor(max_workers=settings.max_workers) as pool:
        in_flight: set[Future] = set()
        fill(pool, in_flight)

        while in_flight:
            if STATE.should_stop:
                log_bus.post({
                    "type": "stopped",
                    "message": "Stop requested — draining workers...",
                    "timestamp": datetime.now().isoformat(),
                })
                break
            done = {f for f in in_flight if f.done()}
            if not done:
                time.sleep(0.05)
                continue
            for fut in done:
                in_flight.discard(fut)
                url, parent, depth = fut._meta  # type: ignore[attr-defined]
                try:
                    result, links = fut.result()
                except Exception as exc:  # noqa: BLE001
                    result = {
                        "url": url, "final_url": url, "status_code": 0,
                        "status": "Worker crash", "title": "", "word_count": 0,
                        "response_time_ms": 0, "content_type": "",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:200], "console_errors": [],
                        "timestamp": datetime.now().isoformat(),
                    }
                    links = []
                added = _ingest(url, parent, depth, result, links, rp)
                STATE.stats.active_workers = max(0, STATE.stats.active_workers - 1)
                _post_log(result, url, depth, added)

                if STATE.stats.crawled % settings.checkpoint_every == 0:
                    csv_writer.flush_streams()
                    csv_writer.save_state(final=False)
                    log_bus.post({
                        "type": "info",
                        "message": f"Checkpoint saved at {STATE.stats.crawled} pages",
                        "timestamp": datetime.now().isoformat(),
                    })

                fill(pool, in_flight)

                if per_request_pause > 0:
                    time.sleep(per_request_pause)

    STATE.stats.finished_at = time.time()
    csv_writer.flush_streams()
    csv_writer.close_streams()
    csv_writer.save_state(final=True)
    elapsed = (STATE.stats.finished_at or 0) - (STATE.stats.started_at or 0)
    log_bus.post({
        "type": "complete",
        "message": (
            f"Crawl complete: {STATE.stats.crawled} pages, "
            f"{STATE.stats.errors} errors in {elapsed:.1f}s"
        ),
        "timestamp": datetime.now().isoformat(),
        "stats": STATE.stats.as_dict(),
    })
    STATE.is_running = False
    log.info(
        "Crawl done — %d pages, %d errors, %.1fs",
        STATE.stats.crawled, STATE.stats.errors, elapsed,
    )
