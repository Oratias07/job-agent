"""Shared pytest fixtures and path setup."""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# Ensure project root is importable regardless of where pytest is invoked from
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Stub WeasyPrint system library before any module imports it ───────────────
# WeasyPrint requires GTK (libgobject, pango, etc.) which may not be installed
# locally. Stub the package so unit tests can import pdf_renderer without error.
# The render_pdf integration tests will skip themselves if WeasyPrint can't render.
def _make_weasyprint_stub():
    stub = types.ModuleType("weasyprint")
    mock_html = MagicMock()
    mock_html.return_value.write_pdf = MagicMock()
    stub.HTML = mock_html
    return stub

if "weasyprint" not in sys.modules:
    try:
        import weasyprint  # noqa: F401 — try the real thing first
    except OSError:
        sys.modules["weasyprint"] = _make_weasyprint_stub()
