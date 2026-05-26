

"""Tier 3 — Semantic similarity classifier using sentence-transformers.

For pages Tier 1 couldn't confidently classify, we compare the page's
visible text to a small set of hand-picked "seed" pages per product /
page-type. The new page inherits the label of the nearest seed (cosine
similarity) provided the similarity is above a threshold.

Uses sentence-transformers/all-MiniLM-L6-v2 — 384-dim embeddings, ~80 MB
model, runs on CPU, no API cost.

The seeds live in seeds/*.json — small lists of authoritative URLs +
short representative text per category. Updates are version-controlled.

When sentence-transformers is unavailable (CI without the package,
or import failure), Tier 3 returns no labels — Tier 1 results pass
through unchanged. Never breaks the pipeline.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .taxonomy import (
    PRODUCTS, PAGE_TYPES, CONFIDENCE_LOW, UNCERTAIN_THRESHOLD,
)


log = logging.getLogger(__name__)


# Module-level model cache (lazy-loaded, single instance per process)
_MODEL = None
_SEEDS_CACHE: dict | None = None
_SEEDS_EMBEDDINGS: dict | None = None


# Minimum cosine similarity to accept a seed-based label.
_MIN_COSINE = 0.40


def _load_model():
    """Lazy-load MiniLM. Returns None if sentence-transformers
    is unavailable — Tier 3 then becomes a no-op."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        from sentence_transformers import SentenceTransformer
        from . import _minilm_path
        _MODEL = SentenceTransformer(_minilm_path())
        return _MODEL
    except ImportError:
        log.info("sentence-transformers not installed; Tier 3 disabled")
        return None
    except Exception as exc:  # noqa: BLE001 — first-run download failures
        log.warning("MiniLM load failed: %s — Tier 3 disabled", exc)
        return None


def _seeds_dir() -> Path:
    return Path(__file__).parent / "seeds"


def _load_seeds() -> dict[str, list[str]]:
    """Load all seed files. Returns {category_key: [seed_text, ...]}.
    Category keys take the form `product:term`, `page_type:calculator`.
    """
    global _SEEDS_CACHE
    if _SEEDS_CACHE is not None:
        return _SEEDS_CACHE
    out: dict[str, list[str]] = {}
    seeds_root = _seeds_dir()
    if not seeds_root.is_dir():
        _SEEDS_CACHE = out
        return out
    for path in seeds_root.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            category = data.get("category", "")
            texts = [s.get("text", "") for s in data.get("seeds", []) if s.get("text")]
            if category and texts:
                out[category] = texts
        except (OSError, ValueError) as exc:
            log.warning("could not load seed file %s: %s", path, exc)
    _SEEDS_CACHE = out
    return out


def _embed_seeds() -> dict[str, Any] | None:
    """Embed every seed once at startup, cache numpy arrays in memory."""
    global _SEEDS_EMBEDDINGS
    if _SEEDS_EMBEDDINGS is not None:
        return _SEEDS_EMBEDDINGS
    model = _load_model()
    if model is None:
        return None
    seeds = _load_seeds()
    if not seeds:
        _SEEDS_EMBEDDINGS = {}
        return _SEEDS_EMBEDDINGS
    out: dict[str, Any] = {}
    for category, texts in seeds.items():
        vectors = model.encode(texts, normalize_embeddings=True)
        out[category] = vectors  # shape (n_seeds, 384)
    _SEEDS_EMBEDDINGS = out
    return out


def _cosine_max(query_vec, seed_matrix) -> float:
    """Max cosine between a single normalized query vector and the
    rows of a normalized seed matrix. Both are already L2-normed."""
    import numpy as np
    sims = seed_matrix @ query_vec   # (n_seeds,)
    return float(np.max(sims))


def classify_tier3(text: str) -> dict:
    """Classify a single page's visible text against the seed corpus.

    Returns the same shape as ClassificationResult.to_dict():
        {products: [{label, confidence}, ...], page_type, page_type_confidence,
         tier: 3, signals: [...], uncertain: bool}

    Returns the empty result (no labels) when MiniLM or seeds are
    unavailable — caller treats this as "tier 3 abstained."
    """
    empty = {
        "products": [],
        "page_type": "other",
        "page_type_confidence": 0.0,
        "tier": 3,
        "signals": [],
        "uncertain": True,
    }
    if not text or not text.strip():
        return empty
    model = _load_model()
    if model is None:
        return empty
    seed_embeddings = _embed_seeds()
    if not seed_embeddings:
        return empty

    # Truncate text — MiniLM has a 256-token window. Send the first
    # ~1500 chars which is roughly the first paragraph or two.
    query = model.encode([text[:1500]], normalize_embeddings=True)[0]

    product_scores: dict[str, float] = {}
    page_type_scores: dict[str, float] = {}
    signals: list[str] = []

    for category, seed_matrix in seed_embeddings.items():
        score = _cosine_max(query, seed_matrix)
        if score < _MIN_COSINE:
            continue
        if category.startswith("product:"):
            label = category.split(":", 1)[1]
            product_scores[label] = max(product_scores.get(label, 0), score)
            signals.append(f"tier3:product:{label}={score:.2f}")
        elif category.startswith("page_type:"):
            label = category.split(":", 1)[1]
            page_type_scores[label] = max(page_type_scores.get(label, 0), score)
            signals.append(f"tier3:page_type:{label}={score:.2f}")

    # Promote raw cosine into our confidence band. Cosine 0.4 → conf 0.60,
    # cosine 0.7 → conf 0.85. Caps at 0.85 (Tier 3 is never as confident
    # as Tier 1 with hard URL signals).
    def _conf(cos: float) -> float:
        return round(min(0.85, 0.50 + cos * 0.50), 3)

    products = [
        (p, _conf(s)) for p, s in product_scores.items()
        if _conf(s) >= UNCERTAIN_THRESHOLD
    ]
    products.sort(key=lambda x: -x[1])

    page_type = "other"
    pt_conf = 0.0
    if page_type_scores:
        best_pt, best_score = max(page_type_scores.items(), key=lambda x: x[1])
        if _conf(best_score) >= UNCERTAIN_THRESHOLD:
            page_type = best_pt
            pt_conf = _conf(best_score)

    return {
        "products": [{"label": p, "confidence": c} for p, c in products],
        "page_type": page_type,
        "page_type_confidence": pt_conf,
        "tier": 3,
        "signals": signals,
        "uncertain": (not products) and pt_conf < UNCERTAIN_THRESHOLD,
    }
