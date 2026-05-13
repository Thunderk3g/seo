"""API Routers — empty after the crawler-engine migration.

The previous ViewSets (WebsiteViewSet / CrawlSessionViewSet / PageViewSet)
were defined in the deleted ``apps.crawler.views`` module and registered
here. The new file-backed crawler exposes ``@api_view`` function views
directly via ``apps.crawler.urls``, so this router is now empty. Kept as a
stub in case future ORM-backed endpoints want to register here again.
"""

from rest_framework.routers import DefaultRouter

router = DefaultRouter()
