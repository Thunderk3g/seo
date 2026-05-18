"""Regression tests for the PDF / Office-doc crawling change.

We previously had .pdf in the URL eligibility skip list, so PDFs Google
indexed (~1,000+ on bajajlifeinsurance.com — policy docs, fund factsheets,
brochures) never appeared in our reports. Now PDFs are allowed; the
fetcher streams the response so binary bodies are never downloaded.
"""
from __future__ import annotations

from apps.crawler.engine.url_utils import has_skip_extension


class TestSkipExtensions:
    def test_pdf_is_allowed(self):
        assert not has_skip_extension(
            "https://www.bajajlifeinsurance.com/content/dam/balic-web/pdf/"
            "ulip/invest-protect-goal-sl.pdf"
        )

    def test_doc_extensions_allowed(self):
        for ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"):
            url = f"https://www.bajajlifeinsurance.com/content/dam/balic-web/pdf/x{ext}"
            assert not has_skip_extension(url), f"{ext} should be allowed"

    def test_image_video_audio_still_skipped(self):
        # We don't want to flood reports with every JPG / PNG / MP4.
        skips = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
                 ".mp3", ".mp4", ".wav", ".mov",
                 ".woff", ".woff2", ".ttf",
                 ".css", ".js", ".json", ".xml",
                 ".zip", ".tar", ".gz")
        for ext in skips:
            url = f"https://www.bajajlifeinsurance.com/asset{ext}"
            assert has_skip_extension(url), f"{ext} should still be skipped"

    def test_html_pages_are_allowed(self):
        assert not has_skip_extension("https://www.bajajlifeinsurance.com/")
        assert not has_skip_extension(
            "https://www.bajajlifeinsurance.com/term-insurance-plans.html"
        )
        assert not has_skip_extension(
            "https://www.bajajlifeinsurance.com/underinsurance-calculator/"
        )
