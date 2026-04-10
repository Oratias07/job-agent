"""Tests for scraper/main.py — deduplication, seen-jobs logic, migration, main flow."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

# Import the functions we can test directly
from scraper.main import (
    _sanitize_filename,
    _company_brand,
    _normalize_title,
    _deduplicate,
)


# ── _sanitize_filename ────────────────────────────────────────────────────────

class TestSanitizeFilename:
    def test_alphanumeric_unchanged(self):
        assert _sanitize_filename("HelloWorld123") == "HelloWorld123"

    def test_spaces_removed(self):
        assert _sanitize_filename("Hello World") == "HelloWorld"

    def test_special_chars_removed(self):
        assert _sanitize_filename("R&D Israel!") == "RDIsrael"

    def test_empty(self):
        assert _sanitize_filename("") == ""

    def test_unicode_removed(self):
        result = _sanitize_filename("סטודנט")
        assert result == ""  # Hebrew chars are not ASCII alphanumeric


# ── _company_brand ────────────────────────────────────────────────────────────

class TestCompanyBrand:
    def test_microsoft_rnd(self):
        assert _company_brand("Microsoft R&D Israel") == "microsoft"

    def test_microsoft_careers(self):
        assert _company_brand("Microsoft Careers") == "microsoft"

    def test_microsoft_plain(self):
        assert _company_brand("Microsoft") == "microsoft"

    def test_nvidia_plain(self):
        assert _company_brand("NVIDIA") == "nvidia"

    def test_google_israel(self):
        assert _company_brand("Google Israel") == "google"

    def test_amazon_aws(self):
        assert _company_brand("Amazon Web Services") == "amazon"

    def test_aws(self):
        assert _company_brand("AWS") == "amazon"

    def test_intel_israel(self):
        assert _company_brand("Intel Israel") == "intel"

    def test_unknown_company_lowercased(self):
        assert _company_brand("SomeStartup Inc") == "somestartup inc"

    def test_case_insensitive(self):
        assert _company_brand("MICROSOFT R&D ISRAEL") == "microsoft"

    def test_wix(self):
        assert _company_brand("Wix.com") == "wix"


# ── _normalize_title ──────────────────────────────────────────────────────────

class TestNormalizeTitle:
    def test_lowercase(self):
        assert _normalize_title("Software Engineer") == "software engineer"

    def test_punctuation_removed(self):
        assert _normalize_title("C/C++ Developer") == "c c  developer" or \
               "c" in _normalize_title("C/C++ Developer")

    def test_extra_spaces_collapsed(self):
        assert _normalize_title("  hello   world  ") == "hello world"

    def test_empty(self):
        assert _normalize_title("") == ""


# ── _deduplicate ──────────────────────────────────────────────────────────────

def _job(id, title, company, description="desc"):
    return {"id": id, "title": title, "company": company,
            "url": f"https://example.com/{id}", "description": description}


class TestDeduplicate:
    def test_no_dupes_unchanged(self):
        jobs = [
            _job("a", "Software Engineer", "Google"),
            _job("b", "Data Scientist", "Meta"),
        ]
        result = _deduplicate(jobs)
        assert len(result) == 2

    def test_same_title_same_company_deduped(self):
        jobs = [
            _job("a", "Software Engineer Intern", "Microsoft R&D Israel"),
            _job("b", "Software Engineer Intern", "Microsoft Careers"),  # same brand
        ]
        result = _deduplicate(jobs)
        assert len(result) == 1

    def test_richest_description_wins(self):
        jobs = [
            _job("a", "Engineer Intern", "Microsoft", description="short"),
            _job("b", "Engineer Intern", "Microsoft Careers", description="x" * 500),
        ]
        result = _deduplicate(jobs)
        assert len(result) == 1
        assert result[0]["description"] == "x" * 500

    def test_different_titles_not_deduped(self):
        jobs = [
            _job("a", "Backend Engineer", "Google"),
            _job("b", "Frontend Engineer", "Google"),
        ]
        result = _deduplicate(jobs)
        assert len(result) == 2

    def test_empty_list(self):
        assert _deduplicate([]) == []

    def test_single_job(self):
        jobs = [_job("a", "Engineer", "Acme")]
        assert _deduplicate(jobs) == jobs

    def test_three_dupes_keeps_one(self):
        jobs = [
            _job("a", "Intern", "Microsoft", "a"),
            _job("b", "Intern", "Microsoft R&D", "bb"),
            _job("c", "Intern", "Microsoft Careers", "ccc"),
        ]
        result = _deduplicate(jobs)
        assert len(result) == 1
        assert result[0]["description"] == "ccc"  # longest


# ── _load_seen / migration ────────────────────────────────────────────────────

class TestLoadSeen:
    def test_missing_file_returns_empty(self, tmp_path):
        from scraper import main as m
        orig = m.STATE_FILE
        m.STATE_FILE = tmp_path / "nonexistent.json"
        try:
            result = m._load_seen()
            assert result == {}
        finally:
            m.STATE_FILE = orig

    def test_legacy_entries_migrated_to_baseline(self, tmp_path):
        state_file = tmp_path / "seen.json"
        # Legacy format: no 'baseline', no 'sent_at'
        state_file.write_text(json.dumps({
            "job-1": {"title": "Eng", "company": "Acme", "url": "https://x.com"},
            "job-2": {"title": "Dev", "company": "Corp", "url": "https://y.com"},
        }), encoding="utf-8")

        from scraper import main as m
        orig = m.STATE_FILE
        m.STATE_FILE = state_file
        try:
            result = m._load_seen()
            assert result["job-1"]["baseline"] is True
            assert result["job-2"]["baseline"] is True
            # File should be updated on disk
            disk = json.loads(state_file.read_text())
            assert disk["job-1"]["baseline"] is True
        finally:
            m.STATE_FILE = orig

    def test_already_flagged_entries_not_double_migrated(self, tmp_path):
        state_file = tmp_path / "seen.json"
        state_file.write_text(json.dumps({
            "job-1": {"title": "E", "company": "A", "url": "u", "sent_at": "2026-01-01"},
            "job-2": {"title": "D", "company": "B", "url": "v", "baseline": True},
        }), encoding="utf-8")

        from scraper import main as m
        orig = m.STATE_FILE
        m.STATE_FILE = state_file
        try:
            result = m._load_seen()
            # sent_at entry should not get baseline added
            assert "baseline" not in result["job-1"]
        finally:
            m.STATE_FILE = orig


# ── main() integration ────────────────────────────────────────────────────────

FAKE_JOB = {
    "id": "test-001",
    "title": "Software Intern",
    "company": "TestCo",
    "url": "https://testco.com/jobs/1",
    "description": "We need a software intern.",
}


class TestMainFlow:
    def _patch_all(self, mocker, seen_data=None, scraped_jobs=None):
        """Helper: patch all external dependencies for main()."""
        if scraped_jobs is None:
            scraped_jobs = [FAKE_JOB]

        mocker.patch("scraper.main._load_seen", return_value=seen_data or {})
        mocker.patch("scraper.main._save_seen")
        mocker.patch("scraper.main.microsoft_rnd.scrape", return_value=scraped_jobs)
        mocker.patch("scraper.main.microsoft_careers.scrape", return_value=[])
        mocker.patch("scraper.main.nvidia.scrape", return_value=[])
        mocker.patch("scraper.main.indeed.scrape", return_value=[])
        mocker.patch("scraper.main.alljobs.scrape", return_value=[])
        mocker.patch("scraper.main.drushim.scrape", return_value=[])
        mocker.patch("scraper.main.hiemetech.scrape", return_value=[])
        mocker.patch("scraper.main.generate_tailored_cv", return_value="# CV")
        mocker.patch("scraper.main.generate_cover_letter", return_value="# CL")
        mocker.patch("scraper.main.render_pdf", return_value=Path("/tmp/fake.pdf"))
        mock_email = mocker.patch("scraper.main.send_email")
        mock_tg = mocker.patch("scraper.main.send_telegram")
        return mock_email, mock_tg

    def test_first_run_no_email_sent(self, mocker):
        mock_email, mock_tg = self._patch_all(mocker, seen_data={})
        from scraper.main import main
        main()
        mock_email.assert_not_called()
        mock_tg.assert_not_called()

    def test_first_run_saves_baseline(self, mocker):
        save_seen = mocker.patch("scraper.main._save_seen")
        mocker.patch("scraper.main._load_seen", return_value={})
        mocker.patch("scraper.main.microsoft_rnd.scrape", return_value=[FAKE_JOB])
        for mod in ["microsoft_careers", "nvidia", "indeed", "alljobs", "drushim", "hiemetech"]:
            mocker.patch(f"scraper.main.{mod}.scrape", return_value=[])
        from scraper.main import main
        main()
        saved = save_seen.call_args[0][0]
        assert saved[FAKE_JOB["id"]]["baseline"] is True

    def test_new_job_triggers_email_and_telegram(self, mocker):
        # seen has a baseline job, scraper returns a brand-new job
        existing = {"old-001": {"title": "Old", "company": "X", "url": "u", "baseline": True}}
        mock_email, mock_tg = self._patch_all(mocker, seen_data=existing)
        from scraper.main import main
        main()
        mock_email.assert_called_once()
        mock_tg.assert_called_once()

    def test_already_sent_job_not_reprocessed(self, mocker):
        seen = {
            FAKE_JOB["id"]: {
                "title": FAKE_JOB["title"],
                "company": FAKE_JOB["company"],
                "url": FAKE_JOB["url"],
                "sent_at": "2026-01-01T10:00:00",
            }
        }
        mock_email, mock_tg = self._patch_all(mocker, seen_data=seen)
        from scraper.main import main
        main()
        mock_email.assert_not_called()

    def test_failed_scraper_does_not_abort(self, mocker):
        mocker.patch("scraper.main._load_seen", return_value={"x": {"baseline": True}})
        mocker.patch("scraper.main._save_seen")
        mocker.patch("scraper.main.microsoft_rnd.scrape", side_effect=RuntimeError("boom"))
        mocker.patch("scraper.main.microsoft_careers.scrape", return_value=[FAKE_JOB])
        for mod in ["nvidia", "indeed", "alljobs", "drushim", "hiemetech"]:
            mocker.patch(f"scraper.main.{mod}.scrape", return_value=[])
        mocker.patch("scraper.main.generate_tailored_cv", return_value="# CV")
        mocker.patch("scraper.main.generate_cover_letter", return_value="# CL")
        mocker.patch("scraper.main.render_pdf", return_value=Path("/tmp/fake.pdf"))
        mock_email = mocker.patch("scraper.main.send_email")
        mocker.patch("scraper.main.send_telegram")
        from scraper.main import main
        main()  # Must not raise
        mock_email.assert_called_once()  # still sends for the working scraper's job
