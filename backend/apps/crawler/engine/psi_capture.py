"""Core Web Vitals capture via PageSpeed Insights.

Companion to ``browser_console.py``: where that module captures live
JS errors via Playwright, this one captures LCP / CLS / INP / FCP /
TBT / TTFB via Google's PSI API. Returns both lab (Lighthouse) and
field (CrUX p75 real-user) numbers.

We do NOT write a sidecar CSV — instead, PSI results are merged back
into ``crawl_results.csv`` as extra columns on the existing rows.
This keeps the operator looking at one file: each URL row in the main
results table gains ``pagespeed_score``, ``lcp_ms``, ``cls``, and
``inp_ms`` populated for the PSI subset (mobile strategy, top N
HTTP-200 www pages, capped by ``PSI_MAX_URLS_PER_RUN``).

After every run we persist a small status file at
``{data_dir}/_psi_status.json`` so the frontend can show "last PSI run
skipped because <reason>" instead of a silently empty column. The
frontend reads this via ``GET /api/v1/crawler/psi/status``.

Field metrics are preferred when CrUX has data for the URL (real-user
p75 across 28 days); lab metrics are the fallback for low-traffic
pages with no field data.

PSI is slow — mobile 1-3 s/call, desktop 30-40 s/call. With mobile-only
and 100 URLs the worst case is ~5 min. The free quota is 25 k/day so
even a 100-URL run is < 1 % of budget.

Disabled silently when PSI_ENABLED=false, the service-account JSON is
missing, or ``crawl_results.csv`` has no eligible rows.

Run via:

    python manage.py capture_psi [--limit N] [--strategies mobile,desktop]

or automatically at the end of every crawl via the engine hook.
"""
from __future__ import annotations

import csv
import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from ..conf import settings as crawler_settings
from ..logger import get_logger
from ..storage import csv_writer

log = get_logger(__name__)


def _status_path():
    return crawler_settings.data_path / "_psi_status.json"


def _write_status(status: dict) -> None:
    """Persist the most-recent PSI run outcome so the UI can render a
    banner. Atomic write via temp+rename so a crash mid-write can't
    corrupt the file. Best-effort: log and continue on disk error."""
    path = _status_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(status, f)
        tmp.replace(path)
    except OSError as exc:
        log.warning("psi_capture: status write failed: %s", exc)


def read_status() -> dict:
    """Return the last persisted PSI status. Empty dict if no PSI run
    has happened yet. Used by the API view that powers the UI banner."""
    path = _status_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


@dataclass
class PSICaptureState:
    is_running: bool = False
    should_stop: bool = False
    total: int = 0
    processed: int = 0
    failed: int = 0
    rows_written: int = 0
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
                "rows_written": self.rows_written,
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
            self.rows_written = 0
            self.started_at = None
            self.finished_at = None
            self.last_url = ""


CAPTURE_STATE = PSICaptureState()


# ── URL selection ──────────────────────────────────────────────────────────


def select_target_urls(
    *,
    limit: int = 100,
    subdomain: str = "www",
    only_status: str = "200",
) -> list[str]:
    """Read crawl_results.csv and pick which URLs to score.

    Same shape as ``browser_console.select_target_urls``. Defaults to
    the top ``limit`` www HTTP-200 URLs. PDFs / images / non-HTML rows
    are skipped — PSI only makes sense on rendered HTML.
    """
    path = crawler_settings.data_path / "crawl_results.csv"
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
                ctype = (row.get("content_type") or "").lower()
                if ctype and "html" not in ctype and "xml" not in ctype:
                    continue
                out.append(url)
                if limit and len(out) >= limit:
                    break
    except OSError as exc:
        log.warning("psi_capture: cannot read %s: %s", path, exc)
    return out


# ── Capture loop ───────────────────────────────────────────────────────────


