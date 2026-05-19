"""Capture PageSpeed Insights metrics for already-crawled URLs.

Runs Google's PSI API against a subset of pages (default: top 100 www
HTTP-200 URLs from the last crawl) and writes one row per (url,
strategy) into ``crawl_psi.csv``. Captures both lab (Lighthouse) and
field (CrUX p75 real-user) metrics — LCP / CLS / INP / FCP / TBT / TTFB.

Usage::

    python manage.py capture_psi
    python manage.py capture_psi --limit 50 --strategies mobile
    python manage.py capture_psi --strategies mobile,desktop

Long-running — mobile ~2 s per URL, desktop ~30 s. With both strategies
and 100 URLs expect ~30-50 minutes. Free PSI quota is 25k/day; this
command bills against the service-account project (geoseo-496810 in
the default .env), not the shared anonymous pool.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.crawler.engine import psi_capture


class Command(BaseCommand):
    help = ("Call Google PageSpeed Insights on crawled URLs and stream "
            "lab + field Core Web Vitals into crawl_psi.csv.")

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100,
                            help="Max URLs to score (default: %(default)s)")
        parser.add_argument("--subdomain", default="www",
                            help="Filter URLs by subdomain (default: %(default)s)")
        parser.add_argument("--status", default="200",
                            help="Filter by HTTP status code (default: %(default)s)")
        parser.add_argument(
            "--strategies",
            default="",
            help="Comma-sep strategies (mobile, desktop). Default: read "
                 "PSI_STRATEGIES from .env (mobile,desktop).",
        )

    def handle(self, *_args, **opts):
        urls = psi_capture.select_target_urls(
            limit=opts["limit"],
            subdomain=opts["subdomain"],
            only_status=opts["status"],
        )
        if not urls:
            self.stdout.write(self.style.WARNING(
                "No URLs match filter — run the crawler first."
            ))
            return

        strategies = None
        raw = (opts.get("strategies") or "").strip()
        if raw:
            strategies = tuple(
                s.strip().lower() for s in raw.split(",") if s.strip()
            )

        self.stdout.write(self.style.NOTICE(
            f"Scoring {len(urls)} URL(s) via PSI "
            f"(strategies={strategies or 'env default'})"
        ))
        result = psi_capture.capture(urls, strategies=strategies)
        if not result.get("ok"):
            self.stdout.write(self.style.ERROR(result.get("error", "Failed.")))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Done — urls={result['urls_inspected']} "
            f"strategies={result['strategies']} "
            f"failed={result['failed']} rows_written={result['rows_written']}"
        ))
