"""API serializers for crawler and crawl session models."""

from rest_framework import serializers

from apps.crawler.models import Website, CrawlConfig
from apps.crawl_sessions.models import (
    CrawlSession,
    CrawlEvent,
    Page,
    Link,
    URLClassification,
    SitemapURL,
)


# ─────────────────────────────────────────────────────────────
# Website Serializers
# ─────────────────────────────────────────────────────────────

class CrawlConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = CrawlConfig
        fields = [
            "max_depth", "max_urls_per_session", "concurrency",
            "request_delay", "request_timeout", "max_retries",
            "enable_js_rendering", "respect_robots_txt",
            "custom_user_agent",
        ]


class WebsiteSerializer(serializers.ModelSerializer):
    crawl_config = CrawlConfigSerializer(read_only=True)

    class Meta:
        model = Website
        fields = [
            "id", "domain", "name", "is_active",
            "include_subdomains", "crawl_config",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class WebsiteCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new website with optional config.

    `id` and `created_at` are read-only (server-assigned) but are returned in
    the 201 response body so the frontend can promote the new site to the
    active selection without a follow-up GET.
    """
    max_depth = serializers.IntegerField(required=False, default=7, write_only=True)
    max_urls_per_session = serializers.IntegerField(required=False, default=50000, write_only=True)
    concurrency = serializers.IntegerField(required=False, default=10, write_only=True)

    class Meta:
        model = Website
        fields = [
            "id", "domain", "name", "is_active", "include_subdomains",
            "max_depth", "max_urls_per_session", "concurrency",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_domain(self, value):
        """Normalise the user-supplied domain and store the bare host.

        Defends against the duplicated-scheme bug (e.g. ``https://https://x.com``)
        that previously caused the crawler to construct invalid URLs.
        """
        from apps.common.url_utils import normalize_seed_url
        from urllib.parse import urlsplit

        try:
            normalized = normalize_seed_url(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        return urlsplit(normalized).netloc.lower()

    def create(self, validated_data):
        config_data = {
            "max_depth": validated_data.pop("max_depth", 7),
            "max_urls_per_session": validated_data.pop("max_urls_per_session", 50000),
            "concurrency": validated_data.pop("concurrency", 10),
        }
        website = Website.objects.create(**validated_data)
        CrawlConfig.objects.create(website=website, **config_data)
        return website


# ─────────────────────────────────────────────────────────────
# Crawl Session Serializers
# ─────────────────────────────────────────────────────────────

class CrawlSessionListSerializer(serializers.ModelSerializer):
    website_domain = serializers.CharField(source="website.domain", read_only=True)
    duration_seconds = serializers.FloatField(read_only=True)

    class Meta:
        model = CrawlSession
        fields = [
            "id", "website", "website_domain", "session_type",
            "status", "started_at", "finished_at", "duration_seconds",
            "total_urls_discovered", "total_urls_crawled",
            "total_urls_failed", "max_depth_reached",
            "avg_response_time_ms",
        ]


class CrawlSessionDetailSerializer(serializers.ModelSerializer):
    website_domain = serializers.CharField(source="website.domain", read_only=True)
    duration_seconds = serializers.FloatField(read_only=True)

    class Meta:
        model = CrawlSession
        fields = [
            "id", "website", "website_domain", "session_type",
            "status", "started_at", "finished_at", "duration_seconds",
            "total_urls_discovered", "total_urls_crawled",
            "total_urls_failed", "total_urls_skipped",
            "max_depth_reached", "avg_response_time_ms",
            "error_summary", "target_url", "target_path_prefix",
            "created_at", "updated_at",
        ]


# ─────────────────────────────────────────────────────────────
# Page Serializers
# ─────────────────────────────────────────────────────────────

class PageListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Page
        fields = [
            "id", "url", "http_status_code", "title",
            "crawl_depth", "load_time_ms", "word_count",
            "source", "is_https",
        ]


class PageDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Page
        fields = [
            "id", "url", "normalized_url", "http_status_code",
            "final_url", "redirect_chain",
            "title", "meta_description", "h1", "h2_list", "h3_list",
            "canonical_url", "robots_meta",
            "crawl_depth", "load_time_ms", "content_size_bytes",
            "word_count", "is_https", "page_hash", "source",
            "total_images", "images_without_alt",
            "crawl_timestamp",
        ]


# ─────────────────────────────────────────────────────────────
# Link & Classification Serializers
# ─────────────────────────────────────────────────────────────

class LinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Link
        fields = [
            "source_url", "target_url", "link_type",
            "anchor_text", "rel_attributes", "is_navigation",
        ]


class URLClassificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = URLClassification
        fields = ["url", "classification", "reason", "classified_at"]


# ─────────────────────────────────────────────────────────────
# Activity Feed Serializer
# ─────────────────────────────────────────────────────────────

class CrawlEventSerializer(serializers.ModelSerializer):
    """Activity-feed entry. Persisted CrawlEvent rows use this directly;
    synthesized per-URL events from the Page table use the same shape."""

    class Meta:
        model = CrawlEvent
        fields = ["id", "timestamp", "kind", "url", "message", "metadata"]


# ─────────────────────────────────────────────────────────────
# Request Serializers (for API actions)
# ─────────────────────────────────────────────────────────────

class StartCrawlSerializer(serializers.Serializer):
    """Serializer for triggering an on-demand crawl."""
    website_id = serializers.UUIDField()
    target_path_prefix = serializers.CharField(
        required=False, default="", allow_blank=True,
    )


class URLInspectionSerializer(serializers.Serializer):
    """Serializer for triggering a URL inspection."""
    website_id = serializers.UUIDField()
    target_url = serializers.URLField()
