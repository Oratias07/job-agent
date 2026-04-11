"""Convert Markdown content to styled PDF using Playwright (Chromium)."""

import html as html_lib
import logging
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

CSS = """
@page {
    size: A4;
    margin: 1.5cm 2cm;
}
body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    font-size: 10.5pt;
    line-height: 1.45;
    color: #1a1a1a;
}
h1 {
    font-size: 20pt;
    margin-bottom: 2pt;
    color: #0a0a0a;
    border-bottom: 2px solid #2b5797;
    padding-bottom: 4pt;
}
h2 {
    font-size: 12pt;
    color: #2b5797;
    margin-top: 14pt;
    margin-bottom: 4pt;
    text-transform: uppercase;
    letter-spacing: 0.5pt;
    border-bottom: 1px solid #ccc;
    padding-bottom: 2pt;
}
h3 {
    font-size: 10.5pt;
    margin-top: 8pt;
    margin-bottom: 2pt;
    color: #1a1a1a;
}
ul {
    margin-top: 2pt;
    margin-bottom: 4pt;
    padding-left: 16pt;
}
li {
    margin-bottom: 2pt;
}
a {
    color: #2b5797;
    text-decoration: none;
}
p {
    margin-top: 2pt;
    margin-bottom: 4pt;
}
strong {
    color: #0a0a0a;
}
"""


_SAFE_URL_SCHEMES = ("https://", "http://", "mailto:")


def _safe_url(url: str) -> str:
    """Allow only http/https/mailto URLs; replace anything else with '#'."""
    stripped = url.strip()
    if any(stripped.lower().startswith(scheme) for scheme in _SAFE_URL_SCHEMES):
        return html_lib.escape(stripped, quote=True)
    return "#"


def _markdown_to_html(md: str) -> str:
    """Minimal Markdown-to-HTML conversion with HTML-escaping for safety."""
    lines = md.split("\n")
    html_lines = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Headings — escape content before inserting into tags
        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3>{html_lib.escape(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2>{html_lib.escape(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h1>{html_lib.escape(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{html_lib.escape(stripped[2:])}</li>")
        elif stripped == "":
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<p>{html_lib.escape(stripped)}</p>")

    if in_list:
        html_lines.append("</ul>")

    result = "\n".join(html_lines)

    # Inline formatting — applied AFTER escaping, so we work on escaped text.
    # **bold** and *italic* delimiters are not HTML-special so they survive escaping unchanged.
    result = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", result)
    result = re.sub(r"\*(.+?)\*", r"<em>\1</em>", result)

    # Links: text is already escaped; URL goes through _safe_url.
    # After html.escape, square brackets and parens are unchanged.
    result = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{_safe_url(m.group(2))}">{m.group(1)}</a>',
        result,
    )

    return result


def render_pdf(markdown_content: str, output_path: str | Path) -> Path:
    """Render Markdown string to PDF. Returns the output path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    body_html = _markdown_to_html(markdown_content)
    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body>{body_html}</body></html>"""

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(full_html, wait_until="domcontentloaded")
        page.pdf(
            path=str(output_path),
            format="A4",
            margin={"top": "1.5cm", "bottom": "1.5cm", "left": "2cm", "right": "2cm"},
            print_background=True,
        )
        browser.close()

    logger.info("Rendered PDF: %s", output_path)
    return output_path
