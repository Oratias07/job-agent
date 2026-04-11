"""Job Monitor Agent — scrapes job sites, detects new postings, triggers CV tailoring and email."""

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path so imports work from any CWD
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scraper.sites import microsoft_rnd, microsoft_careers, nvidia, indeed, alljobs, drushim, hiemetech
from cv_agent.tailor import generate_tailored_cv, generate_cover_letter
from cv_agent.pdf_renderer import render_pdf
from scraper.notifier import send_email, send_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATE_FILE = PROJECT_ROOT / "state" / "seen_jobs.json"
OUTPUT_DIR = PROJECT_ROOT / "output"


def _load_seen() -> dict:
    if not STATE_FILE.exists():
        return {}
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    # Migration: entries written by old code have no 'sent_at' or 'baseline'.
    # Treat them as baseline so they're never re-processed as new jobs.
    migrated = False
    for entry in data.values():
        if "sent_at" not in entry and "baseline" not in entry:
            entry["baseline"] = True
            migrated = True
    if migrated:
        STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Migrated seen_jobs.json — marked legacy entries as baseline.")
    return data


def _save_seen(seen: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(seen, indent=2, ensure_ascii=False), encoding="utf-8")


def _sanitize_filename(s: str) -> str:
    """Remove non-alphanumeric chars (except underscores) for filenames."""
    return re.sub(r"[^A-Za-z0-9]+", "", s)


# ---------------------------------------------------------------------------
# Cross-source deduplication
# ---------------------------------------------------------------------------

_COMPANY_ALIASES: dict[str, list[str]] = {
    "microsoft": ["microsoft r&d israel", "microsoft r&d", "microsoft careers", "microsoft"],
    "nvidia": ["nvidia"],
    "google": ["google israel", "google"],
    "amazon": ["amazon web services", "aws", "amazon"],
    "intel": ["intel israel", "intel"],
    "meta": ["meta platforms", "facebook", "meta"],
    "apple": ["apple"],
    "salesforce": ["salesforce"],
    "amdocs": ["amdocs"],
    "checkpoint": ["check point", "checkpoint"],
    "wix": ["wix.com", "wix"],
}


def _company_brand(company: str) -> str:
    """Normalize company name to a canonical brand key."""
    lower = company.lower().strip()
    for brand, aliases in _COMPANY_ALIASES.items():
        if any(lower == alias or lower.startswith(alias) for alias in sorted(aliases, key=len, reverse=True)):
            return brand
    return lower


def _normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    t = title.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------
# Relevance filtering — keep only hi-tech student/intern roles
# ---------------------------------------------------------------------------

# Title patterns that clearly indicate a non-tech role (regex, case-insensitive)
_NON_TECH_TITLE_PATTERNS: list[str] = [
    r"\bhr\b", r"human resources?", r"hr generalist", r"hr manager",
    r"מנהל משמרת", r"מלצר", r"מלצרית", r"שף", r"טבח", r"בריסטה", r"ברמן",
    r"קופאי", r"קופאית", r"מוכר(?!\s+טכני)", r"מוכרת",
    r"shift manager", r"waiter", r"waitress", r"barista", r"chef",
    r"restaurant manager", r"hospitality",
]

# At least one of these must appear in the title for jobs from general boards
_TECH_TITLE_KEYWORDS: list[str] = [
    "developer", "engineer", "software", "data", "backend", "frontend",
    "fullstack", "full-stack", "full stack", "machine learning", "cloud",
    "devops", "dev ops", "cyber", "security", "algorithm", "research",
    "programmer", "architect", "analytics", "infrastructure", "platform",
    "embedded", "firmware", "mobile", "android", "ios", "web dev",
    # Hebrew
    "מפתח", "מפתחת", "תוכנה", "נתונים", "ענן", "בינה מלאכותית",
    "קיברנט", "אנדרואיד", "מערכות", "אבטחה", "תשתיות",
]

# Companies with curated tech-only scraping — skip the tech-keyword title check
_CURATED_TECH_COMPANIES: set[str] = {"microsoft r&d israel", "microsoft", "nvidia"}


