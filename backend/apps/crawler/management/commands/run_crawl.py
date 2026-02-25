"""
Management command to trigger a crawl from the CLI.

Usage:
    python manage.py run_crawl example.com
    python manage.py run_crawl example.com --type on_demand
    python manage.py run_crawl example.com --type url_inspection --url https://example.com/page
    python manage.py run_crawl example.com --max-depth 5 --max-urls 10000
"""

import asyncio
from django.core.management.base import BaseCommand, CommandError

from apps.common import constants
from apps.crawler.models import Website, CrawlConfig
from apps.crawler.services.crawler_engine import CrawlerEngine
from apps.crawl_sessions.services.session_manager import SessionManager


class Command(BaseCommand):
    help = "Run a crawl for a given website domain"

    def add_arguments(self, parser):
        parser.add_argument(
            "domain",
            type=str,
            help="Domain to crawl (e.g. example.com)",
        )
        parser.add_argument(
            "--type",
            type=str,
            default="on_demand",
            choices=["scheduled", "on_demand", "url_inspection"],
            help="Type of crawl session",
        )
        parser.add_argument(
            "--url",
            type=str,
            default="",
            help="Target URL for url_inspection type",
        )
        parser.add_argument(
            "--path-prefix",
            type=str,
            default="",
            help="Path prefix for sectional crawl (e.g. /blog/)",
        )
        parser.add_argument(
            "--max-depth",
            type=int,
            default=None,
            help="Override max crawl depth",
        )
        parser.add_argument(
            "--max-urls",
            type=int,
            default=None,
            help="Override max URLs per session",
        )
        parser.add_argument(
            "--js-rendering",
            action="store_true",
            help="Enable JavaScript rendering (requires Playwright)",
        )

    def handle(self, *args, **options):
        domain = options["domain"].strip().lower()
        session_type = options["type"]

        # Get or create website
        website, created = Website.objects.get_or_create(
            domain=domain,
            defaults={"name": domain, "is_active": True},
        )
        if created:
            self.stdout.write(f"Created website: {domain}")

        # Get or create config
        config, _ = CrawlConfig.objects.get_or_create(website=website)

        # Apply overrides
        max_depth = options["max_depth"] or config.max_depth
        max_urls = options["max_urls"] or config.max_urls_per_session
        enable_js = options["js_rendering"] or config.enable_js_rendering

        # Create session
        session = SessionManager.create_session(
            website=website,
            session_type=session_type,
            target_url=options["url"],
            target_path_prefix=options["path_prefix"],
        )
        SessionManager.start_session(session)

        self.stdout.write(
            f"Session {str(session.id)[:8]} started "
            f"[{session_type}] for {domain}"
        )

        # Handle URL inspection
        if session_type == constants.SESSION_TYPE_URL_INSPECTION:
            if not options["url"]:
                raise CommandError("--url is required for url_inspection type")

            try:
                engine = CrawlerEngine(
                    domain=f"https://{domain}",
                    enable_js_rendering=enable_js,
                    user_agent=config.effective_user_agent,
                    session_id=str(session.id),
                )
                result = asyncio.run(engine.inspect_url(options["url"]))
                SessionManager.complete_session(session)

                self.stdout.write(self.style.SUCCESS(
                    f"\nURL Inspection Complete:\n"
                    f"  Status: {result.get('status_code')}\n"
                    f"  Title: {result.get('title')}\n"
                    f"  Classification: {result.get('classification', {}).get('type')}\n"
                    f"  Links Found: {result.get('links_found')}\n"
                ))
            except Exception as exc:
                SessionManager.fail_session(session, str(exc))
                raise CommandError(f"URL inspection failed: {exc}")
            return

        # Full / Sectional Crawl
        try:
            engine = CrawlerEngine(
                domain=f"https://{domain}",
                max_depth=max_depth,
                max_urls=max_urls,
                concurrency=config.concurrency,
                request_delay=config.request_delay,
                request_timeout=config.request_timeout,
                max_retries=config.max_retries,
                enable_js_rendering=enable_js,
                respect_robots=config.respect_robots_txt,
                include_subdomains=website.include_subdomains,
                user_agent=config.effective_user_agent,
                target_path_prefix=options["path_prefix"],
                session_id=str(session.id),
            )

            result = asyncio.run(engine.run())

            # Persist results to database
            SessionManager.persist_crawl_results(session, result)
            SessionManager.complete_session(session)

            metrics = result.metrics
            self.stdout.write(self.style.SUCCESS(
                f"\nCrawl Complete:\n"
                f"  Pages Crawled: {metrics.get('total_urls_crawled', 0)}\n"
                f"  URLs Discovered: {metrics.get('total_urls_discovered', 0)}\n"
                f"  Failed: {metrics.get('total_urls_failed', 0)}\n"
                f"  Links Stored: {metrics.get('total_links_stored', 0)}\n"
                f"  Max Depth: {metrics.get('max_depth_reached', 0)}\n"
                f"  Avg Response: {metrics.get('avg_response_time_ms', 0):.0f}ms\n"
                f"  Duration: {metrics.get('duration_seconds', 0):.1f}s\n"
                f"  Session ID: {session.id}\n"
            ))

        except Exception as exc:
            SessionManager.fail_session(session, str(exc))
            raise CommandError(f"Crawl failed: {exc}")
