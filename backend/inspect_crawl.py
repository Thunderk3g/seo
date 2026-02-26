import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.base")
try:
    django.setup()
except Exception as e:
    print(f"Failed loading core.settings.base: {e}")
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.base"
    django.setup()

from apps.crawler.models import CrawledPage, DiscoveredURL, PageLink
from apps.crawl_sessions.models import CrawlSession
from django.db.models import Count

def check():
    session = CrawlSession.objects.last()
    if not session:
        print("No sessions found.")
        return

    print(f"Latest Session ID: {session.id}")
    print(f"Target: {session.website.domain}")
    
    pages = CrawledPage.objects.filter(session=session)
    print(f"Crawled pages in DB: {pages.count()}")
    
    urls = DiscoveredURL.objects.filter(session=session)
    print(f"Discovered URLs in DB: {urls.count()}")
    
    links = PageLink.objects.filter(session=session)
    print(f"Links stored in DB: {links.count()}")

    print("\nTop 5 Content Types:")
    for row in pages.values("content_type").annotate(c=Count("id")).order_by("-c")[:5]:
        print(f"  {row['content_type']}: {row['c']}")

    print("\nTop 5 Status Codes:")
    for row in pages.values("status_code").annotate(c=Count("id")).order_by("-c")[:5]:
        print(f"  {row['status_code']}: {row['c']}")

    print("\nTop 10 URLs Crawled:")
    for p in pages.order_by("-created_at")[:10]:
        print(f"  {p.url} ({p.status_code})")

if __name__ == "__main__":
    check()
