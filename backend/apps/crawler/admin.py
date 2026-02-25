"""Admin interface for crawler models."""

from django.contrib import admin
from apps.crawler.models import Website, CrawlConfig, RobotsRule


@admin.register(Website)
class WebsiteAdmin(admin.ModelAdmin):
    list_display = ("domain", "name", "is_active", "include_subdomains", "created_at")
    list_filter = ("is_active", "include_subdomains")
    search_fields = ("domain", "name")
    ordering = ("-created_at",)


@admin.register(CrawlConfig)
class CrawlConfigAdmin(admin.ModelAdmin):
    list_display = (
        "website", "max_depth", "max_urls_per_session",
        "concurrency", "request_delay", "enable_js_rendering",
        "respect_robots_txt",
    )
    list_filter = ("enable_js_rendering", "respect_robots_txt")
    search_fields = ("website__domain",)


@admin.register(RobotsRule)
class RobotsRuleAdmin(admin.ModelAdmin):
    list_display = ("website", "crawl_delay", "fetched_at")
    search_fields = ("website__domain",)
    readonly_fields = ("raw_content", "disallowed_paths", "allowed_paths", "sitemap_urls")
