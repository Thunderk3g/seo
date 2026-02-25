"""
Standalone crawler test against bajajlifeinsurance.com.

Tests the core crawl pipeline without database:
  - Fetch homepage
  - Parse HTML
  - Extract metadata, links, structured data
  - Normalize URLs
  - Test frontier management

Usage:
    python test_crawler.py
"""

import asyncio
import sys
import os
import time

# Add backend to path
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

# Standalone test -- no Django setup needed for core services
from apps.crawler.services.fetcher import Fetcher
from apps.crawler.services.parser import HTMLParser
from apps.crawler.services.normalization import URLNormalizer
from apps.crawler.services.robots_parser import RobotsParser
from apps.crawler.services.sitemap_crawler import SitemapCrawler
from apps.crawler.selectors.link_extractor import LinkExtractor
from apps.crawler.selectors.metadata_extractor import MetadataExtractor
from apps.crawler.selectors.schema_extractor import SchemaExtractor


TARGET_DOMAIN = "https://www.bajajlifeinsurance.com"

LINE = "-" * 70


def print_header(title: str):
    print(f"\n{LINE}")
    print(f"  {title}")
    print(LINE)


async def test_fetcher():
    """Test the HTTP fetcher on the homepage."""
    print_header("1. FETCHER TEST")

    fetcher = Fetcher(request_delay=0.5)
    try:
        result = await fetcher.fetch(f"{TARGET_DOMAIN}/")
        print(f"  URL:           {result.url}")
        print(f"  Final URL:     {result.final_url}")
        print(f"  Status:        {result.status_code}")
        print(f"  Latency:       {result.latency_ms:.0f}ms")
        print(f"  Content Size:  {result.content_size:,} bytes")
        print(f"  Is HTML:       {result.is_html}")
        print(f"  Is HTTPS:      {result.is_https}")
        print(f"  Redirects:     {len(result.redirect_chain)}")
        if result.redirect_chain:
            for hop in result.redirect_chain:
                print(f"    -> {hop}")
        return result
    finally:
        await fetcher.close()


async def test_robots():
    """Test robots.txt fetching and parsing."""
    print_header("2. ROBOTS.TXT TEST")

    fetcher = Fetcher(request_delay=0.5)
    try:
        robots_content = await fetcher.fetch_robots_txt(TARGET_DOMAIN)
        if robots_content:
            parser = RobotsParser(user_agent="SEOIntelligenceBot")
            parser.parse(robots_content)

            print(f"  Disallowed Paths:  {len(parser.disallowed_paths)}")
            for path in parser.disallowed_paths[:10]:
                print(f"    - {path}")
            if len(parser.disallowed_paths) > 10:
                print(f"    ... and {len(parser.disallowed_paths) - 10} more")

            print(f"  Allowed Paths:     {len(parser.allowed_paths)}")
            print(f"  Crawl Delay:       {parser.crawl_delay}")
            print(f"  Sitemap URLs:      {len(parser.sitemap_urls)}")
            for sm in parser.sitemap_urls[:5]:
                print(f"    - {sm}")

            # Test some paths
            test_paths = ["/", "/about", "/admin", "/wp-admin"]
            print(f"\n  Path Checks:")
            for path in test_paths:
                allowed = parser.is_allowed(path)
                status = "ALLOWED" if allowed else "BLOCKED"
                print(f"    {path:20s} -> {status}")

            return parser
        else:
            print("  No robots.txt found")
            return None
    finally:
        await fetcher.close()


