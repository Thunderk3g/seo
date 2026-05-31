"""Backfill Core Web Vitals onto page rows from the PSI disk cache.

The PSIAdapter already fetched + cached ~4,680 PageSpeed results under
``data/_psi_cache`` (keyed sha1("{strategy}|{url}")), but those numbers
were never written onto the CrawlerPageResult rows — so the dashboard
shows no speed data. This command reconnects them.

CACHE-ONLY by design: it calls ``PSIAdapter._cache_read`` (a pure disk
read), NEVER ``fetch`` — so it makes ZERO live API calls and spends ZERO
quota. It only fills currently-empty CWV columns (additive; no overwrite
of real data, fully reversible).

Usage:
  python manage.py backfill_cwv_from_cache --dry-run
  python manage.py backfill_cwv_from_cache
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

# Numeric CWV metrics + categorical fields the PSI record carries.
_NUM_FIELDS = ("pagespeed_score", "lcp_ms", "cls", "inp_ms", "fcp_ms", "ttfb_ms", "tbt_ms", "si_ms")
_CAT_FIELDS = ("lcp_category", "cls_category", "inp_category", "has_field_data")
_STRATEGIES = ("mobile", "desktop")
# Legacy unprefixed columns the PageDetail UI reads (mobile mirror).
_LEGACY_MIRROR = ("pagespeed_score", "lcp_ms", "cls", "inp_ms")


class Command(BaseCommand):
    help = "Reconnect cached PageSpeed/CWV results onto page rows (cache-only, no API calls)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="Max pages to scan (0 = all).")
        parser.add_argument("--dry-run", action="store_true", help="Report without writing.")

    def handle(self, *args, **opts):
        from apps.crawler.models import CrawlerPageResult
        from apps.seo_ai.adapters.cwv_psi import AdapterDisabledError, PSIAdapter

        dry = bool(opts["dry_run"])
        try:
            psi = PSIAdapter()
        except AdapterDisabledError as exc:
            self.stderr.write(self.style.ERROR(f"PSI disabled: {exc}"))
            return

        qs = CrawlerPageResult.objects.filter(
            status_code="200", mobile_lcp_ms__isnull=True,
        )
        if opts["limit"]:
            qs = qs[: opts["limit"]]

        scanned = cache_hits = pages_written = 0
        for page in qs.iterator(chunk_size=500):
            scanned += 1
            changed_fields: set[str] = set()
            for strat in _STRATEGIES:
                try:
                    rec = psi._cache_read(page.url, strat)  # pure disk read
                except Exception:  # noqa: BLE001
                    rec = None
                if rec is None or getattr(rec, "error", None):
                    continue
                cache_hits += 1
                prefix = "mobile_" if strat == "mobile" else "desktop_"
                for fld in _NUM_FIELDS + _CAT_FIELDS:
                    val = getattr(rec, fld, None)
                    if val is not None:
                        setattr(page, f"{prefix}{fld}", val)
                        changed_fields.add(f"{prefix}{fld}")
                if strat == "mobile":
                    for fld in _LEGACY_MIRROR:
                        val = getattr(rec, fld, None)
                        if val is not None:
                            setattr(page, fld, val)
                            changed_fields.add(fld)
            if changed_fields:
                pages_written += 1
                if not dry:
                    try:
                        page.save(update_fields=list(changed_fields))
                    except Exception as exc:  # noqa: BLE001
                        self.stderr.write(f"save failed for {page.url}: {exc}")
            if scanned % 2000 == 0:
                self.stdout.write(f"  scanned {scanned} | cache_hits {cache_hits} | written {pages_written}")

        verb = "would write" if dry else "wrote"
        self.stdout.write(self.style.SUCCESS(
            f"backfill_cwv_from_cache done: scanned {scanned}, cache_hits {cache_hits}, {verb} {pages_written} pages"
        ))
