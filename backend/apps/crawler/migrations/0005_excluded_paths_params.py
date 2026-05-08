# Hand-written migration: adds excluded_paths and excluded_params JSON fields
# to CrawlConfig. Storage only — engine enforcement is a follow-up. The
# previous migration in this app is 0001_initial; the 0002–0004 numbers are
# reserved for sibling apps but unused here, so we jump straight to 0005 to
# avoid colliding with any future renames in this app.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crawler', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='crawlconfig',
            name='excluded_paths',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "List of URL path prefixes to skip, e.g. ['/admin', '/private']. "
                    "Storage only — engine enforcement is a follow-up."
                ),
            ),
        ),
        migrations.AddField(
            model_name='crawlconfig',
            name='excluded_params',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "List of query-string keys to strip before deduplication, "
                    "e.g. ['utm_source', 'fbclid']."
                ),
            ),
        ),
    ]
