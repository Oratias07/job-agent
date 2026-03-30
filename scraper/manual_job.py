"""Manual job submission — generates tailored CV + cover letter and emails them."""

import os
import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from cv_agent.tailor import generate_tailored_cv, generate_cover_letter
from cv_agent.pdf_renderer import render_pdf
from scraper.notifier import send_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = PROJECT_ROOT / "output"


def _sanitize(s: str) -> str:
    return "".join(c for c in s if c.isalnum())


def main() -> None:
    title = os.environ["JOB_TITLE"]
    company = os.environ["COMPANY"]
    url = os.environ.get("JOB_URL", "")
    description = os.environ["JOB_DESCRIPTION"]

    logger.info("Manual job: %s at %s", title, company)

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
    logger.info("Done — email sent.")


if __name__ == "__main__":
    main()
