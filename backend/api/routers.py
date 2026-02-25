"""API Routers – Central registration of all ViewSets."""

from rest_framework.routers import DefaultRouter

from apps.crawler.views import WebsiteViewSet, CrawlSessionViewSet, PageViewSet

router = DefaultRouter()
router.register(r"websites", WebsiteViewSet, basename="website")
router.register(r"sessions", CrawlSessionViewSet, basename="crawl-session")
router.register(r"pages", PageViewSet, basename="page")
