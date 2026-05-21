"""Schema additions to make CrawlSnapshot + CrawlerPageResult reusable
for competitor crawls.

* CrawlSnapshot gains ``kind`` (bajaj vs competitor) + ``target_domain``
  so per-domain Health Score lookups are O(index).
* CrawlSnapshot.Engine adds ``scrapy_competitor`` so the existing
  legacy / scrapy choices stay readable in admin.
* CrawlerPageResult gains ``body_text`` (full visible text) plus three
  small structural columns (``meta_description``, ``canonical``,
  ``meta_robots``) that the competitor spider extracts. Bajaj rows
  leave these empty — they're additive, never required.

Indexes:
  * (kind, target_domain, -started_at) on CrawlSnapshot — drives the
    "latest snapshot for competitor X" lookup behind the per-competitor
    Health Score endpoint.

Backfill: no — existing CrawlSnapshot rows default to kind='bajaj' and
target_domain='' (derived later by snapshot_service if needed).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crawler", "0003_aibotlog_backlink"),
    ]

    operations = [
        migrations.AddField(
            model_name="crawlsnapshot",
            name="kind",
            field=models.CharField(
                choices=[("bajaj", "Bajaj (own site)"), ("competitor", "Competitor")],
                default="bajaj",
                max_length=16,
                help_text=(
                    "bajaj for own-site crawls; competitor for rival domains."
                ),
            ),
        ),
        migrations.AddField(
            model_name="crawlsnapshot",
            name="target_domain",
            field=models.CharField(
                blank=True,
                default="",
                max_length=255,
                help_text=(
                    "Primary host being crawled — equals urlparse(seed_url)."
                    "netloc for Bajaj, and the competitor's apex domain "
                    "for competitor crawls. Indexed for per-domain "
                    "Health Score lookups."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="crawlsnapshot",
            name="engine",
            field=models.CharField(
                choices=[
                    ("legacy", "Legacy BFS engine"),
                    ("scrapy", "Scrapy spider"),
                    ("scrapy_competitor", "Scrapy competitor spider"),
                ],
                default="legacy",
                max_length=24,
            ),
        ),
        migrations.AddIndex(
            model_name="crawlsnapshot",
            index=models.Index(
                fields=["kind", "target_domain", "-started_at"],
                name="crawler_cra_kind_b9975c_idx",
            ),
        ),
        migrations.AddField(
            model_name="crawlerpageresult",
            name="body_text",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="crawlerpageresult",
            name="meta_description",
            field=models.CharField(blank=True, default="", max_length=1024),
        ),
        migrations.AddField(
            model_name="crawlerpageresult",
            name="canonical",
            field=models.CharField(blank=True, default="", max_length=2048),
        ),
        migrations.AddField(
            model_name="crawlerpageresult",
            name="meta_robots",
            field=models.CharField(blank=True, default="", max_length=256),
        ),
    ]
