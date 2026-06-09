"""Content segregation & classification subsystem.

See docs/CONTENT_CLASSIFICATION_PLAN.md for the full design.

Rule-based classifier with zero paid-LLM and zero ML dependency:

  * Tier 1 — rules.py: URL + title + JSON-LD regex matchers.
             Handles ≈ 80% of pages at confidence ≥ 0.9.
  * Tier 2 — keyword_profiles.py: TF-IDF profiles built from
             Tier 1's confident output. Handles ≈ 15%.

(The former Tier-3 MiniLM embedding fallback was removed along with the
embedding/3D-content-map stack; callers degrade gracefully to Tier 1/2.)

Public entry point: ``pipeline.classify_row(row)``.
"""
