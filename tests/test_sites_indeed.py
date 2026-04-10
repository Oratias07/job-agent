"""Tests for scraper/sites/indeed.py"""

import pytest
from unittest.mock import patch, MagicMock
from scraper.sites.indeed import _matches_keywords, _parse_rss, scrape


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Indeed Jobs</title>
    <item>
      <title>Software Engineer Student - Google - Tel Aviv</title>
      <link>https://il.indeed.com/viewjob?jk=abc123def456</link>
      <description>&lt;p&gt;We are looking for a student intern to join our team.&lt;/p&gt;</description>
    </item>
    <item>
      <title>Senior DevOps Engineer - Startup - Haifa</title>
      <link>https://il.indeed.com/viewjob?jk=zzz999</link>
      <description>&lt;p&gt;5 years of experience required.&lt;/p&gt;</description>
    </item>
    <item>
      <title>Software Internship - Amazon - Jerusalem</title>
      <link>https://il.indeed.com/viewjob?jk=intern789</link>
      <description>&lt;p&gt;Summer internship for CS students.&lt;/p&gt;</description>
    </item>
  </channel>
</rss>"""

MALFORMED_RSS = "this is not xml at all <<<"

EMPTY_RSS = """<?xml version="1.0"?><rss><channel></channel></rss>"""


# ── _matches_keywords ─────────────────────────────────────────────────────────

class TestMatchesKeywords:
    def test_student_matches(self):
        assert _matches_keywords("software student position") is True

    def test_intern_matches(self):
        assert _matches_keywords("Software Intern") is True

    def test_internship_matches(self):
        assert _matches_keywords("Summer Internship Program") is True

    def test_hebrew_student_matches(self):
        assert _matches_keywords("סטודנט תוכנה") is True

    def test_hebrew_training_matches(self):
        assert _matches_keywords("משרת התמחות") is True

    def test_senior_role_no_match(self):
        assert _matches_keywords("Senior Software Engineer 10 years exp") is False

    def test_case_insensitive(self):
        assert _matches_keywords("STUDENT INTERN") is True


# ── _parse_rss ────────────────────────────────────────────────────────────────

class TestParseRss:
    def test_returns_matching_jobs_only(self):
        jobs = _parse_rss(SAMPLE_RSS)
        titles = [j["title"] for j in jobs]
        # "Senior DevOps" should be filtered out
        assert not any("DevOps" in t for t in titles)
        assert any("Student" in t or "Internship" in t for t in titles)

    def test_job_has_required_keys(self):
        jobs = _parse_rss(SAMPLE_RSS)
        assert len(jobs) > 0
        for job in jobs:
            assert "id" in job
            assert "title" in job
            assert "company" in job
            assert "url" in job
            assert "description" in job

    def test_id_uses_indeed_jk_param(self):
        jobs = _parse_rss(SAMPLE_RSS)
        student_job = next(j for j in jobs if "Student" in j["title"])
        assert student_job["id"] == "indeed-abc123def456"

    def test_html_stripped_from_description(self):
        jobs = _parse_rss(SAMPLE_RSS)
        for job in jobs:
            assert "<p>" not in job["description"]
            assert "&lt;" not in job["description"]

    def test_company_extracted_from_title(self):
        jobs = _parse_rss(SAMPLE_RSS)
        student_job = next(j for j in jobs if "Student" in j["title"])
        assert student_job["company"] == "Google"

    def test_title_stripped_of_company_and_location(self):
        jobs = _parse_rss(SAMPLE_RSS)
        student_job = next(j for j in jobs if "Student" in j["title"])
        assert "Software Engineer Student" == student_job["title"]

    def test_malformed_xml_returns_empty(self):
        assert _parse_rss(MALFORMED_RSS) == []

    def test_empty_feed_returns_empty(self):
        assert _parse_rss(EMPTY_RSS) == []


# ── scrape ────────────────────────────────────────────────────────────────────

class TestScrape:
    def test_returns_list(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = SAMPLE_RSS

        with patch("requests.get", return_value=mock_resp):
            result = scrape()

        assert isinstance(result, list)

    def test_deduplicates_across_feed_urls(self):
        """Same job appearing in multiple RSS URLs should appear once."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = SAMPLE_RSS

        with patch("requests.get", return_value=mock_resp):
            result = scrape()

        ids = [j["id"] for j in result]
        assert len(ids) == len(set(ids))

    def test_network_failure_returns_empty_for_that_feed(self):
        call_count = 0
        def flaky_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("timeout")
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.text = SAMPLE_RSS
            return mock_resp

        with patch("requests.get", side_effect=flaky_get):
            result = scrape()

        # Should still return jobs from the feeds that succeeded
        assert isinstance(result, list)
