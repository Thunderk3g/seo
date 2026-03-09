import os
import django
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from apps.crawl_sessions.models import CrawlSession, Page, StructuredData

session = CrawlSession.objects.order_by("-started_at").first()
if not session:
    print("No session found.")
    sys.exit(0)

print(f"--- Session: {session.id} ---")
print(f"Discovered: {session.total_urls_discovered}")
print(f"Crawled: {session.total_urls_crawled}")
print(f"Index-eligible: {session.total_index_eligible}")
print(f"Excluded: {session.total_excluded}")
print(f"Breakdown: {session.exclusion_breakdown}")
print("-" * 30)

pages = Page.objects.filter(crawl_session=session)[:5]
for p in pages:
    print(f"\nURL: {p.url}")
    print(f"Lifecycle: {p.url_lifecycle_state}")
    print(f"Canonical resolved: {p.canonical_resolved}")
    print(f"Canonical match: {p.canonical_match}")
    print(f"Directory: {p.directory_segment}")
    print(f"Discovery source: {p.discovery_source_first}")
    print(f"All sources: {p.discovery_sources_all}")

# Check structured data if any
sd_count = StructuredData.objects.filter(page__in=pages).count()
print(f"\nTotal structured data found for these 5 pages: {sd_count}")

from apps.ai_agents.agents.indexing_agent import IndexingIntelligenceAgent
print("\n--- AI Agent Test ---")
print(IndexingIntelligenceAgent.analyze_session(session.id))
