"""Persistence for SEO AI runs.

We store everything an auditor would need to reproduce a run: the
weight matrix at the time, the per-source data snapshot pointers, every
agent message, and every tool call. Storage cost is small compared to
the value of post-hoc explainability — particularly in a regulated
industry where "why did the model recommend X" must be answerable a
quarter later.

Schema choices:

- UUID primary keys so run IDs are URL-safe and never leak ordering.
- JSON columns (``JSONField``) for everything structured-but-variable.
  Postgres → jsonb under the hood; SQLite → TEXT with a JSON1 helper.
- ``related_name`` chosen for ergonomic ``run.findings.all()`` etc.
"""
from __future__ import annotations

import uuid

from django.db import models


class SEORunStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    CRITIC = "critic", "Critic"
    COMPLETE = "complete", "Complete"
    DEGRADED = "degraded", "Degraded"
    FAILED = "failed", "Failed"


class FindingSeverity(models.TextChoices):
    CRITICAL = "critical", "Critical"
    WARNING = "warning", "Warning"
    NOTICE = "notice", "Notice"


class SEORun(models.Model):
    """One end-to-end grading invocation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.CharField(max_length=255)
    triggered_by = models.CharField(max_length=64, default="api")
    status = models.CharField(
        max_length=16, choices=SEORunStatus.choices, default=SEORunStatus.PENDING
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    overall_score = models.FloatField(null=True, blank=True)
    sub_scores = models.JSONField(default=dict, blank=True)
    weights = models.JSONField(default=dict, blank=True)
    sources_snapshot = models.JSONField(default=dict, blank=True)
    model_versions = models.JSONField(default=dict, blank=True)
    total_cost_usd = models.FloatField(default=0.0)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-started_at",)
        indexes = [
            models.Index(fields=["domain", "-started_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - admin convenience
        return f"{self.domain} {self.id} {self.status}"


class SEORunFinding(models.Model):
    """One recommendation or issue produced by an agent."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        SEORun, on_delete=models.CASCADE, related_name="findings"
    )
    agent = models.CharField(max_length=64)
    severity = models.CharField(
        max_length=16, choices=FindingSeverity.choices
    )
    category = models.CharField(max_length=128)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    recommendation = models.TextField(blank=True, default="")
    evidence_refs = models.JSONField(default=list, blank=True)
    impact = models.CharField(max_length=16, default="medium")  # high/medium/low
    effort = models.CharField(max_length=16, default="medium")
    priority = models.IntegerField(default=50)  # 1–100

    class Meta:
        ordering = ("-priority",)
        indexes = [
            models.Index(fields=["run", "-priority"]),
            models.Index(fields=["agent"]),
            models.Index(fields=["severity"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"[{self.severity}] {self.title}"


class SEORunMessage(models.Model):
    """One agent-to-agent / agent-to-tool message. The audit trail."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        SEORun, on_delete=models.CASCADE, related_name="messages"
    )
    step_index = models.IntegerField()
    from_agent = models.CharField(max_length=64)
    to_agent = models.CharField(max_length=64, blank=True, default="")
    role = models.CharField(max_length=32)  # system|user|assistant|tool|critic
    content = models.JSONField(default=dict, blank=True)
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cost_usd = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("run", "step_index", "created_at")
        indexes = [
            models.Index(fields=["run", "step_index"]),
        ]


class SEORunToolCall(models.Model):
    """Every tool invocation. Replay reads this back instead of re-calling."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        SEORun, on_delete=models.CASCADE, related_name="tool_calls"
    )
    agent = models.CharField(max_length=64)
    tool_name = models.CharField(max_length=128)
    args = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    latency_ms = models.IntegerField(default=0)
    cached = models.BooleanField(default=False)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("run", "created_at")
        indexes = [
            models.Index(fields=["run", "agent"]),
        ]
