"""Manual job submission — generates tailored CV + cover letter and sends via email + Telegram.

Two modes:
  1. URL-only: set JOB_URL — the job page is scraped automatically.
  2. Full: set JOB_TITLE + COMPANY + JOB_DESCRIPTION (JOB_URL optional for the email link).
"""

import os
import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from cv_agent.tailor import generate_tailored_cv, generate_cover_letter
from cv_agent.pdf_renderer import render_pdf
from scraper.notifier import send_email, send_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = PROJECT_ROOT / "output"


def _sanitize(s: str) -> str:
    return "".join(c for c in s if c.isalnum())[:50]


def _scrape_url(url: str) -> tuple[str, str, str]:
    """Delegate to the bot_listener's generic scraper."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from bot_listener import fetch_job_page
    return fetch_job_page(url)


def main() -> None:
    url = os.environ.get("JOB_URL", "").strip()
    title = os.environ.get("JOB_TITLE", "").strip()
    company = os.environ.get("COMPANY", "").strip()
    description = os.environ.get("JOB_DESCRIPTION", "").strip()

    # URL-only mode: auto-scrape the job page
    if url and not (title and company and description):
        logger.info("URL-only mode — scraping: %s", url)
        title, company, description = _scrape_url(url)
        logger.info("Scraped: '%s' at '%s'", title, company)
    elif not (title and company and description):
        logger.error(
            "Provide either JOB_URL (for auto-scrape) "
            "or JOB_TITLE + COMPANY + JOB_DESCRIPTION."
        )
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    company_slug = _sanitize(company)
    title_slug = _sanitize(title)
    attachments: list[Path] = []

    cv_md = generate_tailored_cv(title, company, description)
    cv_path = render_pdf(cv_md, OUTPUT_DIR / f"OrAtias_CV_{company_slug}_{title_slug}.pdf")
    attachments.append(cv_path)

    cl_md = generate_cover_letter(title, company, description)
    cl_path = render_pdf(cl_md, OUTPUT_DIR / f"OrAtias_CoverLetter_{company_slug}_{title_slug}.pdf")
    attachments.append(cl_path)

    job = {"title": title, "company": company, "url": url or "Manual submission"}

    send_email([job], attachments)
    send_telegram([job], attachments)
    logger.info("Done.")


if __name__ == "__main__":
    main()
