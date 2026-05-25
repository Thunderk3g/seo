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