def test_parser(html: str):
    """Test HTML parser on fetched content."""
    print_header("3. HTML PARSER TEST")

    parser = HTMLParser(base_url=TARGET_DOMAIN)
    result = parser.parse(html, page_url=f"{TARGET_DOMAIN}/")

    print(f"  Title:           {result.title[:80]}")
    print(f"  Meta Desc:       {result.meta_description[:80]}")
    print(f"  H1:              {result.h1[:80] if result.h1 else '(none)'}")
    print(f"  H2 Count:        {len(result.h2_list)}")
    print(f"  H3 Count:        {len(result.h3_list)}")
    print(f"  Canonical:       {result.canonical_url or '(none)'}")
    print(f"  Robots Meta:     {result.robots_meta or '(none)'}")
    print(f"  Word Count:      {result.word_count:,}")
    print(f"  Content Size:    {result.content_size_bytes:,} bytes")
    print(f"  Page Hash:       {result.page_hash[:16]}...")
    print(f"  Total Images:    {result.total_images}")
    print(f"  Imgs w/o Alt:    {result.images_without_alt}")
    print(f"  Scripts:         {len(result.scripts)}")
    print(f"  Stylesheets:     {len(result.stylesheets)}")
    print(f"  JSON-LD Blocks:  {len(result.json_ld)}")
    print(f"  Raw Links:       {len(result.raw_links)}")
    print(f"  Language:        {result.lang or '(none)'}")
    print(f"  OG Title:        {result.og_title[:60] if result.og_title else '(none)'}")
    print(f"  Pagination Next: {result.pagination_next or '(none)'}")

    return result


def test_metadata(parse_result):
    """Test metadata extraction."""
    print_header("4. METADATA EXTRACTION TEST")

    extractor = MetadataExtractor()
    metadata = extractor.extract(parse_result)

    print(f"  Is Noindex:      {metadata.is_noindex}")
    print(f"  Is Nofollow:     {metadata.is_nofollow}")
    print(f"  Has Canonical:   {metadata.has_canonical}")
    print(f"  Thin Content:    {metadata.is_thin_content}")

    # Test soft 404
    is_soft_404 = extractor.detect_soft_404(parse_result, 200)
    print(f"  Soft 404:        {is_soft_404}")

    return metadata


def test_link_extractor(parse_result):
    """Test link extraction and classification."""
    print_header("5. LINK EXTRACTION TEST")

    normalizer = URLNormalizer(TARGET_DOMAIN)
    extractor = LinkExtractor(normalizer=normalizer, include_subdomains=False)

    links = extractor.extract(parse_result.raw_links, source_url=f"{TARGET_DOMAIN}/")
    stats = extractor.get_link_stats(links)

    print(f"  Total Links:     {stats['total']}")
    print(f"  Internal:        {stats['internal']}")
    print(f"  External:        {stats['external']}")
    print(f"  Media:           {stats['media']}")
    print(f"  Resource:        {stats['resource']}")
    print(f"  Navigation:      {stats['navigation']}")
    print(f"  Nofollow:        {stats['nofollow']}")

    # Show some internal links
    crawlable = extractor.filter_crawlable(links)
    print(f"\n  Crawlable Links: {len(crawlable)}")
    for link in crawlable[:10]:
        print(f"    -> {link.target_url}")
    if len(crawlable) > 10:
        print(f"    ... and {len(crawlable) - 10} more")

    # Show some external links
    external = [l for l in links if l.link_type == "external"]
    if external:
        print(f"\n  External Links (top 5):")
        for link in external[:5]:
            print(f"    -> {link.target_url} [{link.anchor_text[:40]}]")

    return links


def test_schema_extractor(parse_result):
    """Test structured data extraction."""
    print_header("6. STRUCTURED DATA TEST")

    extractor = SchemaExtractor()
    schemas = extractor.extract(parse_result.json_ld)

    if schemas:
        print(f"  Schema Types Found: {len(schemas)}")
        summary = extractor.get_schema_summary(schemas)
        for schema_type, info in summary.items():
            print(f"    - {schema_type}: {info['count']} (valid: {info['valid']}, invalid: {info['invalid']})")
    else:
        print("  No structured data found")

    return schemas


