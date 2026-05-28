"""Add parent_domain to CrawlSnapshot + backfill from target_domain.

Denormalized registrable apex of target_domain. The Crawled-competitors
table groups rows by this so subdomains like `auth.hdfclife.com` collapse
under their parent `hdfclife.com`. Computed via apps.crawler.util.host.apex
(tldextract against the bundled PSL snapshot).

Backfill runs over every existing row in one pass. tldextract is cheap
(~10 µs per call) so even a ~10k-row table finishes in <100 ms.
"""
from django.db import migrations, models


def _backfill_parent_domain(apps, _schema_editor):
    CrawlSnapshot = apps.get_model("crawler", "CrawlSnapshot")
    # Import lazily so collectstatic/etc. don't import tldextract.
    from apps.crawler.util.host import apex

    to_update = []
    for row in CrawlSnapshot.objects.only("id", "target_domain").iterator():
        new_parent = apex(row.target_domain or "")
        if new_parent and new_parent != getattr(row, "parent_domain", ""):
            row.parent_domain = new_parent
            to_update.append(row)
    if to_update:
        CrawlSnapshot.objects.bulk_update(to_update, ["parent_domain"], batch_size=500)


def _noop_reverse(_apps, _schema_editor):
    # parent_domain is dropped by the schema reverse; backfill data
    # disappears with it. Nothing to undo here.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("crawler", "0013_crawlerpageresult_videos_json"),
    ]

    operations = [
        migrations.AddField(
            model_name="crawlsnapshot",
            name="parent_domain",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=255,
                help_text="Registrable apex of target_domain — set automatically.",
            ),
        ),
        migrations.RunPython(_backfill_parent_domain, _noop_reverse),
    ]
