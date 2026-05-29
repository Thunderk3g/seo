"""Add ``prompt_instructions`` + ``competitor_matches`` to
ContentRewriteProposal for the new page-revamp endpoint.

The endpoint (``content_writer_revamp``) takes a single Bajaj URL plus
an optional free-text prompt, scans every competitor brand for a
counterpart page, and records the matches it found so the operator can
re-open a proposal later and see which competitors were compared.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("seo_ai", "0009_competitor_history"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentrewriteproposal",
            name="prompt_instructions",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="contentrewriteproposal",
            name="competitor_matches",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
