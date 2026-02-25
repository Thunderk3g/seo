"""Shared system constants for the SEO Intelligence Platform."""

# ─────────────────────────────────────────────────────────────
# Crawl Session Types
# ─────────────────────────────────────────────────────────────
SESSION_TYPE_SCHEDULED = "scheduled"
SESSION_TYPE_ON_DEMAND = "on_demand"
SESSION_TYPE_URL_INSPECTION = "url_inspection"

SESSION_TYPE_CHOICES = [
    (SESSION_TYPE_SCHEDULED, "Scheduled"),
    (SESSION_TYPE_ON_DEMAND, "On-Demand"),
    (SESSION_TYPE_URL_INSPECTION, "URL Inspection"),
]

# ─────────────────────────────────────────────────────────────
# Crawl Session Status
# ─────────────────────────────────────────────────────────────
SESSION_STATUS_PENDING = "pending"
SESSION_STATUS_RUNNING = "running"
SESSION_STATUS_COMPLETED = "completed"
SESSION_STATUS_FAILED = "failed"
SESSION_STATUS_CANCELLED = "cancelled"

SESSION_STATUS_CHOICES = [
    (SESSION_STATUS_PENDING, "Pending"),
    (SESSION_STATUS_RUNNING, "Running"),
    (SESSION_STATUS_COMPLETED, "Completed"),
    (SESSION_STATUS_FAILED, "Failed"),
    (SESSION_STATUS_CANCELLED, "Cancelled"),
]

# ─────────────────────────────────────────────────────────────
# URL Frontier / Queue Status
# ─────────────────────────────────────────────────────────────
URL_STATUS_PENDING = "pending"
URL_STATUS_CRAWLING = "crawling"
URL_STATUS_CRAWLED = "crawled"
URL_STATUS_FAILED = "failed"
URL_STATUS_SKIPPED = "skipped"
URL_STATUS_BLOCKED = "blocked"

URL_STATUS_CHOICES = [
    (URL_STATUS_PENDING, "Pending"),
    (URL_STATUS_CRAWLING, "Crawling"),
    (URL_STATUS_CRAWLED, "Crawled"),
    (URL_STATUS_FAILED, "Failed"),
    (URL_STATUS_SKIPPED, "Skipped"),
    (URL_STATUS_BLOCKED, "Blocked by robots.txt"),
]

# ─────────────────────────────────────────────────────────────
# Link Types
# ─────────────────────────────────────────────────────────────
LINK_TYPE_INTERNAL = "internal"
LINK_TYPE_EXTERNAL = "external"
LINK_TYPE_MEDIA = "media"
LINK_TYPE_RESOURCE = "resource"

LINK_TYPE_CHOICES = [
    (LINK_TYPE_INTERNAL, "Internal"),
    (LINK_TYPE_EXTERNAL, "External"),
    (LINK_TYPE_MEDIA, "Media"),
    (LINK_TYPE_RESOURCE, "Resource"),
]

# ─────────────────────────────────────────────────────────────
# URL Discovery Source
# ─────────────────────────────────────────────────────────────
SOURCE_SEED = "seed"
SOURCE_SITEMAP = "sitemap"
SOURCE_LINK = "link"
SOURCE_CANONICAL = "canonical"
SOURCE_REDIRECT = "redirect"
SOURCE_MANUAL = "manual"

SOURCE_CHOICES = [
    (SOURCE_SEED, "Seed URL"),
    (SOURCE_SITEMAP, "Sitemap"),
    (SOURCE_LINK, "Discovered Link"),
    (SOURCE_CANONICAL, "Canonical Tag"),
    (SOURCE_REDIRECT, "Redirect Target"),
    (SOURCE_MANUAL, "Manual Entry"),
]

# ─────────────────────────────────────────────────────────────
# URL Classification (GSC-style coverage buckets)
# ─────────────────────────────────────────────────────────────
CLASSIFICATION_INDEXED = "indexed_candidate"
CLASSIFICATION_CRAWLED_NOT_INDEXED = "crawled_not_indexed"
CLASSIFICATION_DISCOVERED_NOT_CRAWLED = "discovered_not_crawled"
CLASSIFICATION_REDIRECTED = "redirected"
CLASSIFICATION_NOT_FOUND = "not_found_404"
CLASSIFICATION_SOFT_404 = "soft_404"
CLASSIFICATION_DUPLICATE_NO_CANONICAL = "duplicate_without_canonical"
CLASSIFICATION_ALTERNATE_CANONICAL = "alternate_with_canonical"
CLASSIFICATION_NOINDEX = "excluded_noindex"
CLASSIFICATION_BLOCKED_ROBOTS = "blocked_by_robots"
CLASSIFICATION_SERVER_ERROR = "server_error_5xx"

