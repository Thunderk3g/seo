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
from . import psi_scheduler
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
    # Register sitemap-origin URLs so csv_writer can stamp `from_sitemap` on
    # each row. We normalise here (same as the eligibility check below) so a
    # later lookup against the visited URL matches by identity.
    with STATE.lock:
        STATE.sitemap_urls.update(normalize(u) for u in sitemap_urls if u)
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
            elif result["error_type"] == "HTTPError":
                STATE.error_http.append(error_entry)
                error_stream = "error_http"
            # ConnectionError / ChunkedEncodingError categories retired —
            # they roll up into STATE.errors / crawl_errors.csv via the
            # generic path above; no per-class CSV is written.
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

    # Inline PSI: hand the URL off to the background scheduler. No-op
    # when PSI is disabled or the scheduler isn't running. Submit only
    # the canonical (post-redirect) URL — same key the CSV row uses.
    sched = psi_scheduler.get_current()
    if sched is not None:
        try:
            sched.submit(final_url or url)
        except Exception as exc:  # noqa: BLE001
            log.warning("psi submit failed for %s: %s", url, exc)
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
    """Top-level crawl runner. Blocks until the frontier is drained or stop requested.

    The whole body is wrapped in try/finally so ``is_running`` ALWAYS
    clears on exit — clean finish, exception, or thread kill. Previously
    a crash anywhere between ``is_running=True`` and the bottom of the
    function left the singleton flag stuck on, and every subsequent Start
    API call got rejected with 409 until the container was restarted.
    """
    STATE.is_running = True
    STATE.should_stop = False
    # Phase 3 — start a CrawlSnapshot row so dual-written CrawlerPage-
    # Result records know which run they belong to. Silently no-ops
    # when Postgres is down; legacy CSV path keeps working.
    snap_id: str | None = None
    crash_msg: str = ""
    try:
        from ..services import snapshot as snapshot_svc
        snap_id = snapshot_svc.start_snapshot(
            engine="legacy",
            seed_url=settings.seed_url,
            allowed_domains=list(settings.allowed_domains),
            config={
                "max_workers": getattr(settings, "max_workers", None),
                "max_depth": getattr(settings, "max_depth", None),
                "max_pages": getattr(settings, "max_pages", None),
                "psi_inline_enabled": getattr(settings, "psi_inline_enabled", None),
            },
        )
    except Exception:  # noqa: BLE001 - never block crawl on Postgres
        snap_id = None
    try:
        _run_crawl_body()
    except Exception as exc:  # noqa: BLE001
        crash_msg = f"{type(exc).__name__}: {exc}"
        log.exception("crawl-engine thread crashed: %s", exc)
        log_bus.post({
            "type": "error",
            "message": f"Crawl thread crashed: {crash_msg}",
            "timestamp": datetime.now().isoformat(),
        })
    finally:
        STATE.is_running = False
        STATE.stats.finished_at = STATE.stats.finished_at or time.time()
        STATE.stats.active_workers = 0
        # Close crawler CSV handles BEFORE the PSI merger rewrites
        # crawl_results.csv — otherwise the rewrite would orphan rows
        # the crawler hasn't yet flushed.
        try:
            csv_writer.flush_streams()
            csv_writer.close_streams()
        except Exception:  # noqa: BLE001
            pass
        # If _run_crawl_body crashed, mark snapshot failed. The normal
        # completion path inside _run_crawl_body calls
        # finish_snapshot(status='complete') itself.
        if crash_msg:
            try:
                from ..services import snapshot as snapshot_svc
                snapshot_svc.finish_snapshot(
                    status="failed",
                    pages_attempted=STATE.stats.crawled,
                    pages_ok=STATE.stats.ok,
                    pages_errored=STATE.stats.errors,
                    notes=crash_msg,
                )
            except Exception:  # noqa: BLE001
                pass
        # Drain the inline PSI scheduler and do one atomic merge into
        # crawl_results.csv. Runs even on stop/error so whatever PSI
        # data we already collected lands in the CSV.
        sched = psi_scheduler.get_current()
        if sched is not None:
            try:
                _finalise_psi_scheduler(sched)
            except Exception as exc:  # noqa: BLE001
                log.warning("psi scheduler finalise failed: %s", exc)
            finally:
                psi_scheduler.set_current(None)


