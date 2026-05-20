"""A/B parity diff between legacy and Scrapy snapshots — Phase 3e.

Run after both engines have crawled the same site so you can validate
the Scrapy port produces the same URL set + same per-URL signals
within an acceptable delta (target: < 2% URL-count diff).

Usage::

    # Auto-pick latest of each engine:
    python manage.py crawl_ab_compare

    # Explicit snapshot IDs:
    python manage.py crawl_ab_compare --legacy <uuid> --scrapy <uuid>

    # Output a per-URL diff CSV (otherwise just the summary):
    python manage.py crawl_ab_compare --csv ab_diff.csv

Reports:

  * URL count delta (Scrapy vs Legacy)
  * Intersection size + % overlap
  * URLs Legacy-only / Scrapy-only (top 10 each by word_count)
  * Per-URL status_code mismatches in the intersection
  * Per-URL title differences
  * Playwright re-render count from Scrapy (Phase 3e signal)

The intent is to gate the Phase 3 cutover: once delta < 2% AND no
materially differing status codes, the operator can flip
``CRAWLER_ENGINE=scrapy`` in .env with confidence.
"""
from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Diff a legacy crawl snapshot against a Scrapy crawl snapshot."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--legacy",
            type=str,
            default="",
            help="CrawlSnapshot UUID for the legacy engine run. Defaults to most recent.",
        )
        parser.add_argument(
            "--scrapy",
            type=str,
            default="",
            help="CrawlSnapshot UUID for the Scrapy engine run. Defaults to most recent.",
        )
        parser.add_argument(
            "--csv",
            type=str,
            default="",
            help="Optional path to write a per-URL diff CSV. Omit for stdout summary only.",
        )
        parser.add_argument(
            "--top",
            type=int,
            default=10,
            help="How many examples to show in each diff bucket (default 10).",
        )

    def handle(self, *args, **options) -> None:
        from apps.crawler.models import CrawlSnapshot, CrawlerPageResult

        legacy_id = options.get("legacy") or self._latest(CrawlSnapshot.Engine.LEGACY)
        scrapy_id = options.get("scrapy") or self._latest(CrawlSnapshot.Engine.SCRAPY)

        if not legacy_id:
            raise SystemExit("No legacy CrawlSnapshot found. Run `python manage.py crawl` first.")
        if not scrapy_id:
            raise SystemExit(
                "No scrapy CrawlSnapshot found. Run `python manage.py crawl_scrapy --max-pages N` first."
            )

        legacy_snap = CrawlSnapshot.objects.get(pk=legacy_id)
        scrapy_snap = CrawlSnapshot.objects.get(pk=scrapy_id)

        self.stdout.write(self.style.NOTICE(
            f"Comparing:\n"
            f"  Legacy  {legacy_snap.id} (started {legacy_snap.started_at})\n"
            f"  Scrapy  {scrapy_snap.id} (started {scrapy_snap.started_at})\n"
        ))

        legacy_rows = {
            p.url: p for p in CrawlerPageResult.objects.filter(snapshot=legacy_snap)
            .only("url", "status_code", "title", "word_count",
                  "response_time_ms", "playwright_used")
        }
        scrapy_rows = {
            p.url: p for p in CrawlerPageResult.objects.filter(snapshot=scrapy_snap)
            .only("url", "status_code", "title", "word_count",
                  "response_time_ms", "playwright_used")
        }

        legacy_set = set(legacy_rows)
        scrapy_set = set(scrapy_rows)
        intersection = legacy_set & scrapy_set
        legacy_only = legacy_set - scrapy_set
        scrapy_only = scrapy_set - legacy_set

        n_l = len(legacy_set)
        n_s = len(scrapy_set)
        n_i = len(intersection)
        delta_pct = abs(n_s - n_l) / max(n_l, 1) * 100

        # Status mismatches inside the intersection.
        status_mismatches = []
        title_diffs = []
        wc_diffs = []
        for url in intersection:
            l = legacy_rows[url]
            s = scrapy_rows[url]
            if (l.status_code or "") != (s.status_code or ""):
                status_mismatches.append((url, l.status_code, s.status_code))
            if (l.title or "").strip() != (s.title or "").strip():
                title_diffs.append((url, l.title, s.title))
            if abs((l.word_count or 0) - (s.word_count or 0)) > 50:
                wc_diffs.append((url, l.word_count, s.word_count))

        playwright_used = sum(1 for p in scrapy_rows.values() if p.playwright_used)

        # ── Summary ──
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("URL set comparison"))
        self.stdout.write(f"  Legacy URL count    : {n_l:>7,}")
        self.stdout.write(f"  Scrapy URL count    : {n_s:>7,}")
        self.stdout.write(f"  Intersection        : {n_i:>7,}  ({n_i / max(n_l, 1) * 100:5.1f}% of legacy)")
        self.stdout.write(f"  Legacy only         : {len(legacy_only):>7,}")
        self.stdout.write(f"  Scrapy only         : {len(scrapy_only):>7,}")
        self.stdout.write(f"  URL count delta     : {delta_pct:>6.2f}%   "
                          f"(target <2.00% for cutover)")

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Per-URL signal differences in intersection"))
        self.stdout.write(f"  Status code mismatches : {len(status_mismatches):>5,}")
        self.stdout.write(f"  Title differences      : {len(title_diffs):>5,}")
        self.stdout.write(f"  Word count > 50 delta  : {len(wc_diffs):>5,}")

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Phase 3e JS rendering"))
        self.stdout.write(f"  Scrapy URLs rendered via Playwright : {playwright_used:>5,}")

        # ── Examples ──
        top = options.get("top") or 10
        self._dump_examples(
            "Legacy-only URLs (top by word_count desc)",
            sorted(legacy_only, key=lambda u: -(legacy_rows[u].word_count or 0))[:top],
            lambda u: f"{legacy_rows[u].word_count or 0:>6} words  {u[:110]}",
        )
        self._dump_examples(
            "Scrapy-only URLs (top by word_count desc)",
            sorted(scrapy_only, key=lambda u: -(scrapy_rows[u].word_count or 0))[:top],
            lambda u: f"{scrapy_rows[u].word_count or 0:>6} words  {u[:110]}",
        )
        self._dump_examples(
            "Status code mismatches",
            status_mismatches[:top],
            lambda t: f"  legacy={t[1] or '-':>3}  scrapy={t[2] or '-':>3}  {t[0][:90]}",
        )

        # ── Optional CSV ──
        if options.get("csv"):
            self._write_csv(options["csv"], legacy_rows, scrapy_rows, intersection,
                            legacy_only, scrapy_only, status_mismatches, title_diffs, wc_diffs)
            self.stdout.write(self.style.SUCCESS(f"\nPer-URL diff written to {options['csv']}"))

        # ── Verdict ──
        self.stdout.write("")
        passes = delta_pct < 2.0 and len(status_mismatches) < n_i * 0.01
        if passes:
            self.stdout.write(self.style.SUCCESS(
                "VERDICT: parity within tolerance — safe to flip CRAWLER_ENGINE=scrapy"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "VERDICT: parity NOT within tolerance — investigate before cutover"
            ))

    def _dump_examples(self, header: str, items: list, fmt) -> None:
        if not items:
            return
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO(header))
        for it in items:
            self.stdout.write("  " + fmt(it))

    def _latest(self, engine: str) -> str:
        from apps.crawler.models import CrawlSnapshot
        snap = (
            CrawlSnapshot.objects.filter(engine=engine)
            .order_by("-started_at")
            .first()
        )
        return str(snap.id) if snap else ""

    def _write_csv(self, path, legacy_rows, scrapy_rows, intersection,
                   legacy_only, scrapy_only, status_mismatches,
                   title_diffs, wc_diffs) -> None:
        import csv
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["url", "in_legacy", "in_scrapy",
                        "legacy_status", "scrapy_status",
                        "legacy_word_count", "scrapy_word_count",
                        "diff_type"])
            for url in legacy_only:
                l = legacy_rows[url]
                w.writerow([url, "yes", "no", l.status_code, "",
                            l.word_count or 0, "", "legacy_only"])
            for url in scrapy_only:
                s = scrapy_rows[url]
                w.writerow([url, "no", "yes", "", s.status_code,
                            "", s.word_count or 0, "scrapy_only"])
            mismatch_urls = {u for u, *_ in status_mismatches}
            for url in mismatch_urls:
                l = legacy_rows[url]; s = scrapy_rows[url]
                w.writerow([url, "yes", "yes", l.status_code, s.status_code,
                            l.word_count or 0, s.word_count or 0,
                            "status_mismatch"])
