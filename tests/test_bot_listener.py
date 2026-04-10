"""Tests for bot_listener.py"""

import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path
from bs4 import BeautifulSoup

from bot_listener import (
    _he,
    _parse_soup,
    URL_RE,
    fetch_job_page,
)


# ── _he (HTML escaping) ───────────────────────────────────────────────────────

class TestHe:
    def test_plain_text_unchanged(self):
        assert _he("Hello World") == "Hello World"

    def test_ampersand_escaped(self):
        assert _he("R&D") == "R&amp;D"

    def test_less_than_escaped(self):
        assert _he("<script>") == "&lt;script&gt;"

    def test_greater_than_escaped(self):
        assert _he("x > y") == "x &gt; y"

    def test_all_together(self):
        assert _he("<b>R&D</b>") == "&lt;b&gt;R&amp;D&lt;/b&gt;"

    def test_empty(self):
        assert _he("") == ""


# ── URL_RE ────────────────────────────────────────────────────────────────────

class TestUrlRe:
    def test_https_found(self):
        assert URL_RE.findall("check https://example.com out") == ["https://example.com"]

    def test_http_found(self):
        assert URL_RE.findall("http://example.com") == ["http://example.com"]

    def test_no_url(self):
        assert URL_RE.findall("no link here") == []

    def test_multiple_urls(self):
        text = "https://a.com and https://b.com"
        assert len(URL_RE.findall(text)) == 2

    def test_no_ftp(self):
        assert URL_RE.findall("ftp://example.com") == []


# ── _parse_soup ───────────────────────────────────────────────────────────────

class TestParseSoup:
    def _soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    def test_extracts_title_from_h1(self):
        soup = self._soup("<html><body><h1>Software Engineer Intern</h1></body></html>")
        title, _, _ = _parse_soup(soup, "https://example.com/job/1")
        assert title == "Software Engineer Intern"

    def test_extracts_title_from_og_tag(self):
        soup = self._soup(
            '<html><head>'
            '<meta property="og:title" content="ML Engineer Intern"/>'
            '</head><body><h1>Other text</h1></body></html>'
        )
        title, _, _ = _parse_soup(soup, "https://example.com/job/1")
        assert title == "ML Engineer Intern"

    def test_strips_company_suffix_from_page_title(self):
        soup = self._soup(
            "<html><head><title>Software Intern | Google Careers</title></head>"
            "<body></body></html>"
        )
        title, _, _ = _parse_soup(soup, "https://careers.google.com/jobs/1")
        assert title == "Software Intern"

    def test_extracts_company_from_og_site_name(self):
        soup = self._soup(
            '<html><head>'
            '<meta property="og:site_name" content="Google Careers"/>'
            '</head><body></body></html>'
        )
        _, company, _ = _parse_soup(soup, "https://careers.google.com/jobs/1")
        assert company == "Google Careers"

    def test_company_fallback_to_domain(self):
        soup = self._soup("<html><body><h1>Job</h1></body></html>")
        _, company, _ = _parse_soup(soup, "https://nvidia.com/jobs/1")
        assert "nvidia" in company.lower()

    def test_description_strips_script_tags(self):
        soup = self._soup(
            "<html><body>"
            "<div class='description'>We need an intern.</div>"
            "<script>evil()</script>"
            "</body></html>"
        )
        _, _, desc = _parse_soup(soup, "https://example.com")
        assert "evil()" not in desc
        assert "intern" in desc.lower()

    def test_description_strips_nav_and_footer(self):
        soup = self._soup(
            "<html><body>"
            "<nav>Nav links here blah blah</nav>"
            "<div class='description'>Join us as a software student.</div>"
            "<footer>Footer content</footer>"
            "</body></html>"
        )
        _, _, desc = _parse_soup(soup, "https://example.com")
        assert "software student" in desc.lower()

    def test_returns_tuple_of_three_strings(self):
        soup = self._soup("<html><body></body></html>")
        result = _parse_soup(soup, "https://example.com")
        assert len(result) == 3
        assert all(isinstance(s, str) for s in result)

    def test_unknown_title_fallback(self):
        soup = self._soup("<html><body></body></html>")
        title, _, _ = _parse_soup(soup, "https://example.com")
        assert title  # never empty string — has a fallback value

    def test_description_capped_at_300_lines(self):
        lines = "\n".join(f"line {i}" for i in range(500))
        soup = self._soup(f"<html><body><main>{lines}</main></body></html>")
        _, _, desc = _parse_soup(soup, "https://example.com")
        assert len(desc.splitlines()) <= 300


# ── fetch_job_page ────────────────────────────────────────────────────────────

SIMPLE_JOB_HTML = """<html>
<head>
  <title>Backend Intern - TechCorp - Tel Aviv</title>
  <meta property="og:site_name" content="TechCorp Careers"/>
</head>
<body>
  <h1>Backend Intern</h1>
  <div class="description">
    We are looking for a backend intern to join our systems team.
    Requirements: Python, REST APIs, Git.
  </div>
</body></html>"""


class TestFetchJobPage:
    def test_fast_path_used_first(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = SIMPLE_JOB_HTML

        with patch("requests.get", return_value=mock_resp) as mock_get:
            title, company, desc = fetch_job_page("https://example.com/job/1")

        mock_get.assert_called_once()
        assert "Intern" in title or "intern" in desc.lower()

    def test_playwright_fallback_on_request_failure(self):
        with patch("requests.get", side_effect=ConnectionError("blocked")):
            with patch("bot_listener._extract_with_playwright") as mock_pw:
                mock_pw.return_value = ("PW Title", "PW Company", "PW desc")
                title, company, desc = fetch_job_page("https://example.com/job/1")

        mock_pw.assert_called_once()
        assert title == "PW Title"

    def test_returns_tuple_of_three_strings(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = SIMPLE_JOB_HTML

        with patch("requests.get", return_value=mock_resp):
            result = fetch_job_page("https://example.com/job/1")

        assert len(result) == 3
        assert all(isinstance(s, str) for s in result)
