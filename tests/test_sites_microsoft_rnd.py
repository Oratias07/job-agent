"""Tests for scraper/sites/microsoft_rnd.py"""

import pytest
from unittest.mock import patch, MagicMock
from scraper.sites.microsoft_rnd import _matches_keywords, scrape


# ── _matches_keywords ─────────────────────────────────────────────────────────

class TestMatchesKeywords:
    def test_student_matches(self):
        assert _matches_keywords("student position") is True

    def test_intern_matches(self):
        assert _matches_keywords("Software Intern") is True

    def test_internship_matches(self):
        assert _matches_keywords("summer internship") is True

    def test_hebrew_student(self):
        assert _matches_keywords("סטודנט") is True

    def test_hebrew_training(self):
        assert _matches_keywords("התמחות") is True

    def test_senior_no_match(self):
        assert _matches_keywords("Senior Principal Engineer") is False

    def test_case_insensitive(self):
        assert _matches_keywords("INTERN") is True


# ── scrape ────────────────────────────────────────────────────────────────────

STRUCTURED_HTML = """<html><body>
<article>
  <a href="/JobDetails?JobSeqNo=123">Software Engineering Student</a>
  <p>Join our team as a student intern. Work on cutting-edge systems.</p>
</article>
<article>
  <a href="/JobDetails?JobSeqNo=456">Senior Software Engineer</a>
  <p>10+ years of experience required. Not for students.</p>
</article>
</body></html>"""

LINK_ONLY_HTML = """<html><body>
<a href="/JobDetails?JobSeqNo=789">Internship - AI Team</a>
</body></html>"""

EMPTY_HTML = "<html><body></body></html>"


class TestScrape:
    def _mock_get(self, html: str):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = html
        return mock_resp

    def test_returns_only_matching_jobs(self):
        with patch("requests.get", return_value=self._mock_get(STRUCTURED_HTML)):
            jobs = scrape()
        titles = [j["title"] for j in jobs]
        assert any("Student" in t or "Intern" in t for t in titles)
        assert not any("Senior" in t and "Principal" in t for t in titles)

    def test_job_has_required_keys(self):
        with patch("requests.get", return_value=self._mock_get(STRUCTURED_HTML)):
            jobs = scrape()
        for job in jobs:
            assert "id" in job
            assert "title" in job
            assert "company" in job
            assert "url" in job
            assert "description" in job

    def test_company_is_microsoft_rnd(self):
        with patch("requests.get", return_value=self._mock_get(STRUCTURED_HTML)):
            jobs = scrape()
        for job in jobs:
            assert job["company"] == "Microsoft R&D Israel"

    def test_url_absolutified(self):
        with patch("requests.get", return_value=self._mock_get(STRUCTURED_HTML)):
            jobs = scrape()
        for job in jobs:
            assert job["url"].startswith("http")

    def test_fallback_link_scraper(self):
        """When no structured cards found, falls back to link scanning."""
        with patch("requests.get", return_value=self._mock_get(LINK_ONLY_HTML)):
            jobs = scrape()
        assert len(jobs) >= 1
        assert any("Internship" in j["title"] for j in jobs)

    def test_empty_page_returns_empty_list(self):
        with patch("requests.get", return_value=self._mock_get(EMPTY_HTML)):
            jobs = scrape()
        assert jobs == []

    def test_network_failure_returns_empty(self):
        with patch("requests.get", side_effect=ConnectionError("timeout")):
            jobs = scrape()
        assert jobs == []

    def test_ids_are_stable_for_same_content(self):
        """Same title+url should always produce the same ID."""
        with patch("requests.get", return_value=self._mock_get(STRUCTURED_HTML)):
            jobs1 = scrape()
        with patch("requests.get", return_value=self._mock_get(STRUCTURED_HTML)):
            jobs2 = scrape()
        assert [j["id"] for j in jobs1] == [j["id"] for j in jobs2]
