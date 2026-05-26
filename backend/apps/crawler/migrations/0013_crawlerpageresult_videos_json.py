"""Add videos_json field to CrawlerPageResult.

Captures every <video> tag + YouTube/Vimeo <iframe> embed found on the
page. Same parity surface as headings/links/images so the competitor
detail page can render the full A/V structure for any URL.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crawler", "0012_crawlerpageresult_external_links_json_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="crawlerpageresult",
            name="videos_json",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
