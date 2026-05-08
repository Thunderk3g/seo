"""Add cached AI insights columns to ``CrawlSession``.

Spec §4.3 / §4.4 / §6 step 5: AI insights are computed once at the end
of a crawl by ``IndexingIntelligenceAgent.run`` (via
:class:`InsightsService.regenerate`) and persisted on the session row so
opening the AIInsightsDrawer is a cheap DB read instead of a real-money
Anthropic round-trip. POST to ``/sessions/<id>/insights/`` forces a
regenerate and overwrites the cache.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crawl_sessions", "0005_export_binary_content"),
    ]

    operations = [
        migrations.AddField(
            model_name="crawlsession",
            name="ai_insights",
            field=models.JSONField(
                blank=True,
                default=None,
                null=True,
                help_text="Cached AI insights payload. Populated by IndexingIntelligenceAgent post-crawl.",
            ),
        ),
        migrations.AddField(
            model_name="crawlsession",
            name="ai_insights_generated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="crawlsession",
            name="ai_insights_model",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
