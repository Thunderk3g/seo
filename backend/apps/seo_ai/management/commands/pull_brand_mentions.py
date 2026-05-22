"""Pull brand mentions from configured sources.

Usage:
    python manage.py pull_brand_mentions                  # all sources
    python manage.py pull_brand_mentions --source rss
    python manage.py pull_brand_mentions --source serp
    python manage.py pull_brand_mentions --force-serpapi  # bypass monthly cap

Designed for both manual operator runs and Celery beat invocation.
Always prints a one-line summary at end so cron logs are useful.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.seo_ai.adapters.brand_mentions import run_brand_mentions_pull


class Command(BaseCommand):
    help = (
        "Pull brand mentions from RSS / SerpAPI / Common Crawl sources, "
        "classify + sentiment-score them, persist to BrandMention table."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            action="append",
            default=None,
            help=(
                "Source to pull from. Can be repeated. Choices: "
                "all (default) | rss | serp | cc (cc not yet wired)"
            ),
        )
        parser.add_argument(
            "--force-serpapi",
            action="store_true",
            help=(
                "Bypass the SerpAPI monthly cap. Use sparingly — each "
                "call burns one of the 100 free-tier requests/month."
            ),
        )

    def handle(self, *args, **options) -> None:
        sources = options.get("source") or ["all"]
        force_serpapi = bool(options.get("force_serpapi"))

        self.stdout.write(self.style.NOTICE(
            f"Pulling brand mentions — sources={sources} "
            f"force_serpapi={force_serpapi}"
        ))

        result = run_brand_mentions_pull(
            sources=sources,
            force_serpapi=force_serpapi,
        )

        # Per-source summary.
        for src in result.sources:
            line = (
                f"  {src.source:8s} fetched={src.fetched:5d}  "
                f"new={src.new:5d}  updated={src.updated:5d}"
            )
            if src.error:
                line += f"  ERROR: {src.error}"
            self.stdout.write(line)

        self.stdout.write(self.style.SUCCESS(
            f"Done — fetched={result.total_fetched} "
            f"new={result.total_new} updated={result.total_updated} "
            f"sentiment_scored={result.sentiment_scored}"
        ))
