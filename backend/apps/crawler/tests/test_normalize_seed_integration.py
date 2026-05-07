"""Integration tests: ``POST /api/v1/websites/`` exercises ``normalize_seed_url``
through ``WebsiteCreateSerializer.validate_domain``.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from apps.crawler.models import Website


class NormalizeSeedIntegrationTests(APITestCase):
    url = "/api/v1/websites/"

    def test_duplicated_scheme_is_normalised(self):
        """The actual bug: ``https://https://x.com`` should be stored as ``x.com``."""
        response = self.client.post(
            self.url,
            {"domain": "https://https://x.com", "name": "x"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert response.data["domain"] == "x.com"
        assert Website.objects.filter(domain="x.com").exists()

    def test_unsupported_scheme_is_rejected(self):
        response = self.client.post(
            self.url,
            {"domain": "ftp://x.com", "name": "x"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "domain" in response.data

    def test_garbage_input_is_rejected(self):
        response = self.client.post(
            self.url,
            {"domain": "not a url", "name": "x"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "domain" in response.data
