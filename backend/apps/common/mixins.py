"""Reusable model mixins for the SEO Intelligence Platform."""

import uuid
from django.db import models
from django.utils import timezone


class UUIDPrimaryKeyMixin(models.Model):
    """Mixin that provides a UUID primary key instead of auto-incrementing int."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimestampMixin(models.Model):
    """Mixin that adds created_at and updated_at timestamps."""
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