def _is_relevant_job(job: dict) -> bool:
    """Return False for clearly non-tech or off-target roles."""
    title_lower = job["title"].lower()

    # Block non-tech roles from any source
    for pattern in _NON_TECH_TITLE_PATTERNS:
        if re.search(pattern, title_lower, re.IGNORECASE):
            logger.info("Filtered non-tech job: '%s' at %s", job["title"], job["company"])
            return False

    # For general job boards, require at least one tech keyword in the title
    if job["company"].lower() not in _CURATED_TECH_COMPANIES:
        if not any(kw in title_lower for kw in _TECH_TITLE_KEYWORDS):
            logger.info(
                "Filtered job with no tech title keyword: '%s' at %s",
                job["title"], job["company"],
            )
            return False

    return True


def _deduplicate(jobs: list[dict]) -> list[dict]:
    """Remove duplicate jobs across sources.

    Two jobs are considered duplicates when they share a normalized (title, company-brand) key.
    Among duplicates, the one with the longest description is kept (most context for CV gen).
    """
    # Sort by description length descending so the richest entry wins
    sorted_jobs = sorted(jobs, key=lambda j: len(j.get("description", "")), reverse=True)
    seen_keys: set[tuple[str, str]] = set()
    unique: list[dict] = []
    dupes = 0
    for job in sorted_jobs:
        key = (_normalize_title(job["title"]), _company_brand(job["company"]))
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(job)
        else:
            dupes += 1
    if dupes:
        logger.info("Deduplication: removed %d duplicate job(s) across sources", dupes)
    return unique


def main() -> None:
    seen = _load_seen()
    is_first_run = len(seen) == 0

    # --- Scrape all sources ---
    all_jobs: list[dict] = []
    for name, scrape_fn in [
        ("Microsoft R&D Israel", microsoft_rnd.scrape),
        ("Microsoft Careers", microsoft_careers.scrape),
        ("NVIDIA", nvidia.scrape),
        ("Indeed Israel", indeed.scrape),
        ("AllJobs", alljobs.scrape),
        ("Drushim", drushim.scrape),
        ("HiremeTech", hiemetech.scrape),
    ]:
        try:
            jobs = scrape_fn()
            all_jobs.extend(jobs)
            logger.info("%s returned %d jobs", name, len(jobs))
        except Exception:
            logger.exception("Scraper failed: %s — continuing", name)

    # --- Deduplicate across sources ---
    pre_dedup = len(all_jobs)
    all_jobs = _deduplicate(all_jobs)
    logger.info("Total after deduplication: %d (was %d)", len(all_jobs), pre_dedup)

    # --- Relevance filter — drop non-tech / off-target roles ---
    pre_filter = len(all_jobs)
    all_jobs = [j for j in all_jobs if _is_relevant_job(j)]
    filtered = pre_filter - len(all_jobs)
    if filtered:
        logger.info("Relevance filter: dropped %d irrelevant job(s)", filtered)

    # --- Detect new jobs ---
    # Exclude jobs that: (a) were already sent, OR (b) are from the first-run baseline.
    # Jobs that were scraped but failed to send (no sent_at, no baseline) are retried.
    new_jobs = [
        j for j in all_jobs
        if not (
            seen.get(j["id"], {}).get("sent_at")
            or seen.get(j["id"], {}).get("baseline")
        )
    ]

    # Update seen state — add any newly discovered jobs; preserve existing metadata.
    for job in all_jobs:
        if job["id"] not in seen:
            seen[job["id"]] = {
                "title": job["title"],
                "company": job["company"],
                "url": job["url"],
            }

    if is_first_run:
        # Mark all as baseline so they're never re-processed as "new"
        for job in all_jobs:
            seen[job["id"]]["baseline"] = True
        _save_seen(seen)
        logger.info("First run — saved %d jobs as baseline. No email sent.", len(all_jobs))
        return

    _save_seen(seen)

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

    # --- Send notifications ---
    if attachments:
        email_ok = False
        try:
            send_email(new_jobs, attachments)
            email_ok = True
        except Exception:
            logger.exception("Failed to send email")

        try:
            send_telegram(new_jobs, attachments)
        except Exception:
            logger.exception("Failed to send Telegram notification")

        # Mark as sent only if at least one notification channel succeeded
        if email_ok:
            sent_at = datetime.now().isoformat()
            for job in new_jobs:
                if job["id"] in seen:
                    seen[job["id"]]["sent_at"] = sent_at
            _save_seen(seen)
    else:
        logger.warning("No PDFs generated — skipping notifications.")


if __name__ == "__main__":
    main()
