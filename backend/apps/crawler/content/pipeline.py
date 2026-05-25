"""Orchestrator — calls Tier 1 (rules), then Tier 2 (TF-IDF profiles)
and Tier 3 (MiniLM seeds) when needed.

Phase 1a: Tier 1 only. Tier 2 + 3 stub out as no-ops until they're
implemented in follow-up phases.

Public entry: ``classify_row(row) → dict``.
"""
from __future__ import annotations

from typing import Iterable

from .rules import classify_tier1, ClassificationResult
from .taxonomy import UNCERTAIN_THRESHOLD


def classify_row(row: dict) -> dict:
    """Classify one crawl-result row. Always returns a dict suitable
    for direct JSON serialization."""
    result = classify_tier1(row)
    # Tier 2 / Tier 3 will hook in here once built. For now we return
    # whatever Tier 1 produced (may be `uncertain`).
    return result.to_dict()


def classify_batch(rows: Iterable[dict]) -> list[dict]:
    """Convenience: classify many rows. Each output dict carries the
    same URL/title key so downstream code can join by URL."""
    out: list[dict] = []
    for row in rows:
        result = classify_row(row)
        out.append({
            "url": row.get("url", ""),
            "title": row.get("title", ""),
            "status_code": row.get("status_code", ""),
            **result,
        })
    return out


def aggregate_stats(classifications: list[dict]) -> dict:
    """Build the summary numbers we print after a classification run."""
    from collections import Counter
    total = len(classifications)
    uncertain = sum(1 for c in classifications if c.get("uncertain"))

    product_counts: Counter[str] = Counter()
    for c in classifications:
        for p in c.get("products", []):
            product_counts[p["label"]] += 1

    page_type_counts = Counter(c.get("page_type", "other") for c in classifications)

    # Multi-label distribution
    multilabel_distribution = Counter(
        len(c.get("products", [])) for c in classifications
    )

    # Confidence distribution
    confidences = [
        c.get("page_type_confidence", 0) for c in classifications
        if c.get("page_type") != "other"
    ]
    avg_pt_conf = sum(confidences) / len(confidences) if confidences else 0.0

    return {
        "total": total,
        "uncertain": uncertain,
        "uncertain_pct": round(100 * uncertain / total, 1) if total else 0,
        "by_product": dict(product_counts.most_common()),
        "by_page_type": dict(page_type_counts.most_common()),
        "products_per_page": dict(multilabel_distribution),
        "avg_page_type_confidence": round(avg_pt_conf, 3),
    }
