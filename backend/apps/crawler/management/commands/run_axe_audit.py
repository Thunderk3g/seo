"""Run AXE color-contrast accessibility checks against crawled URLs.

AXE needs a real browser to compute color contrast, so it's slow
(~3-5s per URL). Rather than baking it into every crawl, this is a
separate management command the operator runs on demand:

    docker compose exec backend python manage.py run_axe_audit
    docker compose exec backend python manage.py run_axe_audit --limit 20
    docker compose exec backend python manage.py run_axe_audit --url https://...

Operator must set CRAWLER_AXE_ENABLED=true (env or one-shot) so
the helper doesn't silently no-op.

The command updates each CrawlerPageResult row with the
``color_contrast_*`` fields. The frontend Compliance dashboard then
surfaces them automatically because the audit catalog already
includes the Phase E ``color_contrast_failures`` detector.
"""
from __future__ import annotations

import os
import time

from django.core.management.base import BaseCommand

from ...audits.axe_runner import axe_color_contrast
from ...models import CrawlerPageResult, CrawlSnapshot


class Command(BaseCommand):
    help = "Run AXE color-contrast against crawled URLs (slow; opt-in)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Cap how many URLs to audit (0 = all 200-OK pages).",
        )
        parser.add_argument(
            "--url",
            type=str,
            default="",
            help="Audit a single URL instead of every page in the latest snapshot.",
        )

    def handle(self, *args, **options):
        # Force-enable for the lifetime of this command — otherwise the
        # helper short-circuits when the env hasn't been set globally.
        os.environ["CRAWLER_AXE_ENABLED"] = "true"

        if options.get("url"):
            urls = [options["url"]]
            self.stdout.write(self.style.NOTICE(
                f"Auditing single URL: {urls[0]}"
            ))
            self._audit_one(urls[0])
            return

        snap = CrawlSnapshot.objects.order_by("-started_at").first()
        if snap is None:
            self.stderr.write("No crawl snapshots in the database — run a crawl first.")
            return

        qs = (
            CrawlerPageResult.objects
            .filter(snapshot=snap, status_code="200")
            .order_by("url")
        )
        limit = options.get("limit") or 0
        if limit > 0:
            qs = qs[:limit]
        total = qs.count() if hasattr(qs, "count") else len(list(qs))

        self.stdout.write(self.style.NOTICE(
            f"Auditing {total} URLs from snapshot {snap.id} "
            f"({snap.started_at.isoformat() if snap.started_at else '—'})"
        ))

        started = time.time()
        ok = err = 0
        for i, page in enumerate(qs, start=1):
            t0 = time.time()
            result = axe_color_contrast(page.url)
            elapsed = time.time() - t0
            page.color_contrast_violations_count = int(
                result.get("color_contrast_violations_count") or 0
            )
            page.color_contrast_violations = result.get("color_contrast_violations") or []
            page.axe_tool_used = result.get("axe_tool_used") or ""
            page.save(update_fields=[
                "color_contrast_violations_count",
                "color_contrast_violations",
                "axe_tool_used",
            ])
            tool = result.get("axe_tool_used", "")
            cnt = result.get("color_contrast_violations_count", 0)
            if tool == "playwright+axe":
                ok += 1
            else:
                err += 1
            self.stdout.write(
                f"[{i}/{total}] {page.url} — "
                f"{cnt} violations, {elapsed:.1f}s ({tool or 'error'})"
            )

        total_elapsed = time.time() - started
        self.stdout.write(self.style.SUCCESS(
            f"Done. {ok} succeeded, {err} errored/skipped, "
            f"{total_elapsed:.1f}s total."
        ))

    def _audit_one(self, url: str) -> None:
        t0 = time.time()
        result = axe_color_contrast(url)
        elapsed = time.time() - t0
        self.stdout.write(self.style.SUCCESS(
            f"Tool: {result.get('axe_tool_used')}\n"
            f"Violations: {result.get('color_contrast_violations_count')}\n"
            f"Elapsed: {elapsed:.1f}s"
        ))
        for v in result.get("color_contrast_violations", []) or []:
            self.stdout.write(
                f"  - {v.get('selector')!r}  "
                f"ratio={v.get('ratio')} expected={v.get('expected')}  "
                f"fg={v.get('fg')} bg={v.get('bg')}  impact={v.get('impact')}"
            )
        if result.get("axe_error_message"):
            self.stdout.write(self.style.WARNING(
                f"Error: {result['axe_error_message']}"
            ))
