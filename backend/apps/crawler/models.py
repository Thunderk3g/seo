"""
Crawler models – metadata, configuration, and operational state.

These models define the crawler's own operational data:
- Website: The root domains being monitored
- RobotsRule: Cached robots.txt rules per domain
- CrawlConfig: Per-website crawl configuration (depth, limits, etc.)
"""

from django.db import models
from apps.common.mixins import UUIDPrimaryKeyMixin, TimestampMixin
from apps.common import constants


class Website(UUIDPrimaryKeyMixin, TimestampMixin):
    """Root domains monitored by the crawler.

    Each website is a top-level entity that crawl sessions
    and pages are scoped to.
    """
    domain = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Primary domain name (e.g. example.com)",
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Human-readable name for the website",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether the crawler should actively process this website",
    )
    include_subdomains = models.BooleanField(
        default=False,
        help_text="Whether to include subdomain crawling",
    )

    class Meta:
        db_table = "websites"
        ordering = ["-created_at"]
        verbose_name_plural = "websites"

    def __str__(self):
        return self.domain


class CrawlConfig(UUIDPrimaryKeyMixin, TimestampMixin):
    """Per-website crawl configuration and budget controls.

    Maps directly to Section 5.2 (Crawl Budget & Limits) of the
    Crawling Strategies spec and Section 20 (Design Principles) of
    the Web Crawler Engine spec.
    """
    website = models.OneToOneField(
        Website,
        on_delete=models.CASCADE,
        related_name="crawl_config",
    )
    max_depth = models.PositiveIntegerField(
        default=constants.DEFAULT_MAX_DEPTH,
        help_text="Maximum crawl depth (e.g., 7)",
    )
    max_urls_per_session = models.PositiveIntegerField(
        default=constants.DEFAULT_MAX_URLS_PER_SESSION,
        help_text="Hard cap on URLs per crawl session",
    )
    concurrency = models.PositiveIntegerField(
        default=constants.DEFAULT_CONCURRENCY,
        help_text="Max concurrent requests to this domain",
    )
    request_delay = models.FloatField(
        default=constants.DEFAULT_REQUEST_DELAY,
        help_text="Delay (seconds) between requests for politeness",
    )
    request_timeout = models.PositiveIntegerField(
        default=constants.DEFAULT_REQUEST_TIMEOUT,
        help_text="HTTP request timeout in seconds",
    )
    max_retries = models.PositiveIntegerField(
        default=constants.DEFAULT_MAX_RETRIES,
        help_text="Max retry attempts on failure",
    )
    enable_js_rendering = models.BooleanField(
        default=False,
        help_text="Use Playwright for JavaScript rendering",
    )
    respect_robots_txt = models.BooleanField(
        default=True,
        help_text="Whether to obey robots.txt rules",
    )
    custom_user_agent = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Optional custom User-Agent string",
    )
    excluded_paths = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of URL path prefixes to skip, e.g. ['/admin', '/private']. "
            "Storage only — engine enforcement is a follow-up."
        ),
    )
    excluded_params = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of query-string keys to strip before deduplication, "
            "e.g. ['utm_source', 'fbclid']."
        ),
    )

    class Meta:
        db_table = "crawl_configs"
        verbose_name = "Crawl Configuration"
        verbose_name_plural = "Crawl Configurations"

    def __str__(self):
        return f"Config for {self.website.domain}"

    @property
    def effective_user_agent(self) -> str:
        return self.custom_user_agent or constants.CRAWLER_USER_AGENT


class RobotsRule(UUIDPrimaryKeyMixin, TimestampMixin):
    """Cached robots.txt rules per domain.

    Fetched and parsed before any page requests as per
    Section 6 (Robots.txt Handling) of the Web Crawler Engine spec.
    """
    website = models.OneToOneField(
        Website,
        on_delete=models.CASCADE,
        related_name="robots_rule",
    )
    raw_content = models.TextField(
        blank=True,
        default="",
        help_text="Raw robots.txt file content",
    )
    disallowed_paths = models.JSONField(
        default=list,
        help_text="List of disallowed paths extracted from robots.txt",
    )
    allowed_paths = models.JSONField(
        default=list,
        help_text="List of explicitly allowed paths",
    )
    crawl_delay = models.FloatField(
        null=True,
        blank=True,
        help_text="Crawl-delay directive value (seconds)",
    )
    sitemap_urls = models.JSONField(
        default=list,
        help_text="Sitemap URLs discovered from robots.txt",
    )
    fetched_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of last robots.txt fetch",
    )

    class Meta:
        db_table = "robots_rules"
        verbose_name = "Robots.txt Rule"
        verbose_name_plural = "Robots.txt Rules"

    def __str__(self):
        return f"Robots for {self.website.domain}"

    def is_allowed(self, path: str) -> bool:
        """Check if a given URL path is allowed by robots.txt rules.

        Checks allowed paths first (higher specificity), then disallowed.
        """
        # Explicitly allowed paths take precedence
        for allowed in self.allowed_paths:
            if path.startswith(allowed):
                return True
        # Check disallowed paths
        for disallowed in self.disallowed_paths:
            if path.startswith(disallowed):
                return False
        return True
