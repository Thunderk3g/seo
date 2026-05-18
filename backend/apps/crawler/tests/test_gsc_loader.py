"""Tests for the GSC Coverage CSV loader."""
from __future__ import annotations

import csv
import time
from pathlib import Path

import pytest

from apps.crawler.storage import gsc_loader


@pytest.fixture(autouse=True)
def _coverage_dir(tmp_path, monkeypatch):
    """Point gsc_loader at a tmp coverage directory + flush cache between tests."""
    cov_dir = tmp_path / "gsc" / "coverage"
    cov_dir.mkdir(parents=True)
    monkeypatch.setattr(gsc_loader, "coverage_dir", lambda: cov_dir)
    gsc_loader.invalidate_cache()
    yield cov_dir
    gsc_loader.invalidate_cache()


def _write_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["URL", "Indexing status"])
        for url, status in rows:
            w.writerow([url, status])


def test_returns_empty_when_no_file(_coverage_dir):
    assert gsc_loader.load_coverage_map() == {}
    assert gsc_loader.status_for("https://www.bajajlifeinsurance.com/") == "unknown"


def test_maps_indexed_not_indexed_excluded(_coverage_dir):
    _write_csv(_coverage_dir / "coverage_2026-05-18.csv", [
        ("https://www.bajajlifeinsurance.com/term-insurance-plans.html",
         "Submitted and indexed"),
        ("https://www.bajajlifeinsurance.com/ulip-plans.html",
         "Crawled - currently not indexed"),
        ("https://www.bajajlifeinsurance.com/old-page.html",
         "Not found (404)"),
        ("https://branch.bajajlifeinsurance.com/something",
         "URL is not on Google"),
    ])
    m = gsc_loader.load_coverage_map()
    assert m["https://www.bajajlifeinsurance.com/term-insurance-plans.html"] == "indexed"
    assert m["https://www.bajajlifeinsurance.com/ulip-plans.html"] == "not_indexed"
    assert m["https://www.bajajlifeinsurance.com/old-page.html"] == "excluded"
    assert m["https://branch.bajajlifeinsurance.com/something"] == "excluded"


def test_missing_url_returns_unknown(_coverage_dir):
    _write_csv(_coverage_dir / "coverage_a.csv", [
        ("https://www.bajajlifeinsurance.com/term-insurance-plans.html",
         "Submitted and indexed"),
    ])
    assert gsc_loader.status_for("https://www.bajajlifeinsurance.com/never-mentioned") == "unknown"


def test_mtime_invalidates_cache(_coverage_dir):
    f = _coverage_dir / "coverage_initial.csv"
    _write_csv(f, [("https://www.bajajlifeinsurance.com/a", "Submitted and indexed")])
    m1 = gsc_loader.load_coverage_map()
    assert m1["https://www.bajajlifeinsurance.com/a"] == "indexed"

    # Now drop a newer file with different data. The loader must pick it up
    # without an explicit invalidate (mtime-based cache).
    time.sleep(0.05)
    f2 = _coverage_dir / "coverage_newer.csv"
    _write_csv(f2, [
        ("https://www.bajajlifeinsurance.com/a", "Crawled - currently not indexed"),
        ("https://www.bajajlifeinsurance.com/b", "Submitted and indexed"),
    ])
    m2 = gsc_loader.load_coverage_map()
    assert m2["https://www.bajajlifeinsurance.com/a"] == "not_indexed"
    assert m2["https://www.bajajlifeinsurance.com/b"] == "indexed"


def test_normalises_tracking_params(_coverage_dir):
    _write_csv(_coverage_dir / "coverage_norm.csv", [
        ("https://www.bajajlifeinsurance.com/term-insurance-plans.html",
         "Submitted and indexed"),
    ])
    # Same URL with utm params should still match.
    assert gsc_loader.status_for(
        "https://www.bajajlifeinsurance.com/term-insurance-plans.html?utm_source=ads&utm_campaign=q2"
    ) == "indexed"
    # Different host casing should still match.
    assert gsc_loader.status_for(
        "https://WWW.BAJAJLIFEINSURANCE.COM/term-insurance-plans.html"
    ) == "indexed"
    # Trailing slash is normalised away.
    assert gsc_loader.normalize_url(
        "https://www.bajajlifeinsurance.com/term-insurance-plans/"
    ) == "https://www.bajajlifeinsurance.com/term-insurance-plans"


def test_unrecognised_status_becomes_unknown(_coverage_dir):
    _write_csv(_coverage_dir / "coverage_weird.csv", [
        ("https://www.bajajlifeinsurance.com/x", "Some made-up status that does not exist"),
    ])
    assert gsc_loader.status_for("https://www.bajajlifeinsurance.com/x") == "unknown"


def test_pick_picks_most_recent(_coverage_dir):
    older = _coverage_dir / "coverage_old.csv"
    _write_csv(older, [("https://www.bajajlifeinsurance.com/a", "Submitted and indexed")])
    time.sleep(0.05)
    newer = _coverage_dir / "coverage_2026.csv"
    _write_csv(newer, [("https://www.bajajlifeinsurance.com/a", "Crawled - currently not indexed")])
    assert gsc_loader.load_coverage_map()["https://www.bajajlifeinsurance.com/a"] == "not_indexed"
