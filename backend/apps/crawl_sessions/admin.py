"""Admin interface for crawl session models."""

from django.contrib import admin
from apps.crawl_sessions.models import (
    CrawlSession,
    Page,
    Link,
    URLClassification,
    SitemapURL,
    StructuredData,
)


@admin.register(CrawlSession)
class CrawlSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "website", "session_type", "status",
        "started_at", "finished_at",
        "total_urls_discovered", "total_urls_crawled",
    )
    list_filter = ("session_type", "status", "website")
    search_fields = ("id", "website__domain")
    ordering = ("-started_at",)
    readonly_fields = ("error_summary",)


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = (
        "url", "http_status_code", "crawl_depth",
        "title", "word_count", "load_time_ms", "source",
    )
    list_filter = ("http_status_code", "crawl_depth", "source", "is_https")
    search_fields = ("url", "title")
    raw_id_fields = ("crawl_session",)


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = (
        "source_url", "target_url", "link_type",
        "anchor_text", "is_navigation",
    )
    list_filter = ("link_type", "is_navigation")
    search_fields = ("source_url", "target_url", "anchor_text")
    raw_id_fields = ("crawl_session",)


@admin.register(URLClassification)
class URLClassificationAdmin(admin.ModelAdmin):
    list_display = ("url", "classification", "reason")
    list_filter = ("classification",)
    search_fields = ("url",)
    raw_id_fields = ("crawl_session", "page")


@admin.register(SitemapURL)
class SitemapURLAdmin(admin.ModelAdmin):
    list_display = ("page_url", "sitemap_source", "lastmod", "priority")
    search_fields = ("page_url", "sitemap_source")
    raw_id_fields = ("crawl_session",)


@admin.register(StructuredData)
class StructuredDataAdmin(admin.ModelAdmin):
    list_display = ("page", "schema_type", "is_valid", "error_message")
    list_filter = ("schema_type", "is_valid")
    raw_id_fields = ("page",)
