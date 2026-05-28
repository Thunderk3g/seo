"""Add the SystemSetting key/value table.

Operator-tunable flags that need to persist across restarts but don't
justify their own model. First user: ``competitor_walk_paused`` so the
operator can pause the 03:00 IST cron from the dashboard without code
changes.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crawler", "0015_crawlsnapshot_kind_adhoc"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemSetting",
            fields=[
                (
                    "key",
                    models.CharField(max_length=128, primary_key=True, serialize=False),
                ),
                ("value", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("key",)},
        ),
    ]
