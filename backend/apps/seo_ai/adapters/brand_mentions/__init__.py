"""Brand-mention adapter package.

Pulls third-party mentions of Bajaj brand variants from multiple
free sources (RSS, Reddit public JSON, Common Crawl text scan,
SerpAPI daily fallback), classifies them by source-tier and
brand-variant, sentiment-scores via Groq, and persists to
``apps.seo_ai.models.BrandMention``.

Designed free-first: SerpAPI is the only metered source and is
gated by a hard monthly cap (default 30 calls/mo, well under the
100-call free tier).

The orchestrator at ``apps.seo_ai.adapters.brand_mentions.run`` is
the single entry point — used by the management command, the
Celery scheduled job, and the manual "Refresh now" button in the
UI.
"""
from .orchestrator import run_brand_mentions_pull

__all__ = ["run_brand_mentions_pull"]
