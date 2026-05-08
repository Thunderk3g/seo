"""Scheduled and on-demand crawl tasks (Celery).

Defines async tasks that can be triggered by:
- The scheduler (daily scheduled crawls)
- The API (on-demand crawls)
- URL inspection requests
"""

import asyncio
import logging

from celery import shared_task

from apps.common import constants
from apps.common.logging import log_session_event
from apps.common.url_utils import normalize_seed_url

logger = logging.getLogger("seo.crawler.tasks")


@shared_task(
    bind=True,
    name="crawler.run_scheduled_crawl",
    max_retries=1,
    default_retry_delay=300,
)
def run_scheduled_crawl(self, website_id: str):
    """Execute a scheduled full-site crawl.

    Creates a new session, runs the crawler engine,
    persists results, and updates session status.
    """
    from apps.crawler.models import Website, CrawlConfig
    from apps.crawler.services.crawler_engine import CrawlerEngine
    from apps.crawl_sessions.services.session_manager import SessionManager

    try:
        website = Website.objects.get(id=website_id)
    except Website.DoesNotExist:
        logger.error("Website %s not found", website_id)
        return {"error": f"Website {website_id} not found"}

    # Get crawl config
    try:
        config = website.crawl_config
    except CrawlConfig.DoesNotExist:
        config = CrawlConfig.objects.create(website=website)

    # Create session
    session = SessionManager.create_session(
        website=website,
        session_type=constants.SESSION_TYPE_SCHEDULED,
    )
    SessionManager.start_session(session)

    try:
        seed_url = normalize_seed_url(website.domain)
    except ValueError as exc:
        logger.error("Invalid domain for website %s: %s", website.domain, exc)
        SessionManager.fail_session(session, str(exc))
        return {
            "session_id": str(session.id),
            "status": "failed",
            "error": str(exc),
        }

    try:
        # Build and run engine
        engine = CrawlerEngine(
            domain=seed_url,
            max_depth=config.max_depth,
            max_urls=config.max_urls_per_session,
            concurrency=config.concurrency,
            request_delay=config.request_delay,
            request_timeout=config.request_timeout,
            max_retries=config.max_retries,
            enable_js_rendering=config.enable_js_rendering,
            respect_robots=config.respect_robots_txt,
            include_subdomains=website.include_subdomains,
            user_agent=config.effective_user_agent,
            session_id=str(session.id),
            excluded_paths=config.excluded_paths or [],
            excluded_params=config.excluded_params or [],
        )

        # Run async engine in sync context
        result = asyncio.run(engine.run())

        # Persist results
        SessionManager.persist_crawl_results(session, result)
        SessionManager.complete_session(session)

        # Best-effort post-crawl AI insights compute (cache primer).
        # Mirrors run_on_demand_crawl. See spec §6 step 5.
        try:
            from apps.ai_agents.services.insights_service import InsightsService
            InsightsService.regenerate(session)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Post-crawl AI insights regenerate failed for session %s",
                session.id,
            )

        return {
            "session_id": str(session.id),
            "status": "completed",
            "pages_crawled": result.total_pages,
            "links_found": result.total_links,
            "metrics": result.metrics,
        }

    except Exception as exc:
        logger.error("Scheduled crawl failed for %s: %s", website.domain, exc)
        SessionManager.fail_session(session, str(exc))
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    name="crawler.run_on_demand_crawl",
    max_retries=0,
)
def run_on_demand_crawl(
    self,
    website_id: str,
    target_path_prefix: str = "",
):
    """Execute an on-demand crawl (full site or sectional).

    Triggered by user action. Supports sectional crawling
    via target_path_prefix (e.g., /blog/).
    """
    from apps.crawler.models import Website, CrawlConfig
    from apps.crawler.services.crawler_engine import CrawlerEngine
    from apps.crawl_sessions.services.session_manager import SessionManager

    try:
        website = Website.objects.get(id=website_id)
    except Website.DoesNotExist:
        logger.error("Website %s not found", website_id)
        return {"error": f"Website {website_id} not found"}

    try:
        config = website.crawl_config
    except CrawlConfig.DoesNotExist:
        config = CrawlConfig.objects.create(website=website)

    session = SessionManager.create_session(
        website=website,
        session_type=constants.SESSION_TYPE_ON_DEMAND,
        target_path_prefix=target_path_prefix,
    )
    SessionManager.start_session(session)

    try:
        seed_url = normalize_seed_url(website.domain)
    except ValueError as exc:
        logger.error("Invalid domain for website %s: %s", website.domain, exc)
        SessionManager.fail_session(session, str(exc))
        return {
            "session_id": str(session.id),
            "status": "failed",
            "error": str(exc),
        }

    try:
        engine = CrawlerEngine(
            domain=seed_url,
            max_depth=config.max_depth,
            max_urls=config.max_urls_per_session,
            concurrency=config.concurrency,
            request_delay=config.request_delay,
            request_timeout=config.request_timeout,
            max_retries=config.max_retries,
            enable_js_rendering=config.enable_js_rendering,
            respect_robots=config.respect_robots_txt,
            include_subdomains=website.include_subdomains,
            user_agent=config.effective_user_agent,
            target_path_prefix=target_path_prefix,
            session_id=str(session.id),
            excluded_paths=config.excluded_paths or [],
            excluded_params=config.excluded_params or [],
        )

        result = asyncio.run(engine.run())
        SessionManager.persist_crawl_results(session, result)
        SessionManager.complete_session(session)

        # Best-effort post-crawl AI insights compute. Spec §6 step 5: prime
        # the session.ai_insights cache so the dashboard drawer opens
        # without billing Anthropic on first view. Swallow errors — the
        # crawl already succeeded; insights are optional.
        try:
            from apps.ai_agents.services.insights_service import InsightsService
            InsightsService.regenerate(session)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Post-crawl AI insights regenerate failed for session %s",
                session.id,
            )

        return {
            "session_id": str(session.id),
            "status": "completed",
            "pages_crawled": result.total_pages,
            "metrics": result.metrics,
        }

    except Exception as exc:
        logger.error("On-demand crawl failed for %s: %s", website.domain, exc)
        SessionManager.fail_session(session, str(exc))
        return {
            "session_id": str(session.id),
            "status": "failed",
            "error": str(exc),
        }


