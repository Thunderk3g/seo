"""ContentWriterRun — persistence for the new SERP-discovery-driven
content_writer pipeline.
"""
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("seo_ai", "0011_revamp_cluster_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContentWriterRun",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("our_url", models.URLField(max_length=2048)),
                ("operator_prompt", models.TextField(blank=True, default="")),
                ("max_competitors", models.IntegerField(default=5)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("complete", "Complete"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("serp_discovery", models.JSONField(blank=True, default=dict)),
                ("our_page_analysis", models.JSONField(blank=True, default=dict)),
                ("competitor_analyses", models.JSONField(blank=True, default=list)),
                ("our_sections", models.JSONField(blank=True, default=dict)),
                ("competitor_sections", models.JSONField(blank=True, default=dict)),
                ("gap_report", models.JSONField(blank=True, default=dict)),
                ("seo_overlay", models.JSONField(blank=True, default=dict)),
                ("revamp", models.JSONField(blank=True, default=dict)),
                ("warnings", models.JSONField(blank=True, default=list)),
                ("telemetry", models.JSONField(blank=True, default=dict)),
                ("error", models.TextField(blank=True, default="")),
                ("model_used", models.CharField(blank=True, default="", max_length=128)),
                ("tokens_in", models.IntegerField(default=0)),
                ("tokens_out", models.IntegerField(default=0)),
                ("cost_usd", models.FloatField(default=0.0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(
                        fields=["-created_at"],
                        name="seo_ai_cont_created_352d1a_idx",
                    ),
                    models.Index(
                        fields=["our_url", "-created_at"],
                        name="seo_ai_cont_our_url_62b9a1_idx",
                    ),
                    models.Index(
                        fields=["status"],
                        name="seo_ai_cont_status_85527e_idx",
                    ),
                ],
            },
        ),
    ]
