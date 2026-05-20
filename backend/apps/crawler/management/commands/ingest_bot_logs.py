"""Ingest CDN access logs into the AIBotLog table.

Usage::

    python manage.py ingest_bot_logs
    python manage.py ingest_bot_logs --dir data/logs
    python manage.py ingest_bot_logs --host www.bajajlifeinsurance.com
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Parse CDN access logs in the configured log dir + persist verified AI-bot hits."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dir",
            type=str,
            default="",
            help="Override the log directory. Defaults to settings.AI_BOT_LOG_DIR or data/logs.",
        )
        parser.add_argument(
            "--host",
            type=str,
            default="www.bajajlifeinsurance.com",
            help="Host to prepend to each path so /foo becomes https://<host>/foo.",
        )

    def handle(self, *args, **options) -> None:
        from apps.crawler.adapters.bot_log_parser import ingest_dir

        log_dir_str = options.get("dir") or getattr(
            settings, "AI_BOT_LOG_DIR", None,
        )
        if not log_dir_str:
            log_dir_str = str(Path(settings.BASE_DIR) / "data" / "logs")
        log_dir = Path(log_dir_str)

        host = options.get("host") or "www.bajajlifeinsurance.com"

        self.stdout.write(self.style.NOTICE(
            f"Ingesting AI-bot hits from {log_dir} (host={host})..."
        ))
        result = ingest_dir(log_dir, host_for_url=host)
        if not result.get("ok"):
            self.stderr.write(self.style.ERROR(str(result)))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Inserted {result['inserted']:,} hits "
            f"(skipped {result['skipped_duplicate']:,} duplicates, "
            f"{result['spoofed_unverified']:,} unverified/spoofed)"
        ))
        for bot, count in result["per_bot"].items():
            self.stdout.write(f"  {bot}: {count:,}")