@shared_task(
    name="crawler.run_url_inspection",
    max_retries=0,
)
def run_url_inspection(website_id: str, target_url: str):
    """Inspect a single URL – instant, lightweight refresh.

    Creates a url_inspection session and returns detailed
    page-level analysis for the specified URL.
    """
    from apps.crawler.models import Website, CrawlConfig
    from apps.crawler.services.crawler_engine import CrawlerEngine
    from apps.crawl_sessions.services.session_manager import SessionManager

    try:
        website = Website.objects.get(id=website_id)
    except Website.DoesNotExist:
        return {"error": f"Website {website_id} not found"}

    try:
        config = website.crawl_config
    except CrawlConfig.DoesNotExist:
        config = CrawlConfig.objects.create(website=website)

    session = SessionManager.create_session(
        website=website,
        session_type=constants.SESSION_TYPE_URL_INSPECTION,
        target_url=target_url,
    )
    SessionManager.start_session(session)

    try:
        seed_url = normalize_seed_url(website.domain)
    except ValueError as exc:
        logger.error("Invalid domain for website %s: %s", website.domain, exc)
        SessionManager.fail_session(session, str(exc))
        return {
            "session_id": str(session.id),
            "status": "failed",
            "error": str(exc),
        }

    try:
        engine = CrawlerEngine(
            domain=seed_url,
            enable_js_rendering=config.enable_js_rendering,
            user_agent=config.effective_user_agent,
            session_id=str(session.id),
            excluded_paths=config.excluded_paths or [],
            excluded_params=config.excluded_params or [],
        )

        inspection = asyncio.run(engine.inspect_url(target_url))

        SessionManager.complete_session(session)

        # Note: AI insights regenerate is intentionally NOT fired here.
        # url_inspection sessions probe a single URL and have no aggregate
        # indexability/canonical/issue distribution to summarise — the
        # IndexingIntelligenceAgent payload would be near-empty. Insights
        # remain a full-crawl feature (scheduled / on-demand).

        return {
            "session_id": str(session.id),
            "status": "completed",
            "inspection": inspection,
        }

    except Exception as exc:
        logger.error("URL inspection failed for %s: %s", target_url, exc)
        SessionManager.fail_session(session, str(exc))
        return {
            "session_id": str(session.id),
            "status": "failed",
            "error": str(exc),
        }


@shared_task(name="crawler.run_change_detection")
def run_change_detection(website_id: str):
    """Run change detection between the two latest sessions.

    Compares page hashes to identify added, removed, and
    modified pages without performing a new crawl.
    """
    from apps.crawler.models import Website
    from apps.crawl_sessions.services.session_manager import SessionManager
    from apps.crawl_sessions.services.change_detector import ChangeDetector

    try:
        website = Website.objects.get(id=website_id)
    except Website.DoesNotExist:
        return {"error": f"Website {website_id} not found"}

    # Get the two most recent completed sessions
    from apps.crawl_sessions.models import CrawlSession
    sessions = (
        CrawlSession.objects
        .filter(
            website=website,
            status=constants.SESSION_STATUS_COMPLETED,
        )
        .order_by("-started_at")[:2]
    )

    if len(sessions) < 2:
        return {"error": "Need at least 2 completed sessions for comparison"}

    current = sessions[0]
    previous = sessions[1]

    report = ChangeDetector.compare_sessions(current, previous)
    change_rate = ChangeDetector.calculate_change_rate(report)

    return {
        "current_session": str(current.id),
        "previous_session": str(previous.id),
        "summary": report.summary(),
        "change_rate_percent": change_rate,
        "urls_needing_recrawl": ChangeDetector.get_urls_needing_recrawl(report),
    }
