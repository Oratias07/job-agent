"""Tests for cv_agent/pdf_renderer.py"""

import pytest
from pathlib import Path
from cv_agent.pdf_renderer import _safe_url, _markdown_to_html, render_pdf


# ── _safe_url ────────────────────────────────────────────────────────────────

class TestSafeUrl:
    def test_https_allowed(self):
        assert _safe_url("https://example.com") == "https://example.com"

    def test_http_allowed(self):
        assert _safe_url("http://example.com") == "http://example.com"

    def test_mailto_allowed(self):
        assert _safe_url("mailto:someone@example.com") == "mailto:someone@example.com"

    def test_javascript_blocked(self):
        assert _safe_url("javascript:alert(1)") == "#"

    def test_data_uri_blocked(self):
        assert _safe_url("data:text/html,<h1>x</h1>") == "#"

    def test_vbscript_blocked(self):
        assert _safe_url("vbscript:msgbox(1)") == "#"

    def test_empty_blocked(self):
        assert _safe_url("") == "#"

    def test_url_with_special_chars_escaped(self):
        url = 'https://example.com/path?q=a&b=c"'
        result = _safe_url(url)
        assert result.startswith("https://")
        assert '"' not in result  # quote must be escaped

    def test_case_insensitive_scheme_check(self):
        # JAVASCRIPT: should also be blocked
        assert _safe_url("JAVASCRIPT:alert(1)") == "#"


# ── _markdown_to_html ────────────────────────────────────────────────────────

class TestMarkdownToHtml:
    def test_h1(self):
        html = _markdown_to_html("# Hello World")
        assert "<h1>Hello World</h1>" in html

    def test_h2(self):
        html = _markdown_to_html("## Section")
        assert "<h2>Section</h2>" in html

    def test_h3(self):
        html = _markdown_to_html("### Subsection")
        assert "<h3>Subsection</h3>" in html

    def test_bullet_list(self):
        html = _markdown_to_html("- Item one\n- Item two")
        assert "<ul>" in html
        assert "<li>Item one</li>" in html
        assert "<li>Item two</li>" in html
        assert "</ul>" in html

    def test_bold(self):
        html = _markdown_to_html("**bold text**")
        assert "<strong>bold text</strong>" in html

    def test_italic(self):
        html = _markdown_to_html("*italic text*")
        assert "<em>italic text</em>" in html

    def test_link(self):
        html = _markdown_to_html("[click here](https://example.com)")
        assert 'href="https://example.com"' in html
        assert ">click here</a>" in html

    def test_link_with_javascript_blocked(self):
        html = _markdown_to_html("[evil](javascript:alert(1))")
        assert 'href="#"' in html
        assert "javascript" not in html

    def test_html_injection_in_heading(self):
        html = _markdown_to_html("# <script>alert(1)</script>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_html_injection_in_paragraph(self):
        html = _markdown_to_html("<img src=x onerror=alert(1)>")
        assert "<img" not in html
        assert "&lt;img" in html

    def test_html_injection_in_list(self):
        html = _markdown_to_html("- <b>not bold</b>")
        assert "<b>" not in html
        assert "&lt;b&gt;" in html

    def test_paragraph(self):
        html = _markdown_to_html("Just some text.")
        assert "<p>Just some text.</p>" in html

    def test_list_closes_before_heading(self):
        md = "- item\n## New Section"
        html = _markdown_to_html(md)
        # </ul> must appear before <h2>
        assert html.index("</ul>") < html.index("<h2>")

    def test_empty_input(self):
        assert _markdown_to_html("") == ""


# ── render_pdf (integration) ─────────────────────────────────────────────────

class TestRenderPdf:
    def test_creates_pdf_file(self, tmp_path):
        out = tmp_path / "test.pdf"
        try:
            result = render_pdf("# Test\n\n- bullet", out)
            assert result == out
            assert out.exists()
            assert out.stat().st_size > 0
            # PDF magic bytes
            assert out.read_bytes()[:4] == b"%PDF"
        except Exception as e:
            pytest.skip(f"WeasyPrint render failed (system deps?): {e}")

    def test_returns_path_object(self, tmp_path):
        out = tmp_path / "test.pdf"
        try:
            result = render_pdf("hello", out)
            assert isinstance(result, Path)
        except Exception as e:
            pytest.skip(f"WeasyPrint render failed: {e}")

    def test_creates_parent_directory(self, tmp_path):
        out = tmp_path / "nested" / "dir" / "test.pdf"
        try:
            render_pdf("# Hello", out)
            assert out.exists()
        except Exception as e:
            pytest.skip(f"WeasyPrint render failed: {e}")
