"""Tests for scraper/notifier.py"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from scraper.notifier import _tg_escape, send_telegram, send_email


# ── _tg_escape ────────────────────────────────────────────────────────────────

class TestTgEscape:
    def test_plain_text_unchanged(self):
        assert _tg_escape("Hello World") == "Hello World"

    def test_dot_escaped(self):
        assert "\\." in _tg_escape("hello.")

    def test_hyphen_escaped(self):
        assert "\\-" in _tg_escape("step-by-step")

    def test_underscore_escaped(self):
        assert "\\_" in _tg_escape("snake_case")

    def test_asterisk_escaped(self):
        assert "\\*" in _tg_escape("2 * 2")

    def test_parentheses_escaped(self):
        result = _tg_escape("(test)")
        assert "\\(" in result
        assert "\\)" in result

    def test_exclamation_escaped(self):
        assert "\\!" in _tg_escape("Hello!")

    def test_empty_string(self):
        assert _tg_escape("") == ""


# ── send_email ────────────────────────────────────────────────────────────────

class TestSendEmail:
    def _make_job(self, title="Intern", company="Acme", url="https://acme.com/job/1"):
        return {"title": title, "company": company, "url": url}

    def _make_pdf(self, tmp_path, name="cv.pdf") -> Path:
        p = tmp_path / name
        p.write_bytes(b"%PDF-1.4 fake")
        return p

    @pytest.fixture(autouse=True)
    def email_env(self, monkeypatch):
        monkeypatch.setenv("GMAIL_USER", "chamyproject@gmail.com")
        monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")

    def test_raises_if_no_password(self, monkeypatch):
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
        with pytest.raises(ValueError, match="GMAIL_APP_PASSWORD"):
            send_email([self._make_job()], [])

    def test_no_jobs_returns_early(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "testpass")
        # Should return silently without opening SMTP
        with patch("smtplib.SMTP_SSL") as mock_smtp:
            send_email([], [])
            mock_smtp.assert_not_called()

    def test_smtp_login_called(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "testpass")
        pdf = self._make_pdf(tmp_path)

        mock_server = MagicMock()
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP_SSL", return_value=mock_server):
            send_email([self._make_job()], [pdf])

        mock_server.login.assert_called_once_with("chamyproject@gmail.com", "testpass")

    def test_subject_contains_company_and_count(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "testpass")
        pdf = self._make_pdf(tmp_path)
        captured_msg = {}

        mock_server = MagicMock()
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)
        def capture_send(msg):
            captured_msg["subject"] = msg["Subject"]
        mock_server.send_message.side_effect = capture_send

        with patch("smtplib.SMTP_SSL", return_value=mock_server):
            send_email([self._make_job(company="Google")], [pdf])

        assert "Google" in captured_msg["subject"]
        assert "[1]" in captured_msg["subject"]

    def test_pdf_attached(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "testpass")
        pdf = self._make_pdf(tmp_path, "OrAtias_CV_Test.pdf")
        captured_msg = {}

        mock_server = MagicMock()
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)
        def capture_send(msg):
            captured_msg["msg"] = msg
        mock_server.send_message.side_effect = capture_send

        with patch("smtplib.SMTP_SSL", return_value=mock_server):
            send_email([self._make_job()], [pdf])

        raw = captured_msg["msg"].as_string()
        assert "OrAtias_CV_Test.pdf" in raw


# ── send_telegram ─────────────────────────────────────────────────────────────

class TestSendTelegram:
    def _make_job(self):
        return {"title": "Intern", "company": "Acme", "url": "https://acme.com/job/1"}

    def _make_pdf(self, tmp_path, name="cv.pdf") -> Path:
        p = tmp_path / name
        p.write_bytes(b"%PDF-1.4 fake")
        return p

    def test_skips_if_no_token(self, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        pdf = self._make_pdf(tmp_path)
        with patch("requests.post") as mock_post:
            send_telegram([self._make_job()], [pdf])
            mock_post.assert_not_called()

    def test_sends_message_and_document(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
        pdf = self._make_pdf(tmp_path, "OrAtias_CV.pdf")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            send_telegram([self._make_job()], [pdf])

        # First call: sendMessage; second: sendDocument
        assert mock_post.call_count == 2
        first_url = mock_post.call_args_list[0][0][0]
        assert "sendMessage" in first_url
        second_url = mock_post.call_args_list[1][0][0]
        assert "sendDocument" in second_url

    def test_message_contains_job_title(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
        pdf = self._make_pdf(tmp_path)

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"ok": True}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            send_telegram([self._make_job()], [pdf])

        msg_data = mock_post.call_args_list[0][1]["data"]
        # Title should appear (possibly escaped) in the message text
        assert "Intern" in msg_data["text"]

    def test_document_failure_does_not_raise(self, monkeypatch, tmp_path):
        """A failed document upload should log and continue, not raise."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
        pdf = self._make_pdf(tmp_path)

        call_count = 0
        def flaky_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            if call_count == 1:
                # sendMessage succeeds
                mock_resp.raise_for_status = MagicMock()
                mock_resp.json.return_value = {"ok": True}
            else:
                # sendDocument fails
                mock_resp.raise_for_status.side_effect = Exception("upload failed")
            return mock_resp

        with patch("requests.post", side_effect=flaky_post):
            send_telegram([self._make_job()], [pdf])  # must not raise
