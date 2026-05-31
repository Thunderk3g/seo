"""Backfill Core Web Vitals onto page rows from the PSI disk cache.

The PSIAdapter cached thousands of PageSpeed results under data/_psi_cache
(keyed sha1("{strategy}|{url}")), but the numbers were never written onto
the CrawlerPageResult rows — so the dashboard shows no speed data.

IMPORTANT field-name fix: CWVRecord stores metrics as ``lab_lcp_ms`` /
``field_lcp_ms`` / ``performance_score`` (0..1), NOT ``lcp_ms`` /
``pagespeed_score``. The original psi_enrich write-back used the wrong
names and silently wrote nothing — this command maps them correctly
(prefer CrUX field data, fall back to Lighthouse lab).

CACHE-ONLY: calls ``PSIAdapter._cache_read`` (pure disk read) — ZERO live
API calls, ZERO quota. Additive (fills empty columns only), reversible.

Usage:
  python manage.py backfill_cwv_from_cache --dry-run
  python manage.py backfill_cwv_from_cache
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

_STRATEGIES = ("mobile", "desktop")
# Legacy unprefixed columns the PageDetail UI reads (mobile mirror).
_LEGACY_MIRROR = ("pagespeed_score", "lcp_ms", "cls", "inp_ms")


def _pick(*vals):
    for v in vals:
        if v is not None and v != "":
            return v
    return None


def _values_from_record(rec) -> dict:
    """Map a CWVRecord -> {page_column_suffix: value} for populated metrics.
    Prefers CrUX field data (real users), falls back to Lighthouse lab."""
    score = rec.performance_score
    out = {
        "lcp_ms": _pick(rec.field_lcp_ms, rec.lab_lcp_ms),
        "cls": _pick(rec.field_cls, rec.lab_cls),
        "inp_ms": rec.field_inp_ms,                       # INP is field-only
        "fcp_ms": _pick(rec.field_fcp_ms, rec.lab_fcp_ms),
        "ttfb_ms": _pick(rec.field_ttfb_ms, rec.lab_ttfb_ms),
        "tbt_ms": rec.lab_tbt_ms,                         # lab-only
        "si_ms": rec.lab_si_ms,                           # lab-only
        "pagespeed_score": round(score * 100) if score is not None else None,
        "lcp_category": rec.field_lcp_category or None,
        "cls_category": rec.field_cls_category or None,
        "inp_category": rec.field_inp_category or None,
        "has_field_data": rec.has_field_data,
    }
    return {k: v for k, v in out.items() if v is not None and v != ""}


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

        scanned = cache_hits = pages_written = lcp_written = 0
        for page in qs.iterator(chunk_size=500):
            scanned += 1
            changed: set[str] = set()
            for strat in _STRATEGIES:
                try:
                    rec = psi._cache_read(page.url, strat)
                except Exception:  # noqa: BLE001
                    rec = None
                if rec is None or getattr(rec, "error", None):
                    continue
                cache_hits += 1
                prefix = "mobile_" if strat == "mobile" else "desktop_"
                vals = _values_from_record(rec)
                for suffix, val in vals.items():
                    setattr(page, f"{prefix}{suffix}", val)
                    changed.add(f"{prefix}{suffix}")
                if strat == "mobile":
                    for fld in _LEGACY_MIRROR:
                        if fld in vals:
                            setattr(page, fld, vals[fld])
                            changed.add(fld)
                    if "lcp_ms" in vals:
                        lcp_written += 1
            if changed:
                pages_written += 1
                if not dry:
                    try:
                        page.save(update_fields=list(changed))
                    except Exception as exc:  # noqa: BLE001
                        self.stderr.write(f"save failed for {page.url}: {exc}")
            if scanned % 5000 == 0:
                self.stdout.write(f"  scanned {scanned} | cache_hits {cache_hits} | written {pages_written} | with_lcp {lcp_written}")

        verb = "would write" if dry else "wrote"
        self.stdout.write(self.style.SUCCESS(
            f"done: scanned {scanned}, cache_hits {cache_hits}, {verb} {pages_written} pages ({lcp_written} with real LCP)"
        ))
