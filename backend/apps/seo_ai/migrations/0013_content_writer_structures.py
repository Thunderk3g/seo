"""Add per-page structure payloads to ContentWriterRun.

``our_structure`` and ``competitor_structures`` hold the raw heading
outline + internal-link list + image list + LLM clusters that power the
UI "page structure" dropdowns. Old runs render with empty dropdowns —
no backfill needed.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("seo_ai", "0012_content_writer_run"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentwriterrun",
            name="our_structure",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="contentwriterrun",
            name="competitor_structures",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