def capture(
    urls: Iterable[str],
    *,
    strategies: tuple[str, ...] | None = None,
) -> dict:
    """Run PSI sequentially over ``urls``. Captured metrics are merged
    into ``crawl_results.csv`` as extra columns at the end of the run.

    Returns a summary dict matching ``browser_console.capture``'s shape.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        from apps.seo_ai.adapters.cwv_psi import (
            AdapterDisabledError,
            PSIAdapter,
        )
    except ImportError as exc:
        result = {"ok": False, "error": f"cwv_psi import: {exc}"}
        _write_status({**result, "started_at": started_at,
                       "finished_at": datetime.now(timezone.utc).isoformat(),
                       "urls_inspected": 0, "rows_written": 0, "failed": 0})
        return result

    try:
        psi = PSIAdapter()
    except AdapterDisabledError as exc:
        log.info("psi_capture: skipped (%s)", exc)
        result = {"ok": False, "error": str(exc)}
        _write_status({**result, "started_at": started_at,
                       "finished_at": datetime.now(timezone.utc).isoformat(),
                       "urls_inspected": 0, "rows_written": 0, "failed": 0})
        return result

    if strategies is None:
        from django.conf import settings as dj_settings
        strategies = tuple(
            (getattr(dj_settings, "PSI", {}) or {}).get("strategies")
            or ("mobile", "desktop")
        )

    # We surface mobile metrics on the main results row (mobile is what
    # Google cares about for ranking). Desktop is still captured and
    # cached on disk for the audit pipeline, just not merged into
    # crawl_results.csv — no room for an extra 4 columns per strategy
    # without doubling the schema.
    primary = "mobile" if "mobile" in strategies else strategies[0]

    url_list = list(urls)
    CAPTURE_STATE.reset()
    with CAPTURE_STATE.lock:
        CAPTURE_STATE.is_running = True
        CAPTURE_STATE.total = len(url_list) * len(strategies)
        CAPTURE_STATE.started_at = time.time()

    # url -> {pagespeed_score, lcp_ms, cls, inp_ms}. Only the primary
    # strategy's numbers go here; non-primary calls still hit the API
    # (so their disk cache populates for the audit pipeline) but their
    # values aren't merged into the row.
    psi_data: dict[str, dict] = {}
    failed = 0

    try:
        for i, url in enumerate(url_list):
            if CAPTURE_STATE.should_stop:
                log.info("psi_capture: stop requested at %s/%s", i, len(url_list))
                break
            for strategy in strategies:
                try:
                    record = psi.fetch(url, strategy=strategy)
                except Exception as exc:  # noqa: BLE001
                    log.warning("psi_capture: %s/%s crashed: %s", strategy, url, exc)
                    failed += 1
                    record = None
                if record is None or record.error:
                    if record and record.error:
                        failed += 1
                    if strategy == primary:
                        psi_data[url] = {
                            "pagespeed_score": "",
                            "lcp_ms": "",
                            "cls": "",
                            "inp_ms": "",
                        }
                elif strategy == primary:
                    psi_data[url] = _row_from_record(record)
                with CAPTURE_STATE.lock:
                    CAPTURE_STATE.processed += 1
                    CAPTURE_STATE.failed = failed
                    CAPTURE_STATE.last_url = url
    finally:
        with CAPTURE_STATE.lock:
            CAPTURE_STATE.is_running = False
            CAPTURE_STATE.finished_at = time.time()

    rows_merged = 0
    if psi_data:
        try:
            rows_merged = _merge_into_results_csv(psi_data)
        except Exception as exc:  # noqa: BLE001
            log.warning("psi_capture: results-csv merge failed: %s", exc)
            result = {
                "ok": False,
                "error": f"merge failed: {exc}",
                "urls_inspected": len(url_list),
                "failed": failed,
                "rows_written": 0,
            }
            _write_status({
                **result,
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "strategies": list(strategies),
                "primary_strategy": primary,
            })
            return result

    with CAPTURE_STATE.lock:
        CAPTURE_STATE.rows_written = rows_merged

    result = {
        "ok": True,
        "urls_inspected": len(url_list),
        "failed": failed,
        "rows_written": rows_merged,
        "strategies": list(strategies),
        "primary_strategy": primary,
    }
    _write_status({
        **result,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "error": "",
    })
    return result


# ── helpers ────────────────────────────────────────────────────────────────


def _row_from_record(record) -> dict:
    """Pick the four numbers we surface on the main results row.

    Field (CrUX p75) is preferred when present — it reflects what real
    Chrome users see. Lab is the fallback for low-traffic URLs.
    ``pagespeed_score`` is rescaled from PSI's 0-1 float to a 0-100
    integer because that's how Lighthouse historically presents it and
    it reads cleaner in a spreadsheet.
    """
    score = record.performance_score
    if isinstance(score, (int, float)):
        score = round(score * 100)
    else:
        score = ""

    lcp = record.field_lcp_ms if record.has_field_data else record.lab_lcp_ms
    cls = record.field_cls if record.has_field_data and record.field_cls is not None else record.lab_cls
    # INP is field-only — Lighthouse lab doesn't simulate user input.
    inp = record.field_inp_ms

    return {
        "pagespeed_score": score if score != "" else "",
        "lcp_ms": lcp if lcp is not None else "",
        "cls": round(cls, 3) if isinstance(cls, (int, float)) else "",
        "inp_ms": inp if inp is not None else "",
    }


# Single-flight lock for _merge_into_results_csv. After the inline PSI
# scheduler shipped in commit f0459d9, two callers race for the merge:
# the inline scheduler (engine.py finally block) AND the legacy Phase 3
# batch fallback. Both used to share the same crawl_results.csv.psi.tmp
# filename, leading to ENOENT during os.replace when one caller's tmp
# was renamed out from under another caller. The lock serialises the
# merge per process; the unique-tmp logic below handles the cross-
# process case (e.g., chained celery workers).
_merge_lock = threading.Lock()


def _merge_into_results_csv(psi_data: dict[str, dict],
                            *, _retry_remaining: int = 1) -> int:
    """Rewrite crawl_results.csv with PSI values filled in on rows whose
    URL is in ``psi_data``. Other rows are preserved verbatim. Done as
    a read-then-write-temp-then-rename so a crash mid-rewrite can't
    corrupt the file.

    Hardening shipped to fix the ENOENT race we observed in production:

      1. ``threading.Lock`` serialises merges within one process so the
         inline scheduler + legacy Phase 3 batch can't double-merge.
      2. Tmp filename is per-call unique (pid + ns counter) so two
         processes racing don't truncate each other's tmp.
      3. ``fout.flush()`` + ``os.fsync()`` before ``os.replace`` so the
         data is durable before the atomic rename.
      4. If ``os.replace`` still fails with ENOENT (transient overlay
         filesystem race in Docker), we recurse once with a fresh tmp.
      5. If that retry also fails we fall back to rebuilding the file
         in-place from the sidecar, logging loudly. The crawl_results
         file is preserved either way.

    IMPORTANT: callers must ensure no writer is appending to
    crawl_results.csv during this call. The engine's Phase 3 hook runs
    after the crawl loop is complete, so this is safe; standalone runs
    via ``capture_psi`` are also safe because the streams are closed.
    """
    path = crawler_settings.data_path / "crawl_results.csv"
    if not path.exists():
        log.info("psi_capture: %s missing — nothing to merge", path)
        return 0

    # Flush + close any open writer so the temp-rename is safe on
    # Windows (where you can't replace an open file).
    try:
        csv_writer.flush_streams()
        csv_writer.close_streams()
    except Exception:  # noqa: BLE001 - safe to ignore
        pass

    psi_cols = ("pagespeed_score", "lcp_ms", "cls", "inp_ms")

    # Per-call unique tmp name. Same directory as the target so
    # os.replace is atomic on POSIX + Windows. Includes PID + monotonic
    # ns counter so concurrent processes never collide.
    tmp = path.with_name(
        f"{path.name}.psi-{os.getpid()}-{time.time_ns()}.tmp"
    )

    with _merge_lock:
        merged = 0
        with open(path, "r", encoding="utf-8", newline="") as fin:
            reader = csv.DictReader(fin)
            header = list(reader.fieldnames or [])
            # If the file pre-dates the new columns, add them now.
            for col in psi_cols:
                if col not in header:
                    header.append(col)
            with open(tmp, "w", encoding="utf-8", newline="") as fout:
                writer = csv.DictWriter(
                    fout, fieldnames=header, extrasaction="ignore",
                )
                writer.writeheader()
                for row in reader:
                    url = (row.get("url") or "").strip()
                    values = psi_data.get(url)
                    if values:
                        for col in psi_cols:
                            row[col] = values.get(col, row.get(col, ""))
                        merged += 1
                    else:
                        for col in psi_cols:
                            row.setdefault(col, "")
                    writer.writerow(row)
                # Ensure bytes are on disk before the rename. Overlay
                # filesystems in Docker have surprised us here.
                try:
                    fout.flush()
                    os.fsync(fout.fileno())
                except (OSError, AttributeError):
                    pass

        try:
            os.replace(tmp, path)
            return merged
        except (FileNotFoundError, PermissionError) as exc:
            # Two failure modes we've seen:
            #   - FileNotFoundError: Docker overlay race / concurrent
            #     merge stole the tmp.
            #   - PermissionError: Windows file lock — usually the
            #     operator has crawl_results.csv open in Excel.
            kind = "missing tmp" if isinstance(exc, FileNotFoundError) else "target locked"
            log.warning(
                "psi_capture: os.replace failed (%s) "
                "(%s -> %s): %s; retries_left=%d",
                kind, tmp, path, exc, _retry_remaining,
            )
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            if _retry_remaining > 0:
                # Brief back-off in case the lock is from another
                # short-lived process (PSI scheduler finishing up).
                time.sleep(0.5)
                return _merge_into_results_csv(
                    psi_data, _retry_remaining=_retry_remaining - 1,
                )
            # Last-resort recovery: rewrite in-place. Skipped silently
            # if the same lock prevents `open(path, "w")` — in that
            # case the operator must close Excel and re-run.
            try:
                return _merge_inplace(path, psi_data, header, psi_cols)
            except PermissionError as inner:
                log.error(
                    "psi_capture: in-place rewrite also blocked by file "
                    "lock on %s (%s). Close whatever has the file open "
                    "(Excel / viewer / indexer) and re-run.",
                    path, inner,
                )
                return 0


def _merge_inplace(path, psi_data: dict[str, dict],
                   header: list[str], psi_cols: tuple[str, ...]) -> int:
    """Fallback merge that doesn't use tmp+rename. Reads the whole CSV
    into memory, writes back in place. Logged as a degraded path
    because a crash mid-write could corrupt the file."""
    log.warning(
        "psi_capture: falling back to in-place rewrite of %s "
        "(no tmp file — crash here will corrupt the CSV)", path,
    )
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8", newline="") as fin:
        reader = csv.DictReader(fin)
        for row in reader:
            rows.append(row)
    merged = 0
    with open(path, "w", encoding="utf-8", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            url = (row.get("url") or "").strip()
            values = psi_data.get(url)
            if values:
                for col in psi_cols:
                    row[col] = values.get(col, row.get(col, ""))
                merged += 1
            else:
                for col in psi_cols:
                    row.setdefault(col, "")
            writer.writerow(row)
        try:
            fout.flush()
            os.fsync(fout.fileno())
        except (OSError, AttributeError):
            pass
    return merged


def request_stop() -> None:
    with CAPTURE_STATE.lock:
        CAPTURE_STATE.should_stop = True
