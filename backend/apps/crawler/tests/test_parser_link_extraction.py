"""Regression tests for two parser bugs discovered in the Bajaj crawl:

1. URL normalisation stripped trailing slashes, turning live pages like
   ``/underinsurance-calculator/`` (HTTP 200) into 404s
   (``/underinsurance-calculator``).
2. ``data-link="false"`` and similar config booleans on AEM components
   were being treated as URLs, producing spurious ``/false`` 404s on every
   page that embedded the floating-feedback widget.
"""
from __future__ import annotations

from apps.crawler.engine.parser import _collect_links, _looks_like_url, parse_page
from apps.crawler.engine.url_utils import normalize

from bs4 import BeautifulSoup


# ── Normalizer: trailing-slash preservation ───────────────────────────────
class TestTrailingSlash:
    def test_preserves_trailing_slash_on_directory_url(self):
        # Live Bajaj page: /underinsurance-calculator/ is HTTP 200,
        # /underinsurance-calculator is HTTP 404. They must be distinct.
        assert normalize("https://www.bajajlifeinsurance.com/underinsurance-calculator/") \
            == "https://www.bajajlifeinsurance.com/underinsurance-calculator/"

    def test_does_not_add_slash_when_absent(self):
        assert normalize("https://www.bajajlifeinsurance.com/term-insurance-plans.html") \
            == "https://www.bajajlifeinsurance.com/term-insurance-plans.html"

    def test_distinguishes_slashed_and_bare_paths(self):
        a = normalize("https://www.bajajlifeinsurance.com/foo/")
        b = normalize("https://www.bajajlifeinsurance.com/foo")
        assert a != b, "/foo/ and /foo must dedupe to different URLs"

    def test_root_path_unchanged(self):
        assert normalize("https://www.bajajlifeinsurance.com/") \
            == "https://www.bajajlifeinsurance.com/"


# ── Parser: reject non-URL data-* attribute values ────────────────────────
class TestDataAttributeFiltering:
    def test_looks_like_url_accepts_real_urls(self):
        assert _looks_like_url("/foo")
        assert _looks_like_url("/foo/")
        assert _looks_like_url("https://example.com/x")
        assert _looks_like_url("//cdn.example.com/x.js")
        assert _looks_like_url("./relative.html")
        assert _looks_like_url("page.html")

    def test_looks_like_url_rejects_config_flags(self):
        # The exact case we hit on bajajlifeinsurance.com: data-link="false"
        assert not _looks_like_url("false")
        assert not _looks_like_url("true")
        assert not _looks_like_url("null")
        assert not _looks_like_url("undefined")
        assert not _looks_like_url("")
        assert not _looks_like_url("   ")
        assert not _looks_like_url("0")
        assert not _looks_like_url("1")

    def test_data_link_false_does_not_become_a_link(self):
        # Exact HTML pattern from the floating-feedback widget.
        html = '''
            <div class="floating-feedback-main-container"
                 data-link="false"
                 id="main-container">
              <p>Floating widget</p>
            </div>
            <a href="/real-link/">Real link</a>
        '''
        soup = BeautifulSoup(html, "html.parser")
        links = _collect_links(soup, "https://www.bajajlifeinsurance.com/ae/foo.html")
        assert "https://www.bajajlifeinsurance.com/ae/false" not in links
        assert "https://www.bajajlifeinsurance.com/false" not in links
        assert "https://www.bajajlifeinsurance.com/real-link/" in links

    def test_data_link_with_real_url_still_followed(self):
        html = '<div data-link="/genuine/landing.html">tile</div>'
        soup = BeautifulSoup(html, "html.parser")
        links = _collect_links(soup, "https://www.bajajlifeinsurance.com/")
        assert "https://www.bajajlifeinsurance.com/genuine/landing.html" in links


# ── End-to-end: parse_page handles the slash + boolean cases together ─────
class TestParsePageRegressions:
    def test_widget_link_to_underinsurance_keeps_slash(self):
        html = '''
            <html><head><title>article</title></head><body>
              <a href="https://www.bajajlifeinsurance.com/underinsurance-calculator/">
                Underinsurance Calculator
              </a>
            </body></html>
        '''
        result = parse_page(html, "https://www.bajajlifeinsurance.com/life-insurance-guide/term/x.html")
        assert "https://www.bajajlifeinsurance.com/underinsurance-calculator/" in result["links"]
        assert "https://www.bajajlifeinsurance.com/underinsurance-calculator" not in result["links"]

    def test_floating_feedback_widget_does_not_produce_false_link(self):
        html = '''
            <html><head><title>article</title></head><body>
              <div class="floating-feedback-main-container"
                   id="main-container" data-link="false">
                <span>feedback</span>
              </div>
              <a href="/term-insurance-plans/">Term</a>
            </body></html>
        '''
        result = parse_page(html, "https://www.bajajlifeinsurance.com/ae/nri-ulip-plans.html")
        for link in result["links"]:
            assert not link.endswith("/false"), f"Spurious /false link: {link}"
            assert "false" not in link.split("/")[-1] or link.endswith(".html"), link
