"""Post-crawl PSI sweep — fill Core Web Vitals gaps left by the inline pass.

The inline PSI scheduler runs in parallel with the crawl and prefers fast
CrUX *field* data. Pages with no field data need a slow Lighthouse *lab*
run (~30 s on desktop), which the crawl often finishes before. This command
scores ONLY the HTML-200 pages that still have no CWV, sequentially, waiting
for each lab run — so coverage reaches ~100 % of crawlable pages.

Usage::

    python manage.py psi_sweep
    python manage.py psi_sweep --limit 200
    python manage.py psi_sweep --strategies mobile

Long-running: each no-field page needs a real lab render. Quota-billed like
``capture_psi`` (service-account project), well under the 25k/day limit.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.crawler.engine import psi_capture


class Command(BaseCommand):
    help = ("Score HTML-200 pages that still have no Core Web Vitals "
            "(waits for slow Lighthouse lab runs).")

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0,
                            help="Max gap pages to score (0 = all).")
        parser.add_argument(
            "--strategies", default="",
            help="Comma-sep strategies (mobile, desktop). Default: env.",
        )

    def handle(self, *_args, **opts):
        missing = psi_capture.select_missing_cwv_urls(limit=opts["limit"] or 0)
        if not missing:
            self.stdout.write(self.style.SUCCESS(
                "No HTML-200 pages are missing CWV — nothing to sweep."
            ))
            return

        strategies = None
        raw = (opts.get("strategies") or "").strip()
        if raw:
            strategies = tuple(s.strip().lower() for s in raw.split(",") if s.strip())

        self.stdout.write(self.style.NOTICE(
            f"Sweeping {len(missing)} page(s) missing CWV "
            f"(strategies={strategies or 'env default'}) — this waits for lab runs…"
        ))
        result = psi_capture.sweep_missing_cwv(limit=opts["limit"] or 0,
                                               strategies=strategies)
        if not result.get("ok"):
            self.stdout.write(self.style.ERROR(result.get("error", "Failed.")))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Sweep done — swept={result.get('swept', 0)} "
            f"rows_written={result.get('rows_written', 0)} "
            f"failed={result.get('failed', 0)}"
        ))
