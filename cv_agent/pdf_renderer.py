"""Convert Markdown content to styled PDF using WeasyPrint."""

import logging
import re
from pathlib import Path
from weasyprint import HTML

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


def _markdown_to_html(md: str) -> str:
    """Minimal Markdown-to-HTML conversion (no external dependency)."""
    lines = md.split("\n")
    html_lines = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Headings
        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{stripped[2:]}</li>")
        elif stripped == "":
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<p>{stripped}</p>")

    if in_list:
        html_lines.append("</ul>")

    html = "\n".join(html_lines)

    # Inline formatting
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
    html = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        html,
    )

    return html


def render_pdf(markdown_content: str, output_path: str | Path) -> Path:
    """Render Markdown string to PDF. Returns the output path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    body_html = _markdown_to_html(markdown_content)
    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body>{body_html}</body></html>"""

    HTML(string=full_html).write_pdf(str(output_path))
    logger.info("Rendered PDF: %s", output_path)
    return output_path
