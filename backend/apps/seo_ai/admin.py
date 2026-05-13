from django.contrib import admin

from .models import SEORun, SEORunFinding, SEORunMessage, SEORunToolCall


@admin.register(SEORun)
class SEORunAdmin(admin.ModelAdmin):
    list_display = ("id", "domain", "status", "overall_score", "started_at", "finished_at")
    list_filter = ("status", "domain")
    readonly_fields = (
        "started_at",
        "finished_at",
        "overall_score",
        "sub_scores",
        "weights",
        "sources_snapshot",
        "model_versions",
        "total_cost_usd",
    )
    search_fields = ("id", "domain")


@admin.register(SEORunFinding)
class SEORunFindingAdmin(admin.ModelAdmin):
    list_display = ("title", "agent", "severity", "priority", "run")
    list_filter = ("severity", "agent")
    search_fields = ("title", "category")


@admin.register(SEORunMessage)
class SEORunMessageAdmin(admin.ModelAdmin):
    list_display = ("run", "step_index", "from_agent", "role", "cost_usd")
    list_filter = ("from_agent", "role")
    search_fields = ("run__id",)


@admin.register(SEORunToolCall)
class SEORunToolCallAdmin(admin.ModelAdmin):
    list_display = ("run", "agent", "tool_name", "latency_ms", "cached")
    list_filter = ("agent", "tool_name", "cached")
