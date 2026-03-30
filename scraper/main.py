"""Job Monitor Agent — scrapes job sites, detects new postings, triggers CV tailoring and email."""

import json
import logging
import re
import sys
from pathlib import Path

# Ensure project root is on sys.path so imports work from any CWD
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scraper.sites import microsoft_rnd, microsoft_careers, nvidia
from cv_agent.tailor import generate_tailored_cv, generate_cover_letter
from cv_agent.pdf_renderer import render_pdf
from scraper.notifier import send_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATE_FILE = PROJECT_ROOT / "state" / "seen_jobs.json"
OUTPUT_DIR = PROJECT_ROOT / "output"


def _load_seen() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def _save_seen(seen: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(seen, indent=2, ensure_ascii=False), encoding="utf-8")


def _sanitize_filename(s: str) -> str:
    """Remove non-alphanumeric chars (except underscores) for filenames."""
    return re.sub(r"[^A-Za-z0-9]+", "", s)


def main() -> None:
    seen = _load_seen()
    is_first_run = len(seen) == 0

    # --- Scrape all sources ---
    all_jobs: list[dict] = []
    for name, scrape_fn in [
        ("Microsoft R&D Israel", microsoft_rnd.scrape),
        ("Microsoft Careers", microsoft_careers.scrape),
        ("NVIDIA", nvidia.scrape),
    ]:
        try:
            jobs = scrape_fn()
            all_jobs.extend(jobs)
            logger.info("%s returned %d jobs", name, len(jobs))
        except Exception:
            logger.exception("Scraper failed: %s — continuing", name)

    # --- Detect new jobs ---
    new_jobs = [j for j in all_jobs if j["id"] not in seen]

    # Update seen state
    for job in all_jobs:
        seen[job["id"]] = {
            "title": job["title"],
            "company": job["company"],
            "url": job["url"],
        }
    _save_seen(seen)

    if is_first_run:
        logger.info("First run — saved %d jobs as baseline. No email sent.", len(all_jobs))
        return

    if not new_jobs:
        logger.info("No new jobs found. Nothing to do.")
        return

    logger.info("Found %d new job(s). Generating tailored documents...", len(new_jobs))

    # --- Generate tailored CV + cover letter per new job ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    attachments: list[Path] = []

    for job in new_jobs:
        company_slug = _sanitize_filename(job["company"])
        title_slug = _sanitize_filename(job["title"])

        try:
            cv_md = generate_tailored_cv(job["title"], job["company"], job["description"])
            cv_path = render_pdf(cv_md, OUTPUT_DIR / f"OrAtias_CV_{company_slug}_{title_slug}.pdf")
            attachments.append(cv_path)
        except Exception:
            logger.exception("Failed to generate CV for: %s at %s", job["title"], job["company"])

        try:
            cl_md = generate_cover_letter(job["title"], job["company"], job["description"])
            cl_path = render_pdf(cl_md, OUTPUT_DIR / f"OrAtias_CoverLetter_{company_slug}_{title_slug}.pdf")
            attachments.append(cl_path)
        except Exception:
            logger.exception("Failed to generate cover letter for: %s at %s", job["title"], job["company"])

    # --- Send email ---
    if attachments:
        try:
            send_email(new_jobs, attachments)
        except Exception:
            logger.exception("Failed to send email")
    else:
        logger.warning("No PDFs generated — skipping email.")


if __name__ == "__main__":
    main()