def _finalise_psi_scheduler(sched) -> None:
    """Drain workers + atomic-merge the sidecar into crawl_results.csv.

    Split out so the ``finally`` block stays readable. Mirrors the
    Phase 3 log shape from the legacy batch path so the UI banner /
    PSI status JSON keep working.
    """
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    from .psi_capture import _write_status

    snap_before = sched.progress()
    started = (
        _dt.fromtimestamp(snap_before["started_at"], tz=_tz.utc).isoformat()
        if snap_before.get("started_at") else _dt.now(_tz.utc).isoformat()
    )
    sched.stop(drain=not STATE.should_stop)
    rows_merged = sched.merge_into_results_csv()
    snap = sched.progress()
    if sched.is_disabled:
        _write_status({
            "ok": False,
            "error": sched.disabled_reason or "PSI disabled",
            "started_at": started,
            "finished_at": _dt.now(_tz.utc).isoformat(),
            "urls_inspected": 0,
            "rows_written": 0,
            "failed": 0,
            "mode": "inline",
        })
        return
    _write_status({
        "ok": rows_merged > 0 or snap["completed"] > 0,
        "error": "",
        "started_at": started,
        "finished_at": _dt.now(_tz.utc).isoformat(),
        "urls_inspected": snap["completed"],
        "rows_written": rows_merged,
        "failed": snap["failed"],
        "strategies": snap["strategies"],
        "primary_strategy": snap["primary_strategy"],
        "mode": "inline",
    })
    log_bus.post({
        "type": "info",
        "message": (
            f"PSI inline merged {rows_merged} row(s) into crawl_results.csv "
            f"(completed={snap['completed']}, failed={snap['failed']})"
        ),
        "timestamp": _dt.now().isoformat(),
    })


