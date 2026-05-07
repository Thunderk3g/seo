"""Integration tests for ``POST /api/v1/sessions/<id>/cancel/``.

Covers state transitions for the cancel action on
``CrawlSessionViewSet``:

- Running session -> 200, status flips to ``cancelled``,
  ``finished_at`` populated.
- Pending session -> 200, status flips to ``cancelled``.
- Already-completed session -> 409 with ``detail`` field.
- Non-existent session id -> 404.
"""

import uuid

from rest_framework import status
from rest_framework.test import APITestCase

from apps.common import constants
from apps.crawl_sessions.models import CrawlSession
from apps.crawler.models import Website


class CancelSessionEndpointTests(APITestCase):
    """Exercise the cancel custom action on CrawlSessionViewSet."""

    @classmethod
    def setUpTestData(cls):
        cls.website = Website.objects.create(domain="x.com", name="x")

    def _cancel_url(self, session_id):
        return f"/api/v1/sessions/{session_id}/cancel/"

    def test_cancel_running_session_returns_200_and_marks_cancelled(self):
        session = CrawlSession.objects.create(
            website=self.website,
            status=constants.SESSION_STATUS_RUNNING,
        )

        response = self.client.post(self._cancel_url(session.id))

        assert response.status_code == status.HTTP_200_OK, response.content
        session.refresh_from_db()
        assert session.status == constants.SESSION_STATUS_CANCELLED
        assert session.finished_at is not None
        assert response.data["status"] == constants.SESSION_STATUS_CANCELLED

    def test_cancel_pending_session_returns_200_and_marks_cancelled(self):
        session = CrawlSession.objects.create(
            website=self.website,
            status=constants.SESSION_STATUS_PENDING,
        )

        response = self.client.post(self._cancel_url(session.id))

        assert response.status_code == status.HTTP_200_OK, response.content
        session.refresh_from_db()
        assert session.status == constants.SESSION_STATUS_CANCELLED

    def test_cancel_completed_session_returns_409_with_detail(self):
        session = CrawlSession.objects.create(
            website=self.website,
            status=constants.SESSION_STATUS_COMPLETED,
        )

        response = self.client.post(self._cancel_url(session.id))

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "detail" in response.data
        session.refresh_from_db()
        assert session.status == constants.SESSION_STATUS_COMPLETED

    def test_cancel_nonexistent_session_returns_404(self):
        bogus_id = uuid.uuid4()

        response = self.client.post(self._cancel_url(bogus_id))

        assert response.status_code == status.HTTP_404_NOT_FOUND
