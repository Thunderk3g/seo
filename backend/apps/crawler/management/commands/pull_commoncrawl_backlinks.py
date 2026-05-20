"""Pull one Common Crawl release into the Backlink table (dry-run by default)."""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Pull backlinks from a Common Crawl release (dry-run loads data/backlinks_seed.csv)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--release", type=str, default="manual")
        parser.add_argument("--live", action="store_true",
                            help="Live mode (not implemented yet).")

    def handle(self, *args, **options) -> None:
        from apps.crawler.adapters.commoncrawl_backlinks import pull_release
        result = pull_release(options["release"], dry_run=not options["live"])
        if not result.get("ok"):
            self.stderr.write(self.style.ERROR(str(result)))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Release {result.get('release_id')}: "
            f"inserted={result.get('inserted', 0)}, updated={result.get('updated', 0)}"
        ))
        if result.get("note"):
            self.stdout.write(self.style.NOTICE(result["note"]))
