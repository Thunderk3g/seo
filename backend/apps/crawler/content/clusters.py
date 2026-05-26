"""Hierarchical content-cluster tree — Phase 1c.

Buckets the latest snapshot's pages into:
    Product → Page-type → page list

This is the in-house, LLM-free counterpart to the 3D scatter map. The
3D map shows the *shape* of clusters; this view enumerates them so an
editor can walk the corpus product-by-product, see counts, and spot
gaps (e.g. "ULIP has 12 blog guides but zero calculators").

Two view modes:
    * primary  — each page assigned to its highest-confidence product
    * multi    — each page listed under every matching product (taxonomy intent)

Both modes share the same uncertain bucket: pages Tier-1 couldn't pin
down. Caller can re-run Tier 3 (MiniLM) on those if MiniLM is available.

No LLM provider needed — runs purely off classify_row's URL + title +
JSON-LD heuristics.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Literal

from .pipeline import classify_row
from .taxonomy import (
    PRODUCTS, PRODUCT_LABELS, PAGE_TYPES, PAGE_TYPE_LABELS,
)


Mode = Literal["primary", "multi"]


def _row_from_page(page) -> dict:
    """Adapt a CrawlerPageResult ORM row to the dict shape classify_row
    expects. Mirrors the synthesis used in embedder.embed_snapshot."""
    return {
        "url": page.url,
        "title": page.title or "",
        "meta_description": page.meta_description or "",
        "jsonld_types": page.jsonld_types or [],
        "status_code": str(page.status_code or ""),
    }


def _primary_product(products: list[dict]) -> str | None:
    """Return the label of the highest-confidence product, or None."""
    if not products:
        return None
    return max(products, key=lambda p: p.get("confidence", 0))["label"]


def build_clusters(snapshot, *, mode: Mode = "primary") -> dict:
    """Build the tree for a snapshot.

    Output shape (stable — frontend depends on this):

        {
          "snapshot_id": "...",
          "snapshot_date": "ISO-8601",
          "mode": "primary" | "multi",
          "totals": {
            "pages": int,
            "classified": int,
            "uncertain": int,
            "assignments": int,        # multi-mode: > pages; primary: == classified
          },
          "products": [
            {
              "product": "term",
              "label": "Term Insurance",
              "count": int,             # pages under this product (post-mode)
              "page_types": [
                {
                  "page_type": "calculator",
                  "label": "Calculator",
                  "count": int,
                  "pages": [
                    {"url", "title", "confidence", "tier", "products", "page_type"},
                    ...
                  ],
                },
                ...
              ],
            },
            ...
          ],
          "uncertain": {"count": int, "pages": [...]}
        }
    """
    from ..models import CrawlerPageResult

    pages_qs = (
        CrawlerPageResult.objects
        .filter(snapshot=snapshot, status_code="200")
        .only(
            "url", "title", "meta_description", "jsonld_types", "status_code",
        )
    )

    # Tree: product → page_type → [page_entry]
    tree: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    uncertain: list[dict] = []

    total_pages = 0
    classified = 0
    assignments = 0

    for page in pages_qs.iterator():
        total_pages += 1
        row = _row_from_page(page)
        result = classify_row(row)

        entry = {
            "url": page.url,
            "title": page.title or "",
            "confidence": result.get("page_type_confidence", 0.0),
            "tier": result.get("tier", 1),
            "products": [p["label"] for p in result.get("products", [])],
            "page_type": result.get("page_type", "other"),
        }

        is_uncertain = result.get("uncertain", False) or (
            not result.get("products") and result.get("page_type") == "other"
        )

        if is_uncertain:
            uncertain.append(entry)
            continue

        classified += 1
        page_type = result.get("page_type", "other")

        if mode == "multi" and result.get("products"):
            for prod in result["products"]:
                tree[prod["label"]][page_type].append(entry)
                assignments += 1
        else:
            primary = _primary_product(result.get("products", []))
            # Pages with a confident page_type but no product still
            # deserve a home — bucket under general_life.
            bucket = primary or "general_life"
            tree[bucket][page_type].append(entry)
            assignments += 1

    # Materialise tree in taxonomy order, with counts and stable sort.
    products_out: list[dict] = []
    for prod_key in PRODUCTS:
        if prod_key not in tree:
            continue
        pt_buckets = tree[prod_key]
        page_types_out: list[dict] = []
        for pt_key in PAGE_TYPES:
            entries = pt_buckets.get(pt_key)
            if not entries:
                continue
            # Stable sort: highest-confidence first, then title.
            entries.sort(key=lambda e: (-e["confidence"], e["title"]))
            page_types_out.append({
                "page_type": pt_key,
                "label": PAGE_TYPE_LABELS[pt_key],
                "count": len(entries),
                "pages": entries,
            })
        if not page_types_out:
            continue
        products_out.append({
            "product": prod_key,
            "label": PRODUCT_LABELS[prod_key],
            "count": sum(pt["count"] for pt in page_types_out),
            "page_types": page_types_out,
        })

    uncertain.sort(key=lambda e: e["url"])

    return {
        "snapshot_id": str(snapshot.id),
        "snapshot_date": snapshot.started_at.isoformat() if snapshot.started_at else "",
        "mode": mode,
        "totals": {
            "pages": total_pages,
            "classified": classified,
            "uncertain": len(uncertain),
            "assignments": assignments,
        },
        "products": products_out,
        "uncertain": {"count": len(uncertain), "pages": uncertain},
    }
