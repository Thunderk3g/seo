# Hand-rolled migration for the Phase-3 gap-detection pipeline models.
# Schema mirrors the model definitions in apps.seo_ai.models exactly —
# regenerate with ``manage.py makemigrations seo_ai --name gap_pipeline``
# if you tweak field shapes; the table layout here was authored to
# match what makemigrations would have produced (Django 6.0).

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("seo_ai", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="GapPipelineRun",
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
                ("domain", models.CharField(max_length=255)),
                ("triggered_by", models.CharField(default="api", max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("complete", "Complete"),
                            ("degraded", "Degraded"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("query_count", models.IntegerField(default=0)),
                ("seed_keyword_count", models.IntegerField(default=0)),
                ("llm_provider_count", models.IntegerField(default=0)),
                ("llm_call_count", models.IntegerField(default=0)),
                ("llm_total_cost_usd", models.FloatField(default=0.0)),
                ("serp_engine_count", models.IntegerField(default=0)),
                ("serp_call_count", models.IntegerField(default=0)),
                ("competitor_count", models.IntegerField(default=0)),
                ("deep_crawl_pages", models.IntegerField(default=0)),
                ("stage_status", models.JSONField(blank=True, default=dict)),
                ("config_snapshot", models.JSONField(blank=True, default=dict)),
                ("error", models.TextField(blank=True, default="")),
            ],
            options={
                "ordering": ("-started_at",),
                "indexes": [
                    models.Index(
                        fields=["domain", "-started_at"],
                        name="gap_pipe_domain_idx",
                    ),
                    models.Index(
                        fields=["status"], name="gap_pipe_status_idx"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="GapPipelineQuery",
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
                ("query", models.CharField(max_length=512)),
                (
                    "intent",
                    models.CharField(default="informational", max_length=32),
                ),
                (
                    "rationale",
                    models.CharField(blank=True, default="", max_length=512),
                ),
                ("source_keywords", models.JSONField(blank=True, default=list)),
                ("order", models.IntegerField(default=0)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="queries",
                        to="seo_ai.gappipelinerun",
                    ),
                ),
            ],
            options={
                "ordering": ("run", "order"),
                "indexes": [
                    models.Index(
                        fields=["run", "order"], name="gap_pipe_q_run_idx"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="GapLLMResult",
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
                ("provider", models.CharField(max_length=32)),
                ("model", models.CharField(blank=True, default="", max_length=128)),
                ("answer_text", models.TextField(blank=True, default="")),
                ("cited_urls", models.JSONField(blank=True, default=list)),
                ("cited_domains", models.JSONField(blank=True, default=list)),
                ("mentions_our_brand", models.BooleanField(default=False)),
                ("web_search_used", models.BooleanField(default=False)),
                ("tokens_in", models.IntegerField(default=0)),
                ("tokens_out", models.IntegerField(default=0)),
                ("cost_usd", models.FloatField(default=0.0)),
                ("latency_ms", models.IntegerField(default=0)),
                ("cached", models.BooleanField(default=False)),
                ("error", models.TextField(blank=True, default="")),
                (
                    "query",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="llm_results",
                        to="seo_ai.gappipelinequery",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="llm_results",
                        to="seo_ai.gappipelinerun",
                    ),
                ),
            ],
            options={
                "ordering": ("run", "provider", "query_id"),
                "indexes": [
                    models.Index(
                        fields=["run", "provider"], name="gap_pipe_llm_run_idx"
                    ),
                    models.Index(
                        fields=["query"], name="gap_pipe_llm_q_idx"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="GapSerpResult",
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
                ("engine", models.CharField(max_length=32)),
                ("organic", models.JSONField(blank=True, default=list)),
                (
                    "featured_snippet",
                    models.JSONField(blank=True, default=dict, null=True),
                ),
                (
                    "ai_overview",
                    models.JSONField(blank=True, default=dict, null=True),
                ),
                ("people_also_ask", models.JSONField(blank=True, default=list)),
                ("related_searches", models.JSONField(blank=True, default=list)),
                ("our_position", models.IntegerField(blank=True, null=True)),
                ("cached", models.BooleanField(default=False)),
                ("latency_ms", models.IntegerField(default=0)),
                ("error", models.TextField(blank=True, default="")),
                (
                    "query",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="serp_results",
                        to="seo_ai.gappipelinequery",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="serp_results",
                        to="seo_ai.gappipelinerun",
                    ),
                ),
            ],
            options={
                "ordering": ("run", "engine", "query_id"),
                "indexes": [
                    models.Index(
                        fields=["run", "engine"], name="gap_pipe_serp_run_idx"
                    ),
                    models.Index(
                        fields=["query"], name="gap_pipe_serp_q_idx"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="GapCompetitor",
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
                ("domain", models.CharField(max_length=255)),
                ("rank", models.IntegerField()),
                ("score", models.FloatField(default=0.0)),
                ("llm_citation_count", models.IntegerField(default=0)),
                ("serp_appearance_count", models.IntegerField(default=0)),
                ("serp_top3_count", models.IntegerField(default=0)),
                ("featured_snippet_count", models.IntegerField(default=0)),
                ("ai_overview_citation_count", models.IntegerField(default=0)),
                (
                    "queries_appeared_for",
                    models.JSONField(blank=True, default=list),
                ),
                ("score_breakdown", models.JSONField(blank=True, default=dict)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="competitors",
                        to="seo_ai.gappipelinerun",
                    ),
                ),
            ],
            options={
                "ordering": ("run", "rank"),
                "indexes": [
                    models.Index(
                        fields=["run", "rank"], name="gap_pipe_comp_run_idx"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="GapDeepCrawl",
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
                ("domain", models.CharField(max_length=255)),
                ("is_us", models.BooleanField(default=False)),
                ("sitemap_url_count", models.IntegerField(default=0)),
                ("pages_attempted", models.IntegerField(default=0)),
                ("pages_ok", models.IntegerField(default=0)),
                ("profile", models.JSONField(blank=True, default=dict)),
                ("error", models.TextField(blank=True, default="")),
                (
                    "competitor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deep_crawl",
                        to="seo_ai.gapcompetitor",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deep_crawls",
                        to="seo_ai.gappipelinerun",
                    ),
                ),
            ],
            options={
                "ordering": ("run", "domain"),
                "indexes": [
                    models.Index(
                        fields=["run", "is_us"], name="gap_pipe_dc_run_idx"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="GapComparison",
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
                ("dimension", models.CharField(max_length=64)),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("critical", "Critical"),
                            ("warning", "Warning"),
                            ("notice", "Notice"),
                        ],
                        default="notice",
                        max_length=16,
                    ),
                ),
                ("headline", models.CharField(max_length=255)),
                ("our_value", models.JSONField(blank=True, default=dict)),
                ("competitor_median", models.JSONField(blank=True, default=dict)),
                ("delta", models.JSONField(blank=True, default=dict)),
                ("evidence", models.JSONField(blank=True, default=dict)),
                ("priority", models.IntegerField(default=50)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comparisons",
                        to="seo_ai.gappipelinerun",
                    ),
                ),
            ],
            options={
                "ordering": ("run", "-priority"),
                "indexes": [
                    models.Index(
                        fields=["run", "-priority"], name="gap_pipe_cmp_run_idx"
                    )
                ],
            },
        ),
    ]
