"""Content segregation & classification subsystem.

See docs/CONTENT_CLASSIFICATION_PLAN.md for the full design.

Three-tier classifier with zero paid-LLM dependency:

  * Tier 1 — rules.py: URL + title + JSON-LD regex matchers.
             Handles ≈ 80% of pages at confidence ≥ 0.9.
  * Tier 2 — keyword_profiles.py: TF-IDF profiles built from
             Tier 1's confident output. Handles ≈ 15%.
  * Tier 3 — embedding_classifier.py: MiniLM cosine to seed pages.
             Handles ≈ 5%. Final fallback.

Public entry point: ``pipeline.classify_row(row)``.
"""
import os
from pathlib import Path


def _minilm_path() -> str:
    """Return the model identifier passed to SentenceTransformer.

    Resolution order:
      1. $MINILM_PATH env var
      2. /app/models/all-MiniLM-L6-v2 if present (mirror cached locally)
      3. HF hub id (will hit the network — fine in dev, blocked on Bajaj corp net)
    """
    env = os.environ.get("MINILM_PATH", "").strip()
    if env:
        return env
    local = Path("/app/models/all-MiniLM-L6-v2")
    if local.is_dir() and (local / "config.json").exists():
        return str(local)
    return "sentence-transformers/all-MiniLM-L6-v2"

