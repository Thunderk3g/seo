"""Upgrade `unknown` URLs to definitive verdicts via the GSC URL Inspection API.

Run after ``gsc_build_coverage`` to convert the 5,000+ "no signal" URLs
into real Google-confirmed states. Quota: ~2,000 inspections / day per
property, so for a full site rewrite this needs to run on 3 consecutive
days. The command is idempotent — already-inspected URLs are skipped
because their coverage row is no longer ``unknown``.

Usage::

    python manage.py gsc_inspect_unknowns
    python manage.py gsc_inspect_unknowns --site https://www.example.com/ --max 500
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.crawler.storage import gsc_coverage_builder as builder


class Command(BaseCommand):
    help = ("Upgrade `unknown` URLs to indexed / not_indexed / excluded via "
            "the GSC URL Inspection API.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--site", default="https://www.bajajlifeinsurance.com/",
            help="GSC property URL (default: %(default)s)",
        )
        parser.add_argument(
            "--max", type=int, default=1900,
            help="Max URLs to inspect this run (quota is ~2000/day; default: %(default)s)",
        )
        parser.add_argument(
            "--sleep", type=float, default=0.4,
            help="Seconds to sleep between calls (default: %(default)s)",
        )

    def handle(self, *_args, **opts):
        self.stdout.write(self.style.NOTICE(
            f"Inspecting up to {opts['max']} unknown URLs against {opts['site']}..."
        ))
        res = builder.upgrade_with_url_inspection(
            site_url=opts["site"],
            max_urls=opts["max"],
            sleep_between=opts["sleep"],
        )
        if not res.get("ok"):
            self.stdout.write(self.style.ERROR(res.get("error", "Failed.")))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Inspected: {res.get('inspected', 0)}  "
            f"Errors: {res.get('errors', 0)}  "
            f"Remaining unknown: {res.get('remaining', '?')}"
        ))
        bf = res.get("backfill") or {}
        if bf.get("files"):
            total = sum(f.get("updated", 0) for f in bf["files"].values())
            self.stdout.write(f"Updated indexed_status on {total} crawler rows.")
