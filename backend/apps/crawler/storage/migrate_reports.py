"""One-shot migration: backfill the five enrichment columns onto existing
CSVs that pre-date the category-segregated reports schema.

Triggered automatically by ``csv_writer.open_streams(resume=True)`` when it
detects an old header. Also exposed as a Django management command::

    python manage.py crawler_migrate_reports

Per CSV in ``backend/data/``:

    1. If the header already contains ``category_key``, skip (idempotent).
    2. Otherwise, copy ``<file>`` -> ``<file>.bak`` (one-shot backup),
       stream-rewrite to ``<file>.tmp`` with the 5 new columns appended,
       calling the classifier + GSC loader for each row. ``from_sitemap``
       is unknown for historic rows, so it is recorded as ``"unknown"``
       (treated as falsy in UI filters and SQL queries).
    3. Atomic rename ``<file>.tmp`` -> ``<file>``.

The script never deletes data; the ``.bak`` files stay until an operator
removes them.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from ..conf import settings
from ..logger import get_logger
from . import gsc_loader, url_classifier

log = get_logger(__name__)

# Filenames the migration touches. Anything else in ``backend/data/`` is
# untouched. The list intentionally includes the hand-curated branch
# extracts so they get categorised too.
_TARGETS = (
    "crawl_results.csv",
    "crawl_errors.csv",
    "crawl_404_errors.csv",
    "crawl_errors_httperror.csv",
    "crawl_errors_connectionerror.csv",
    "crawl_errors_chunkedencodingerror.csv",
    "crawl_console_log.csv",
    "crawl_discovered.csv",
    "branch_404.csv",
    "crawl_404_errors_branch.csv",
)

# Columns appended to every CSV header (in this order, after existing ones).
_NEW_COLS = ["subdomain", "page_type", "category_key",
             "from_sitemap", "indexed_status"]


def run(data_dir: Path | None = None) -> dict:
    """Migrate every applicable CSV under ``data_dir``.

    Returns a summary dict ``{file: {status, rows}}`` for logging / CLI output.
    """
    base = Path(data_dir or settings.data_path)
    summary: dict[str, dict] = {}
    # Force a fresh coverage load before the run so historic backfills see
    # the latest GSC export the operator just dropped in.
    gsc_loader.invalidate_cache()
    coverage = gsc_loader.load_coverage_map()
    for name in _TARGETS:
        path = base / name
        if not path.exists() or path.stat().st_size == 0:
            summary[name] = {"status": "missing", "rows": 0}
            continue
        summary[name] = _migrate_file(path, coverage)
    return summary


def _migrate_file(path: Path, coverage: dict[str, str]) -> dict:
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            header = next(csv.reader(f), [])
    except Exception as exc:  # noqa: BLE001
        log.warning("migrate_reports: cannot read header of %s: %s", path, exc)
        return {"status": "error", "rows": 0, "detail": str(exc)}
    if "category_key" in header:
        return {"status": "skipped", "rows": 0}

    new_header = list(header) + [c for c in _NEW_COLS if c not in header]
    tmp = path.with_suffix(path.suffix + ".tmp")
    bak = path.with_suffix(path.suffix + ".bak")
    rows_written = 0
    try:
        with open(path, "r", encoding="utf-8", newline="") as src, \
             open(tmp, "w", encoding="utf-8", newline="") as dst:
            reader = csv.DictReader(src)
            writer = csv.DictWriter(dst, fieldnames=new_header,
                                    extrasaction="ignore")
            writer.writeheader()
            for row in reader:
                _enrich_for_migration(row, coverage)
                writer.writerow(row)
                rows_written += 1
        if not bak.exists():
            # Keep the original bytes once; subsequent re-runs of the
            # migration are no-ops (header already migrated) so we don't
            # clobber a working backup.
            try:
                bak.write_bytes(path.read_bytes())
            except OSError as exc:
                log.warning(
                    "migrate_reports: could not write backup %s: %s",
                    bak, exc,
                )
        tmp.replace(path)
        log.info("migrate_reports: %s rows=%s", path.name, rows_written)
        return {"status": "migrated", "rows": rows_written}
    except Exception as exc:  # noqa: BLE001
        log.warning("migrate_reports: %s failed: %s", path.name, exc)
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return {"status": "error", "rows": rows_written, "detail": str(exc)}


def _enrich_for_migration(row: dict, coverage: dict[str, str]) -> None:
    """Stamp the five new columns onto a single row, in-place."""
    url = (row.get("url") or "").strip()
    cls = url_classifier.classify(url)
    row.setdefault("subdomain", cls["subdomain"])
    row.setdefault("page_type", cls["page_type"])
    row.setdefault("category_key", cls["category_key"])
    # `from_sitemap` is unrecoverable for historic rows — record the
    # ambiguity rather than guessing.
    row.setdefault("from_sitemap", "unknown")
    if url:
        key = gsc_loader.normalize_url(url)
        row.setdefault("indexed_status", coverage.get(key, "unknown"))
    else:
        row.setdefault("indexed_status", "unknown")


# ── Convenience for ad-hoc CLI use ────────────────────────────────────────
def format_summary(summary: dict[str, dict]) -> str:
    lines = []
    for name, info in summary.items():
        lines.append(f"  {name:<40} {info['status']:<10} rows={info['rows']}")
    return "\n".join(lines)


def iter_migrated_paths(data_dir: Path | None = None) -> Iterable[Path]:
    """Yield each ``<file>.bak`` left behind by past migrations."""
    base = Path(data_dir or settings.data_path)
    yield from base.glob("*.csv.bak")
