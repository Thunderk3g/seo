"""Persist orchestrator outputs (our_sections, their_sections, gap) on
ContentRewriteProposal so re-opening a past proposal renders the Gap
Panel + Section Comparison without re-running the LLM clusterer.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("seo_ai", "0010_revamp_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentrewriteproposal",
            name="our_sections",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="contentrewriteproposal",
            name="their_sections",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="contentrewriteproposal",
            name="gap",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
