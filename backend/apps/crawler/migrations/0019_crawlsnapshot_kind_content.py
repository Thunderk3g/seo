"""Add `content` to CrawlSnapshot.Kind choices.

Own-site CONTENT crawls (competitor-walk machinery pointed at our own
domain, with body_text + zoned link/heading/image structure persisted)
get their own kind so they never pollute competitor lists or the
nightly technical-crawl (`bajaj`) consumers.

Choices live in Python; this migration only rewrites the field's
`choices` metadata — no data change, instant on Postgres.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crawler", "0018_delete_pageembedding"),
    ]

    operations = [
        migrations.AlterField(
            model_name="crawlsnapshot",
            name="kind",
            field=models.CharField(
                choices=[
                    ("bajaj", "Bajaj (own site)"),
                    ("competitor", "Competitor"),
                    ("adhoc", "Ad-hoc URL"),
                    ("content", "Content crawl (own site)"),
                ],
                default="bajaj",
                help_text="bajaj for own-site crawls; competitor for rival domains.",
                max_length=16,
            ),
        ),
    ]
