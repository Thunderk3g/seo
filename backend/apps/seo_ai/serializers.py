"""DRF serializers for the SEO AI run endpoints.

Shaped so the frontend's `/grade` page can render a run summary card,
a sub-score grid, a findings table, and the conversation viewer with
no further transformation.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import SEORun, SEORunFinding, SEORunMessage, SEORunToolCall


class SEORunFindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SEORunFinding
        fields = (
            "id",
            "agent",
            "severity",
            "category",
            "title",
            "description",
            "recommendation",
            "evidence_refs",
            "impact",
            "effort",
            "priority",
        )


class SEORunMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = SEORunMessage
        fields = (
            "id",
            "step_index",
            "from_agent",
            "to_agent",
            "role",
            "content",
            "tokens_in",
            "tokens_out",
            "cost_usd",
            "created_at",
        )


class SEORunToolCallSerializer(serializers.ModelSerializer):
    class Meta:
        model = SEORunToolCall
        fields = (
            "id",
            "agent",
            "tool_name",
            "args",
            "result",
            "latency_ms",
            "cached",
            "error",
            "created_at",
        )


class SEORunSerializer(serializers.ModelSerializer):
    findings_count = serializers.SerializerMethodField()

    class Meta:
        model = SEORun
        fields = (
            "id",
            "domain",
            "triggered_by",
            "status",
            "started_at",
            "finished_at",
            "overall_score",
            "sub_scores",
            "weights",
            "sources_snapshot",
            "model_versions",
            "total_cost_usd",
            "error",
            "findings_count",
        )

    def get_findings_count(self, obj: SEORun) -> int:
        return obj.findings.count()
