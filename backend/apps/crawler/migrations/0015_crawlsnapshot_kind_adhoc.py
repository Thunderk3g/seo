"""Add `adhoc` to CrawlSnapshot.Kind choices.

Pure metadata change — the underlying column is a plain CharField so no
SQL runs. Required so Django form/admin validation accepts the new
value the ad-hoc URL crawler writes.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crawler", "0014_crawlsnapshot_parent_domain"),
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
                ],
                default="bajaj",
                help_text=(
                    "bajaj for own-site crawls; competitor for rival domains."
                ),
                max_length=16,
            ),
        ),
    ]
