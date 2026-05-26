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
    for direct JSON serialization.

    Tier order:
      1. classify_tier1   — rules over URL + title + JSON-LD
      2. (placeholder)    — TF-IDF profile scoring [Phase 1b]
      3. classify_tier3   — MiniLM seed-based cosine fallback

    Tiers 2/3 only fire when Tier 1 returns `uncertain` to keep
    runtime tight on the 80% of pages with clear signals.
    """
    tier1 = classify_tier1(row)
    result_dict = tier1.to_dict()

    if tier1.is_uncertain:
        # Lazy-import so non-classification code paths don't pay the
        # sentence-transformers import cost.
        try:
            from .embedding_classifier import classify_tier3
            visible = _visible_text(row)
            t3 = classify_tier3(visible)
            # Merge: Tier 3 fills in fields Tier 1 left empty.
            if t3["products"] and not result_dict["products"]:
                result_dict["products"] = t3["products"]
                result_dict["tier"] = 3
                result_dict["signals"].extend(t3["signals"])
            if t3["page_type"] != "other" and result_dict["page_type"] == "other":
                result_dict["page_type"] = t3["page_type"]
                result_dict["page_type_confidence"] = t3["page_type_confidence"]
                result_dict["tier"] = 3
                result_dict["signals"].extend(
                    [s for s in t3["signals"] if "page_type" in s]
                )
            # Recompute the uncertain flag after merging.
            has_pt = result_dict["page_type_confidence"] >= UNCERTAIN_THRESHOLD
            has_prod = any(
                p.get("confidence", 0) >= UNCERTAIN_THRESHOLD
                for p in result_dict["products"]
            )
            result_dict["uncertain"] = not (has_pt or has_prod)
        except Exception as exc:  # noqa: BLE001 — never break the pipeline
            result_dict["signals"].append(f"tier3:error:{type(exc).__name__}")

    return result_dict


def _visible_text(row: dict) -> str:
    """Concatenate the searchable text fields for Tier 3 embedding.
    The crawler doesn't keep full body_text for Bajaj rows (only meta
    + title + h1), so we work with what we have."""
    parts = [
        row.get("title", "") or "",
        row.get("meta_description", "") or "",
    ]
    return " ".join(p for p in parts if p)


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
