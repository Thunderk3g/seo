"""Capture real browser console output for already-crawled URLs.

Runs Playwright headless against a subset of pages (default: top 200
www HTTP-200 URLs from the last crawl) and writes any console messages,
page errors, or failed network requests into crawl_console_log.csv.

Usage::

    python manage.py capture_console
    python manage.py capture_console --limit 50 --subdomain www
    python manage.py capture_console --levels error,warning,log

Long-running — expect ~3 seconds per URL with networkidle waits.
For 200 URLs that's ~10 minutes. Run via ``docker exec -d`` if you
want it detached.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.crawler.engine import browser_console


class Command(BaseCommand):
    help = ("Run headless Chromium against crawled URLs to capture real "
            "console errors, page errors, and failed network requests.")

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200,
                            help="Max URLs to inspect (default: %(default)s)")
        parser.add_argument("--subdomain", default="www",
                            help="Filter URLs by subdomain (default: %(default)s)")
        parser.add_argument("--status", default="200",
                            help="Filter by HTTP status code (default: %(default)s)")
        parser.add_argument("--wait", type=int, default=1500,
                            help="ms to wait after DOMContentLoaded before capturing "
                                 "(lets JS settle). Default: %(default)s")
        parser.add_argument("--levels",
                            default="error,warning",
                            help="Comma-sep console levels to record. "
                                 "Default: error,warning. Use 'all' for everything.")

    def handle(self, *_args, **opts):
        levels = (("error", "warning", "info", "log", "debug")
                  if opts["levels"] == "all"
                  else tuple(x.strip() for x in opts["levels"].split(",")))
        urls = browser_console.select_target_urls(
            limit=opts["limit"],
            subdomain=opts["subdomain"],
            only_status=opts["status"],
        )
        if not urls:
            self.stdout.write(self.style.WARNING("No URLs match filter — run the crawler first."))
            return
        self.stdout.write(self.style.NOTICE(
            f"Inspecting {len(urls)} URL(s) with Playwright (levels={levels})"
        ))
        result = browser_console.capture(
            urls,
            wait_after_load_ms=opts["wait"],
            levels=levels,
        )
        if not result.get("ok"):
            self.stdout.write(self.style.ERROR(result.get("error", "Failed.")))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Done — inspected={result['urls_inspected']} "
            f"failed={result['failed']} rows_written={result['rows_written']}"
        ))