def test_normalizer():
    """Test URL normalization."""
    print_header("7. URL NORMALIZATION TEST")

    normalizer = URLNormalizer(TARGET_DOMAIN)

    test_cases = [
        "/about-us",
        "/products?utm_source=google&id=123",
        "//www.bajajlifeinsurance.com/plans/",
        "mailto:info@bajaj.com",
        "tel:+911234567890",
        "/path/../other/page",
        "https://www.bajajlifeinsurance.com/PAGE/",
        "javascript:void(0)",
        "/blog/?page=1&sort=date&fbclid=abc123",
    ]

    for url in test_cases:
        normalized = normalizer.normalize(url)
        status = normalized or "(filtered out)"
        print(f"  {url:50s} -> {status}")

    # Test domain checks
    print(f"\n  Domain Checks:")
    domain_tests = [
        "https://www.bajajlifeinsurance.com/page",
        "https://bajajlifeinsurance.com/page",
        "https://blog.bajajlifeinsurance.com/page",
        "https://www.google.com/page",
    ]
    for url in domain_tests:
        is_internal = normalizer.is_internal(url, include_subdomains=False)
        is_sub = normalizer.is_internal(url, include_subdomains=True)
        print(f"  {url:50s} internal={is_internal} (with_subs={is_sub})")


def test_frontier():
    """Test frontier manager."""
    print_header("8. FRONTIER MANAGER TEST")

    from apps.crawler.services.frontier_manager import FrontierManager
    from apps.common.constants import SOURCE_SEED, SOURCE_SITEMAP, SOURCE_LINK

    frontier = FrontierManager(max_depth=5, max_urls=1000)

    # Add seed
    frontier.add(f"{TARGET_DOMAIN}/", depth=0, source=SOURCE_SEED)
    frontier.add(f"{TARGET_DOMAIN}/about", depth=1, source=SOURCE_LINK)
    frontier.add(f"{TARGET_DOMAIN}/products", depth=1, source=SOURCE_SITEMAP)
    frontier.add(f"{TARGET_DOMAIN}/blog", depth=2, source=SOURCE_LINK)
    frontier.add(f"{TARGET_DOMAIN}/blog/post-1", depth=3, source=SOURCE_LINK)

    # Try duplicate
    added_dup = frontier.add(f"{TARGET_DOMAIN}/about", depth=1, source=SOURCE_LINK)

    print(f"  Queue Size:      {frontier.size}")
    print(f"  Total Seen:      {frontier.total_seen}")
    print(f"  Duplicate Block:  {not added_dup}")

    # Pop in priority order
    print(f"\n  Priority Order (pop sequence):")
    count = 0
    while not frontier.is_empty and count < 10:
        entry = frontier.pop()
        if entry:
            print(f"    {count+1}. [{entry.source:8s}] depth={entry.depth} priority={-entry.priority_score:.2f} -> {entry.url}")
            frontier.mark_crawled(entry.url)
            count += 1

    metrics = frontier.get_metrics()
    print(f"\n  Final Metrics: {metrics}")


async def main():
    """Run all tests."""
    start = time.time()

    print("=" * 70)
    print("  SEO CRAWLER ENGINE - INTEGRATION TEST")
    print(f"  Target: {TARGET_DOMAIN}")
    print("=" * 70)

    # 1. Fetch homepage
    fetch_result = await test_fetcher()

    if not fetch_result or not fetch_result.html:
        print("\n  FATAL: Could not fetch homepage. Aborting.")
        return

    # 2. Test robots.txt
    await test_robots()

    # 3. Parse HTML
    parse_result = test_parser(fetch_result.html)

    # 4. Extract metadata
    test_metadata(parse_result)

    # 5. Extract links
    test_link_extractor(parse_result)

    # 6. Extract structured data
    test_schema_extractor(parse_result)

    # 7. Test URL normalization
    test_normalizer()

    # 8. Test frontier
    test_frontier()

    elapsed = time.time() - start
    print(f"\n{'=' * 70}")
    print(f"  ALL TESTS COMPLETED in {elapsed:.1f}s")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