def _run_crawl_body() -> None:
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

    # ── Inline PSI scheduler ─────────────────────────────────────────
    # Spin up the background PSI worker pool BEFORE the crawl loop so
    # the first finished URL can be submitted immediately. ``start()``
    # returns False if PSI is disabled (missing SA file, etc.); in
    # that case we register a None handle and ``_ingest`` becomes a
    # no-op for the submit call.
    if getattr(settings, "psi_inline_enabled", True):
        sched = psi_scheduler.InlinePSIScheduler()
        if sched.start():
            psi_scheduler.set_current(sched)
            log_bus.post({
                "type": "info",
                "message": (
                    f"Inline PSI scheduler online — {sched.workers} worker(s), "
                    f"strategies={list(sched.strategies)}. CWV columns will "
                    f"populate as the crawl progresses."
                ),
                "timestamp": datetime.now().isoformat(),
            })
        else:
            log_bus.post({
                "type": "warning",
                "message": (
                    "Inline PSI disabled: "
                    f"{sched.disabled_reason or 'unknown reason'}"
                ),
                "timestamp": datetime.now().isoformat(),
            })

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

    # ── Phase 2: browser-side console capture ────────────────────────────
    # The static crawl above only sees the HTML at fetch time — it cannot
    # observe JavaScript errors that happen at runtime. Run a Playwright
    # pass on the www HTTP-200 pages we just crawled to capture real
    # console errors, page errors, and failed network requests. Disabled
    # if `settings.capture_console_after_crawl` is False (default True).
    if getattr(settings, "capture_console_after_crawl", True) and not STATE.should_stop:
        try:
            from . import browser_console
            console_targets = browser_console.select_target_urls(
                limit=getattr(settings, "console_capture_limit", 200),
                subdomain="www",
                only_status="200",
            )
            if console_targets:
                log_bus.post({
                    "type": "info",
                    "message": (
                        f"Phase 2 — capturing real browser console for "
                        f"{len(console_targets)} URL(s) via Playwright..."
                    ),
                    "timestamp": datetime.now().isoformat(),
                })
                # Streams are already open from phase 1; capture writes
                # into the existing console_logs stream.
                browser_console.capture(
                    console_targets,
                    wait_after_load_ms=1500,
                    levels=("error", "warning"),
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("phase 2 console capture failed: %s", exc)
            log_bus.post({
                "type": "warning",
                "message": f"Console capture skipped: {exc}",
                "timestamp": datetime.now().isoformat(),
            })

    # ── Phase 3: PSI / Core Web Vitals (legacy batch fallback) ──────────
    # The default path is the inline scheduler started before the crawl
    # loop (see ``_run_crawl_body`` top). The batch path below only runs
    # when CRAWLER_PSI_INLINE=false. It is kept for environments that
    # explicitly opt out of the concurrent scheduler (e.g. unit tests).
    inline_active = (
        getattr(settings, "psi_inline_enabled", True)
        and psi_scheduler.get_current() is not None
    )
    if (
        not inline_active
        and getattr(settings, "capture_psi_after_crawl", True)
        and not STATE.should_stop
    ):
        try:
            from . import psi_capture
            psi_targets = psi_capture.select_target_urls(
                limit=getattr(settings, "psi_capture_limit", 100),
                subdomain="www",
                only_status="200",
            )
            if psi_targets:
                log_bus.post({
                    "type": "info",
                    "message": (
                        f"Phase 3 (batch) — capturing CWV for "
                        f"{len(psi_targets)} URL(s) via PageSpeed Insights..."
                    ),
                    "timestamp": datetime.now().isoformat(),
                })
                psi_result = psi_capture.capture(psi_targets)
                if not psi_result.get("ok"):
                    log_bus.post({
                        "type": "warning",
                        "message": (
                            "PSI capture skipped: "
                            f"{psi_result.get('error', 'unknown reason')}"
                        ),
                        "timestamp": datetime.now().isoformat(),
                    })
                else:
                    log_bus.post({
                        "type": "info",
                        "message": (
                            f"Phase 3 done — merged "
                            f"{psi_result.get('rows_written', 0)} PSI rows "
                            f"(failed={psi_result.get('failed', 0)})"
                        ),
                        "timestamp": datetime.now().isoformat(),
                    })
        except Exception as exc:  # noqa: BLE001
            log.warning("phase 3 psi capture failed: %s", exc)
            log_bus.post({
                "type": "warning",
                "message": f"PSI capture skipped: {exc}",
                "timestamp": datetime.now().isoformat(),
            })

    # Normal completion. The outer try/finally in run_crawl() also handles
    # the close_streams / finished_at fallbacks, so it's safe if any of
    # this raises.
    STATE.stats.finished_at = time.time()
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
    log.info(
        "Crawl done — %d pages, %d errors, %.1fs",
        STATE.stats.crawled, STATE.stats.errors, elapsed,
    )
    # Phase 3 — finalise the snapshot with stats + Health Score. Silent
    # no-op when Postgres is down or no snapshot was started.
    try:
        from ..services import snapshot as snapshot_svc
        from ..services.health_score import compute as compute_health
        hs = None
        try:
            hs = compute_health()
        except Exception:  # noqa: BLE001
            hs = None
        snapshot_svc.finish_snapshot(
            status="complete",
            pages_attempted=STATE.stats.crawled,
            pages_ok=STATE.stats.ok,
            pages_errored=STATE.stats.errors,
            health_score=hs.score if hs else None,
            health_tier=hs.tier if hs else "",
        )
    except Exception:  # noqa: BLE001
        pass
