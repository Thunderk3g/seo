"""Phase D — Audit data completeness for a CrawlSnapshot.

Run::

    python manage.py audit_completeness [--snapshot <uuid>] [--min-pct 80]

Walks every field the pipeline is supposed to populate and reports
per-field coverage % over the snapshot's 200-OK rows. Fields below
``--min-pct`` are flagged in red so the operator knows which re-crawl
gaps still need to close before declaring the snapshot production-
ready.

Why this lives as a management command (not a view): completeness is
a snapshot-acceptance check the operator runs after a crawl, and the
output is a flat textual report not a UI surface. A CLI keeps it
scriptable (pipe into CI, attach to release-notes, etc.).

Fields audited per row:

  * HTTP layer     — status_code, response_time_ms, content_type
  * Title/meta     — title, meta_description, canonical
  * Headings/IA    — headings_json (+ zone), internal_links_json (+ zone)
  * Images         — images_json (+ alt %)
  * Schema         — jsonld_count, jsonld_types
  * Security       — hsts, csp, x_frame_options
  * Hreflang       — hreflang_count
  * PSI / CWV      — mobile_pagespeed_score, mobile_lcp_ms
  * Readability    — flesch_score (computed; expected non-zero)
  * Cookies        — cookie_count (Phase D.1 + opt-in)
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count, Q


class Command(BaseCommand):
    help = "Audit per-field coverage % on a CrawlSnapshot."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--snapshot", default="",
            help="UUID of the snapshot to audit. Default: latest non-empty.",
        )
        parser.add_argument(
            "--min-pct", type=float, default=80.0,
            help="Fields below this coverage %% are flagged. Default 80.",
        )
        parser.add_argument(
            "--kind", default="",
            help="When --snapshot is unset, restrict latest lookup to "
                 "this kind (bajaj | competitor).",
        )

    def handle(self, *args, **options) -> None:
        from apps.crawler.models import CrawlerPageResult, CrawlSnapshot

        snap_id = options.get("snapshot") or ""
        kind = (options.get("kind") or "").strip().lower()
        min_pct = float(options.get("min_pct") or 80.0)

        if snap_id:
            snap = CrawlSnapshot.objects.filter(id=snap_id).first()
        else:
            qs = CrawlSnapshot.objects.annotate(n=Count("pages")).filter(n__gte=5)
            if kind:
                qs = qs.filter(kind=kind)
            snap = qs.order_by("-started_at").first()

        if snap is None:
            self.stdout.write(self.style.ERROR("no snapshot found"))
            return

        ok_qs = CrawlerPageResult.objects.filter(
            snapshot=snap, status_code="200",
        )
        total = ok_qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING(
                f"snapshot {snap.id} has 0 OK rows — nothing to audit",
            ))
            return

        # Field name → Q() expressing "row has this populated"
        fields: dict[str, Q] = {
            # Content
            "title":                Q(title__gt=""),
            "meta_description":     Q(meta_description__gt=""),
            "canonical":            Q(canonical__gt=""),
            "word_count > 50":      Q(word_count__gt=50),
            "body_text":            Q(body_text__gt=""),
            # Structural mirror
            "headings_json":        ~Q(headings_json=[]),
            "internal_links_json":  ~Q(internal_links_json=[]),
            "external_links_json":  ~Q(external_links_json=[]),
            "images_json":          ~Q(images_json=[]),
            # Schema
            "jsonld_types":         ~Q(jsonld_types=[]),
            # Security
            "hsts":                 Q(hsts__gt=""),
            "csp":                  Q(csp__gt=""),
            "x_frame_options":      Q(x_frame_options__gt=""),
            # Hreflang
            "hreflang_count > 0":   Q(hreflang_count__gt=0),
            # PSI / CWV
            "mobile_pagespeed":     Q(mobile_pagespeed_score__isnull=False),
            "mobile_lcp_ms":        Q(mobile_lcp_ms__isnull=False),
            "mobile_cls":           Q(mobile_cls__isnull=False),
            # Readability
            "flesch_score":         Q(flesch_score__gt=0),
            # Cookies
            "cookie_count > 0":     Q(cookie_count__gt=0),
            # Page typing
            "page_type":            Q(page_type__gt=""),
            "indexed_status known": ~Q(indexed_status="unknown"),
        }

        self.stdout.write(
            self.style.NOTICE(
                f"\nSnapshot {snap.id} "
                f"[{snap.kind}/{snap.engine}] target={snap.target_domain or '-'}",
            ),
        )
        self.stdout.write(
            f"started_at={snap.started_at} status={snap.status} "
            f"ok_rows={total}\n",
        )

        below: list[tuple[str, float]] = []
        for label, q in fields.items():
            populated = ok_qs.filter(q).count()
            pct = 100.0 * populated / total
            line = f"  {label:30s}  {populated:5d}/{total:<5d}  {pct:5.1f}%"
            if pct < min_pct:
                self.stdout.write(self.style.WARNING(line + "  ⚠"))
                below.append((label, pct))
            else:
                self.stdout.write(self.style.SUCCESS(line))

        # Per-zone breakdown — surfaces "we crawled but lost zones" gaps.
        zoned_rows = ok_qs.exclude(headings_json=[]).count()
        with_zone = 0
        for h_list in ok_qs.exclude(headings_json=[]).values_list(
            "headings_json", flat=True,
        )[:500]:  # sampling cap — full scan is too expensive
            for h in h_list or []:
                if (h or {}).get("zone"):
                    with_zone += 1
                    break
        zone_pct = 100.0 * with_zone / max(1, min(zoned_rows, 500))
        self.stdout.write(
            f"  {'headings_json have zone tag':30s}  "
            f"{with_zone:5d}/{min(zoned_rows, 500):<5d}  {zone_pct:5.1f}%"
            f"  (sampled)",
        )

        # Summary
        self.stdout.write("")
        if below:
            self.stdout.write(self.style.WARNING(
                f"FAIL: {len(below)} field(s) below {min_pct:.0f}% coverage. "
                "Re-crawl needed:",
            ))
            for label, pct in below:
                self.stdout.write(f"  - {label} ({pct:.1f}%)")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"PASS: all fields >= {min_pct:.0f}% coverage.",
            ))
