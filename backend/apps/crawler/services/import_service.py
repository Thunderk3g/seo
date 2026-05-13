"""One-shot importer — copies ``data_complete/`` into ``backend/data/``."""
from __future__ import annotations

import shutil
from pathlib import Path

from ..conf import settings
from ..logger import get_logger

log = get_logger(__name__)

_FILES = [
    "crawl_results.csv", "crawl_errors.csv", "crawl_404_errors.csv",
    "crawl_errors_httperror.csv", "crawl_errors_connectionerror.csv",
    "crawl_errors_chunkedencodingerror.csv", "crawl_console_log.csv",
    "crawl_discovered.csv", "crawl_results.json", "crawl_state.json",
]


def import_legacy(source: Path | None = None, overwrite: bool = False) -> dict:
    """Copy known CSV/JSON files from source into ``settings.data_path``.

    Returns ``{copied: [...], skipped: [...]}``.
    """
    src = source or settings.legacy_data_path
    dst = settings.data_path
    dst.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    skipped: list[str] = []

    if not src.exists():
        log.info("Legacy data dir %s not found — skipping import", src)
        return {"copied": [], "skipped": _FILES}

    for name in _FILES:
        s = src / name
        d = dst / name
        if not s.exists():
            skipped.append(name)
            continue
        if d.exists() and not overwrite:
            skipped.append(name)
            continue
        shutil.copy2(s, d)
        copied.append(name)
    log.info("Imported %d legacy file(s) from %s", len(copied), src)
    return {"copied": copied, "skipped": skipped}


def import_if_empty() -> None:
    """Run on startup if backend/data is empty."""
    results = settings.data_path / "crawl_results.csv"
    if results.exists():
        return
    import_legacy(overwrite=False)