CLASSIFICATION_CHOICES = [
    (CLASSIFICATION_INDEXED, "Indexed Candidate"),
    (CLASSIFICATION_CRAWLED_NOT_INDEXED, "Crawled – Not Indexed"),
    (CLASSIFICATION_DISCOVERED_NOT_CRAWLED, "Discovered – Not Crawled"),
    (CLASSIFICATION_REDIRECTED, "Redirected Page"),
    (CLASSIFICATION_NOT_FOUND, "Not Found (404)"),
    (CLASSIFICATION_SOFT_404, "Soft 404"),
    (CLASSIFICATION_DUPLICATE_NO_CANONICAL, "Duplicate without Canonical"),
    (CLASSIFICATION_ALTERNATE_CANONICAL, "Alternate with Proper Canonical"),
    (CLASSIFICATION_NOINDEX, "Excluded by Noindex"),
    (CLASSIFICATION_BLOCKED_ROBOTS, "Blocked by Robots"),
    (CLASSIFICATION_SERVER_ERROR, "Server Error (5xx)"),
]

# ─────────────────────────────────────────────────────────────
# Crawl Budget & Limits (Defaults)
# ─────────────────────────────────────────────────────────────
DEFAULT_MAX_DEPTH = 7
DEFAULT_MAX_URLS_PER_SESSION = 50_000
DEFAULT_CONCURRENCY = 10
DEFAULT_REQUEST_DELAY = 1.0          # seconds between requests to same domain
DEFAULT_REQUEST_TIMEOUT = 30         # seconds
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 2.0         # exponential backoff multiplier

# ─────────────────────────────────────────────────────────────
# Priority Weights for Frontier Scoring
# ─────────────────────────────────────────────────────────────
PRIORITY_SITEMAP = 1.0
PRIORITY_HOME_NAVIGATION = 0.9
PRIORITY_RECENT_UPDATES = 0.8
PRIORITY_HIGH_LINK_HUB = 0.7
PRIORITY_CONTENT_PAGE = 0.5
PRIORITY_PARAMETER_FILTER = 0.2

# ─────────────────────────────────────────────────────────────
# Recrawl Tiers (hours between recrawls)
# ─────────────────────────────────────────────────────────────
RECRAWL_HUB_INTERVAL_HOURS = 6
RECRAWL_ACTIVE_INTERVAL_HOURS = 24
RECRAWL_STATIC_INTERVAL_HOURS = 168       # 7 days
RECRAWL_ARCHIVE_INTERVAL_HOURS = 720      # 30 days

# ─────────────────────────────────────────────────────────────
# Schema / Structured Data Types
# ─────────────────────────────────────────────────────────────
SCHEMA_TYPES = [
    "Breadcrumb",
    "FAQ",
    "Product",
    "Review",
    "Video",
    "Article",
    "Organization",
    "LocalBusiness",
    "HowTo",
    "Event",
    "Recipe",
    "JobPosting",
    "Other",
]

# ─────────────────────────────────────────────────────────────
# User Agent for the Crawler
# ─────────────────────────────────────────────────────────────
CRAWLER_USER_AGENT = (
    "SEOIntelligenceBot/1.0 "
    "(+https://seointelligence.dev/bot; compatible; BFS Crawler)"
)

# ─────────────────────────────────────────────────────────────
# Non-crawlable URL Schemes
# ─────────────────────────────────────────────────────────────
IGNORED_SCHEMES = frozenset([
    "mailto:", "tel:", "javascript:", "data:", "ftp:",
    "file:", "sms:", "whatsapp:", "skype:",
])

# ─────────────────────────────────────────────────────────────
# Resource File Extensions (not recursively crawled)
# ─────────────────────────────────────────────────────────────
RESOURCE_EXTENSIONS = frozenset([
    ".pdf", ".zip", ".rar", ".gz", ".tar",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dmg", ".iso",
])

MEDIA_EXTENSIONS = frozenset([
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".mp4", ".avi", ".mov", ".wmv", ".mp3", ".wav",
    ".woff", ".woff2", ".ttf", ".eot",
])
