"""Post-crawl ``CrawlEvent`` retention.

The live activity-feed flusher (Phase 2.5 #19) writes ``CrawlEvent`` rows
during a running crawl. Without a cap, a long-running site crawl could
balloon the ``crawl_events`` table to hundreds of thousands of rows per
session (every link discovery, every fetch, every skip). The dashboard's
activity widget only needs a recent slice, so we trim to the most recent
:data:`DEFAULT_CAP` rows once the session reaches a terminal state.

This module exposes a single helper, :func:`cap_events_for_session`,
which is invoked from ``SessionManager.complete_session`` /
``fail_session`` / ``cancel_session``. Best-effort by design: errors are
logged at WARNING and swallowed because activity-feed cleanup must
NEVER break session-completion bookkeeping.
"""

from __future__ import annotations

import logging

from apps.crawl_sessions.models import CrawlEvent, CrawlSession


logger = logging.getLogger("seo.crawl_sessions.event_retention")

# Hard cap: keep at most this many CrawlEvent rows per session.
# Sized to comfortably power the dashboard's "Live activity" widget
# (which paginates anyway) while keeping table growth bounded.
DEFAULT_CAP: int = 5000


def cap_events_for_session(session: CrawlSession, cap: int = DEFAULT_CAP) -> int:
    """Delete oldest ``CrawlEvent`` rows for *session* until at most *cap* remain.

    Returns the number of rows deleted. Best-effort — swallows DB errors and
    returns 0 (the activity feed must never break completion).

    Trim policy: keep the *newest* ``cap`` rows, ordered by ``timestamp``
    ascending → descending. Implemented as a two-step query (count, then
    bulk delete-by-id) rather than a subquery DELETE because Django/Postgres
    doesn't allow ``DELETE ... LIMIT ... ORDER BY`` directly through the
    ORM portably.
    """
    try:
        qs = CrawlEvent.objects.filter(crawl_session=session)
        total = qs.count()
        if total <= cap:
            return 0

        excess = total - cap
        # Pull only the IDs of the oldest rows; ordering by timestamp ASC
        # puts the oldest first, slice to the count we need to drop.
        ids_to_delete = list(
            qs.order_by("timestamp", "id").values_list("id", flat=True)[:excess]
        )
        if not ids_to_delete:
            return 0

        deleted, _ = CrawlEvent.objects.filter(id__in=ids_to_delete).delete()
        return int(deleted or 0)
    except Exception:
        # Best-effort — log and move on. The activity feed is a UX nicety
        # and must NOT block / corrupt session completion.
        logger.warning(
            "cap_events_for_session failed for session=%s (cap=%s); "
            "leaving table untrimmed",
            getattr(session, "id", "<unknown>"),
            cap,
            exc_info=True,
        )
        return 0
